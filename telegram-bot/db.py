"""SQLite access. One connection, WAL enabled, opened once at boot.

Every call here is synchronous and measured in microseconds, so it runs directly on
the event loop rather than through an executor. Wrapping it would add complexity for
no gain at this scale.
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Sequence

import config

_conn: Optional[sqlite3.Connection] = None


def now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now().strftime("%Y-%m-%d %H:%M:%S")


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
    _conn.execute("PRAGMA foreign_keys=ON")
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


def touch_user_id(user_id: int, username: str | None = None,
                  first_name: str | None = None) -> sqlite3.Row:
    """Upsert by numeric id and return the stored row.

    The id is always on the event, while the sender object is fetched lazily by Telethon
    and is often absent, so the row is keyed on the id and the names fill in when known.
    """
    uid = int(user_id)
    execute(
        """
        INSERT INTO users (telegram_user_id, username, first_name, timezone)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (telegram_user_id) DO UPDATE SET
            username     = COALESCE(excluded.username, users.username),
            first_name   = COALESCE(excluded.first_name, users.first_name),
            last_seen_at = datetime('now')
        """,
        (uid, username, first_name, config.DEFAULT_TIMEZONE),
    )
    return one("SELECT * FROM users WHERE telegram_user_id = ?", (uid,))


def touch_user(user) -> sqlite3.Row:
    """Upsert the Telegram user behind an event and return the stored row."""
    return touch_user_id(
        int(user.id), getattr(user, "username", None), getattr(user, "first_name", None)
    )


def get_user(user_id: int) -> Optional[sqlite3.Row]:
    return one("SELECT * FROM users WHERE telegram_user_id = ?", (user_id,))


def set_pending(user_id: int, pending: Optional[dict]) -> None:
    execute(
        "UPDATE users SET pending = ? WHERE telegram_user_id = ?",
        (json.dumps(pending) if pending else None, user_id),
    )


def get_pending(user_id: int) -> Optional[dict]:
    raw = scalar("SELECT pending FROM users WHERE telegram_user_id = ?", (user_id,))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def user_timezone(user_id: int) -> str:
    return scalar(
        "SELECT timezone FROM users WHERE telegram_user_id = ?", (user_id,), config.DEFAULT_TIMEZONE
    ) or config.DEFAULT_TIMEZONE


# -- rendered views ---------------------------------------------------------


def remember_view(chat_id: int, message_id: int, view: str, params: dict) -> None:
    execute(
        """
        INSERT INTO ui_views (chat_id, message_id, view, params, updated_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT (chat_id, message_id) DO UPDATE SET
            view = excluded.view, params = excluded.params, updated_at = datetime('now')
        """,
        (chat_id, message_id, view, json.dumps(params, separators=(",", ":"))),
    )
