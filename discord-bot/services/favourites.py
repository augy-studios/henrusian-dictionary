"""Saved entries, per Discord account, in SQLite only.

These do not sync with the browser or with the Telegram bot. The shared favourites table
in Supabase is keyed on Telegram ids, and the website's pairing flow only knows Telegram.
"""

import db


def is_favourite(user_id: int, tab: str, entry_id: str) -> bool:
    return db.one(
        "SELECT 1 FROM favourites WHERE discord_user_id = ? AND tab = ? AND entry_id = ?",
        (user_id, tab, str(entry_id)),
    ) is not None


def add(user_id: int, tab: str, entry_id: str) -> None:
    db.execute(
        "INSERT OR IGNORE INTO favourites (discord_user_id, tab, entry_id) VALUES (?, ?, ?)",
        (user_id, tab, str(entry_id)),
    )


def remove(user_id: int, tab: str, entry_id: str) -> None:
    db.execute(
        "DELETE FROM favourites WHERE discord_user_id = ? AND tab = ? AND entry_id = ?",
        (user_id, tab, str(entry_id)),
    )


def toggle(user_id: int, tab: str, entry_id: str) -> bool:
    """Flip the saved state and return the new one."""
    if is_favourite(user_id, tab, entry_id):
        remove(user_id, tab, entry_id)
        return False
    add(user_id, tab, entry_id)
    return True


def ids_for(user_id: int) -> list[tuple[str, str]]:
    rows = db.query(
        "SELECT tab, entry_id FROM favourites WHERE discord_user_id = ? ORDER BY created_at",
        (user_id,),
    )
    return [(row["tab"], row["entry_id"]) for row in rows]


def clear(user_id: int) -> int:
    cursor = db.execute("DELETE FROM favourites WHERE discord_user_id = ?", (user_id,))
    return cursor.rowcount or 0
