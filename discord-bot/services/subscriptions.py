"""Daily word subscriptions and their jobs.

A subscription targets either a person, delivered by DM, or a server channel. Delivery
times are stored as a local hour plus an IANA timezone, and the next run is recalculated
in that timezone every time the job fires, so daylight saving needs no special case.
"""

import logging
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import config
import db
from services import scheduler

log = logging.getLogger("subscriptions")

USER = "user"
CHANNEL = "channel"

COMMON_TIMEZONES = [
    "Asia/Singapore", "Europe/London", "America/New_York", "America/Los_Angeles",
    "Europe/Berlin", "Asia/Tokyo", "Australia/Sydney", "UTC",
]


def job_key(target_type: str, target_id: int) -> str:
    return f"wotd:{target_type}:{target_id}"


def valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


@lru_cache(maxsize=1)
def all_timezones() -> list[str]:
    return sorted(available_timezones())


def next_run(hour: int, tz_name: str) -> datetime:
    """The next occurrence of hour:00 in the timezone, as an aware datetime."""
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo(config.DEFAULT_TIMEZONE)

    local_now = datetime.now(tz)
    target = local_now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= local_now:
        target += timedelta(days=1)
    return target


def get(target_type: str, target_id: int):
    return db.one(
        "SELECT * FROM subscriptions WHERE target_type = ? AND target_id = ?",
        (target_type, target_id),
    )


def active_in_guild(guild_id: int) -> list:
    return db.query(
        "SELECT * FROM subscriptions WHERE target_type = ? AND guild_id = ? AND active = 1 "
        "ORDER BY hour",
        (CHANNEL, guild_id),
    )


def next_delivery(target_type: str, target_id: int) -> Optional[datetime]:
    stamp = db.scalar("SELECT run_at FROM jobs WHERE dedupe_key = ?", (job_key(target_type, target_id),))
    return db.from_iso(stamp) if stamp else None


def schedule(target_type: str, target_id: int, hour: int, tz_name: str) -> datetime:
    when = next_run(hour, tz_name)
    scheduler.enqueue(
        "daily_wotd",
        {"t": target_type, "id": target_id},
        run_at=db.to_iso(when),
        dedupe_key=job_key(target_type, target_id),
    )
    return when


def enable(target_type: str, target_id: int, *, owner_id: int, guild_id: int | None,
           hour: int, tz_name: str, include_quote: bool) -> datetime:
    """Turn a subscription on, or change one that is on, and schedule the next delivery."""
    db.execute(
        """
        INSERT INTO subscriptions
            (target_type, target_id, guild_id, owner_id, hour, timezone, include_quote, active, failures)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)
        ON CONFLICT (target_type, target_id) DO UPDATE SET
            guild_id = excluded.guild_id, owner_id = excluded.owner_id,
            hour = excluded.hour, timezone = excluded.timezone,
            include_quote = excluded.include_quote, active = 1, failures = 0
        """,
        (target_type, target_id, guild_id, owner_id, hour, tz_name, 1 if include_quote else 0),
    )
    return schedule(target_type, target_id, hour, tz_name)


def update(target_type: str, target_id: int, *, hour: int | None = None,
           tz_name: str | None = None, include_quote: bool | None = None) -> None:
    """Change settings on an existing row, rescheduling if it is on."""
    row = get(target_type, target_id)
    if row is None:
        return
    hour = row["hour"] if hour is None else hour
    tz_name = row["timezone"] if tz_name is None else tz_name
    quote = row["include_quote"] if include_quote is None else (1 if include_quote else 0)
    db.execute(
        "UPDATE subscriptions SET hour = ?, timezone = ?, include_quote = ? "
        "WHERE target_type = ? AND target_id = ?",
        (hour, tz_name, quote, target_type, target_id),
    )
    if row["active"]:
        schedule(target_type, target_id, hour, tz_name)


def stop(target_type: str, target_id: int) -> bool:
    """Turn a subscription off. Returns whether it was on."""
    cursor = db.execute(
        "UPDATE subscriptions SET active = 0 WHERE target_type = ? AND target_id = ? AND active = 1",
        (target_type, target_id),
    )
    scheduler.cancel(job_key(target_type, target_id))
    return bool(cursor.rowcount)


def delete(target_type: str, target_id: int) -> None:
    db.execute("DELETE FROM subscriptions WHERE target_type = ? AND target_id = ?",
               (target_type, target_id))
    scheduler.cancel(job_key(target_type, target_id))


def record_failure(target_type: str, target_id: int) -> int:
    db.execute(
        "UPDATE subscriptions SET failures = failures + 1 WHERE target_type = ? AND target_id = ?",
        (target_type, target_id),
    )
    return db.scalar(
        "SELECT failures FROM subscriptions WHERE target_type = ? AND target_id = ?",
        (target_type, target_id), 0,
    )


def reset_failures(target_type: str, target_id: int) -> None:
    db.execute(
        "UPDATE subscriptions SET failures = 0 WHERE target_type = ? AND target_id = ?",
        (target_type, target_id),
    )


def restore_jobs() -> int:
    """Recreate the job for any active subscription whose row went missing."""
    restored = 0
    for row in db.query("SELECT * FROM subscriptions WHERE active = 1"):
        if scheduler.exists(job_key(row["target_type"], row["target_id"])):
            continue
        schedule(row["target_type"], row["target_id"], row["hour"], row["timezone"])
        restored += 1
    if restored:
        log.info("restored %s daily jobs", restored)
    return restored
