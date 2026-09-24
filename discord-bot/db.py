"""SQLite access. One connection, WAL enabled, opened once at boot.

Every call here is synchronous and measured in microseconds, so it runs directly on
the event loop rather than through an executor. Wrapping it would add complexity for
no gain at this scale.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Sequence

import config

_conn: Optional[sqlite3.Connection] = None


def now() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def from_iso(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn

    config.SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(config.SQLITE_PATH, isolation_level=None, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA busy_timeout=5000")
    _conn.execute("PRAGMA synchronous=NORMAL")
    return _conn


def apply_schema() -> None:
    schema = (config.ROOT / "schema.sql").read_text(encoding="utf-8")
    connect().executescript(schema)
    set_meta("schema_version", "1")


def execute(sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
    return connect().execute(sql, params)


def executemany(sql: str, rows: Iterable[Sequence[Any]]) -> sqlite3.Cursor:
    return connect().executemany(sql, rows)


def query(sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
    return connect().execute(sql, params).fetchall()


def one(sql: str, params: Sequence[Any] = ()) -> Optional[sqlite3.Row]:
    return connect().execute(sql, params).fetchone()


def scalar(sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
    row = one(sql, params)
    return default if row is None else row[0]


def get_meta(key: str, default: Optional[str] = None) -> Optional[str]:
    return scalar("SELECT value FROM meta WHERE key = ?", (key,), default)


def set_meta(key: str, value: str) -> None:
    execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# -- users ------------------------------------------------------------------


def touch_user(user) -> None:
    """Upsert the Discord user behind an interaction."""
    execute(
        """
        INSERT INTO users (discord_user_id, username, display_name, timezone)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (discord_user_id) DO UPDATE SET
            username     = excluded.username,
            display_name = excluded.display_name,
            last_seen_at = datetime('now')
        """,
        (int(user.id), user.name, getattr(user, "display_name", None), config.DEFAULT_TIMEZONE),
    )


def user_timezone(user_id: int) -> str:
    return scalar(
        "SELECT timezone FROM users WHERE discord_user_id = ?", (user_id,), config.DEFAULT_TIMEZONE
    ) or config.DEFAULT_TIMEZONE


def set_user_timezone(user_id: int, name: str) -> None:
    execute("UPDATE users SET timezone = ? WHERE discord_user_id = ?", (name, user_id))
