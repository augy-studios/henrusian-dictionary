"""Per-user cooldowns, kept in SQLite so they survive a restart."""

from datetime import timedelta

import db


def allow(user_id: int, key: str, limit: int, window_seconds: int) -> bool:
    """True when the call is within budget. Rolls the window when it has expired."""
    row = db.one(
        "SELECT hits, window_at FROM ratelimits WHERE user_id = ? AND key = ?",
        (user_id, key),
    )
    now = db.now()

    if row is not None:
        started = db.from_iso(row["window_at"])
        if now - started < timedelta(seconds=window_seconds):
            if row["hits"] >= limit:
                return False
            db.execute(
                "UPDATE ratelimits SET hits = hits + 1 WHERE user_id = ? AND key = ?",
                (user_id, key),
            )
            return True

    db.execute(
        """
        INSERT INTO ratelimits (user_id, key, hits, window_at)
        VALUES (?, ?, 1, ?)
        ON CONFLICT (user_id, key) DO UPDATE SET hits = 1, window_at = excluded.window_at
        """,
        (user_id, key, db.to_iso(now)),
    )
    return True


def retry_after(user_id: int, key: str, window_seconds: int) -> int:
    """Seconds left in the current window, for a message that says when to try again."""
    started = db.scalar(
        "SELECT window_at FROM ratelimits WHERE user_id = ? AND key = ?", (user_id, key)
    )
    if not started:
        return 0
    elapsed = (db.now() - db.from_iso(started)).total_seconds()
    return max(0, int(window_seconds - elapsed))
