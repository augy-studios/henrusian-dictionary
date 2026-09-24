"""SQLite backed job queue.

No cron and no APScheduler. The queue is a table, which means it survives restarts, and
it can be inspected on the VPS with plain sqlite3 when something looks wrong.
"""

import asyncio
import json
import logging
from datetime import timedelta
from typing import Awaitable, Callable, Optional

import db

log = logging.getLogger("scheduler")

TICK_SECONDS = 15
STALE_LOCK_MINUTES = 10
MAX_ATTEMPTS = 5

_kinds: dict[str, Callable[..., Awaitable[None]]] = {}
_bot = None


def job(kind: str):
    """Register a job handler. Handlers take (bot, payload: dict)."""

    def decorator(func):
        if kind in _kinds:
            raise RuntimeError(f"duplicate job kind registered: {kind}")
        _kinds[kind] = func
        return func

    return decorator


def registered_kinds() -> list[str]:
    return sorted(_kinds)


def enqueue(
    kind: str,
    payload: dict | None = None,
    *,
    delay_seconds: int = 0,
    run_at: Optional[str] = None,
    interval_s: Optional[int] = None,
    dedupe_key: Optional[str] = None,
) -> None:
    """Add a job, or move an existing one with the same dedupe key."""
    when = run_at or db.to_iso(db.now() + timedelta(seconds=delay_seconds))
    db.execute(
        """
        INSERT INTO jobs (kind, payload, run_at, interval_s, dedupe_key)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (dedupe_key) DO UPDATE SET
            kind = excluded.kind,
            run_at = excluded.run_at,
            payload = excluded.payload,
            interval_s = excluded.interval_s,
            status = 'pending',
            attempts = 0,
            locked_at = NULL,
            last_error = NULL
        """,
        (kind, json.dumps(payload or {}, separators=(",", ":")), when, interval_s, dedupe_key),
    )


def ensure_recurring(kind: str, interval_s: int, payload: dict | None = None) -> None:
    """Register a repeating job exactly once, keyed so restarts do not duplicate it."""
    enqueue(kind, payload, delay_seconds=5, interval_s=interval_s, dedupe_key=f"recurring:{kind}")


def cancel(dedupe_key: str) -> None:
    db.execute("DELETE FROM jobs WHERE dedupe_key = ?", (dedupe_key,))


def exists(dedupe_key: str) -> bool:
    return db.one("SELECT 1 FROM jobs WHERE dedupe_key = ?", (dedupe_key,)) is not None


def _claim_due() -> list[dict]:
    """Claim due rows in one pass. Locks older than the stale window are reclaimed, which
    is how a job interrupted by a crash gets picked up again."""
    now = db.to_iso(db.now())
    stale = db.to_iso(db.now() - timedelta(minutes=STALE_LOCK_MINUTES))

    conn = db.connect()
    conn.execute("BEGIN IMMEDIATE")
    try:
        rows = conn.execute(
            """
            SELECT * FROM jobs
            WHERE status = 'pending'
              AND run_at <= ?
              AND (locked_at IS NULL OR locked_at < ?)
            ORDER BY run_at
            LIMIT 20
            """,
            (now, stale),
        ).fetchall()

        claimed = []
        for row in rows:
            conn.execute("UPDATE jobs SET locked_at = ? WHERE id = ?", (now, row["id"]))
            claimed.append({**dict(row), "locked_at": now})
        conn.execute("COMMIT")
        return claimed
    except Exception:
        conn.execute("ROLLBACK")
        raise


async def _run(row: dict) -> None:
    kind = row["kind"]
    handler = _kinds.get(kind)
    if handler is None:
        log.error("no handler for job kind %r, dropping job %s", kind, row["id"])
        db.execute("UPDATE jobs SET status = 'failed', last_error = ? WHERE id = ?",
                   ("unknown kind", row["id"]))
        return

    try:
        payload = json.loads(row["payload"] or "{}")
    except json.JSONDecodeError:
        payload = {}

    try:
        await handler(_bot, payload)
    except Exception as exc:  # a bad job must not take the worker down
        attempts = row["attempts"] + 1
        log.exception("job %s (%s) failed on attempt %s", row["id"], kind, attempts)
        if attempts >= MAX_ATTEMPTS:
            db.execute(
                "UPDATE jobs SET status = 'failed', attempts = ?, last_error = ?, locked_at = NULL "
                "WHERE id = ?",
                (attempts, str(exc)[:400], row["id"]),
            )
        else:
            backoff = min(2 ** attempts * 30, 3600)
            db.execute(
                "UPDATE jobs SET attempts = ?, last_error = ?, run_at = ?, locked_at = NULL "
                "WHERE id = ?",
                (attempts, str(exc)[:400], db.to_iso(db.now() + timedelta(seconds=backoff)), row["id"]),
            )
        return

    if row["interval_s"]:
        db.execute(
            "UPDATE jobs SET run_at = ?, attempts = 0, locked_at = NULL, last_error = NULL "
            "WHERE id = ?",
            (db.to_iso(db.now() + timedelta(seconds=row["interval_s"])), row["id"]),
        )
    else:
        # A handler that rescheduled itself through its dedupe key has already cleared the
        # lock, so matching on it leaves the next occurrence in place.
        db.execute("DELETE FROM jobs WHERE id = ? AND locked_at = ?", (row["id"], row["locked_at"]))


async def worker(bot) -> None:
    """Long running loop. Started once from bot.py, after the gateway is ready."""
    global _bot
    _bot = bot
    await bot.wait_until_ready()
    log.info("scheduler started, handlers: %s", ", ".join(registered_kinds()))

    while True:
        try:
            for row in _claim_due():
                await _run(row)
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)
