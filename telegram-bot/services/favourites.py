"""Favourites, before and after a link exists.

The collection belongs to the Telegram account, so every browser paired with it shares one
set. Someone who has not linked anything can still save entries, and those live in the bot's
own SQLite file until a link exists.

Linking merges the browser's set with the bot's, by union, so neither side loses a favourite
and nothing is stored twice. When the last browser is unpaired, the collection is copied back
into local storage before it is deleted.
"""

import logging
from typing import Iterable, Optional

import db
from services import linking, supabase

log = logging.getLogger("favourites")

TABLE = "henrusian15_sync_favourites"
VALID_TABS = ("dict", "idioms", "names")


# -- local, for anyone who has not linked ----------------------------------


def local_ids(telegram_user_id: int) -> set[tuple[str, str]]:
    rows = db.query(
        "SELECT tab, entry_id FROM favourites_local WHERE telegram_user_id = ?",
        (telegram_user_id,),
    )
    return {(r["tab"], r["entry_id"]) for r in rows}


def _local_toggle(telegram_user_id: int, tab: str, entry_id: str) -> bool:
    existing = db.one(
        "SELECT 1 FROM favourites_local WHERE telegram_user_id = ? AND tab = ? AND entry_id = ?",
        (telegram_user_id, tab, entry_id),
    )
    if existing:
        db.execute(
            "DELETE FROM favourites_local WHERE telegram_user_id = ? AND tab = ? AND entry_id = ?",
            (telegram_user_id, tab, entry_id),
        )
        return False
    db.execute(
        "INSERT INTO favourites_local (telegram_user_id, tab, entry_id) VALUES (?, ?, ?)",
        (telegram_user_id, tab, entry_id),
    )
    return True


def _local_add_many(telegram_user_id: int, pairs: Iterable[tuple[str, str]]) -> int:
    rows = [(telegram_user_id, tab, entry_id) for tab, entry_id in pairs]
    if not rows:
        return 0
    db.executemany(
        "INSERT OR IGNORE INTO favourites_local (telegram_user_id, tab, entry_id) VALUES (?, ?, ?)",
        rows,
    )
    return len(rows)


# -- shared, once a link exists --------------------------------------------


async def shared_ids(telegram_user_id: int) -> set[tuple[str, str]]:
    """The collection for a Telegram account, shared by every browser paired with it."""
    rows = await supabase.select(
        TABLE, columns="tab,entry_id",
        params={"telegram_user_id": supabase.eq(telegram_user_id)},
    )
    return {(r["tab"], str(r["entry_id"])) for r in rows}


# -- one interface over both -----------------------------------------------


async def ids_for(telegram_user_id: int) -> set[tuple[str, str]]:
    """Every (tab, entry_id) this user has saved, wherever it happens to live."""
    if not linking.cached_linked(telegram_user_id):
        return local_ids(telegram_user_id)

    try:
        return await shared_ids(telegram_user_id)
    except supabase.SupabaseError:
        log.warning("shared favourites unreadable, falling back to the local set")
        return local_ids(telegram_user_id)


async def is_favourite(telegram_user_id: int, tab: str, entry_id: str) -> bool:
    return (tab, str(entry_id)) in await ids_for(telegram_user_id)


async def toggle(telegram_user_id: int, tab: str, entry_id: str) -> bool:
    """Add or remove, returning the state afterwards."""
    entry_id = str(entry_id)
    if not linking.cached_linked(telegram_user_id):
        return _local_toggle(telegram_user_id, tab, entry_id)

    existing = await supabase.select_one(
        TABLE,
        columns="id",
        params={
            "telegram_user_id": supabase.eq(telegram_user_id),
            "tab": supabase.eq(tab),
            "entry_id": supabase.eq(entry_id),
        },
    )
    if existing:
        await supabase.delete(TABLE, {"id": supabase.eq(existing["id"])})
        return False

    await supabase.insert(
        TABLE,
        {"telegram_user_id": telegram_user_id, "tab": tab, "entry_id": entry_id},
        upsert=True,
        returning=False,
    )
    return True


def _clean(pairs: Iterable) -> set[tuple[str, str]]:
    """Filter whatever arrived down to well formed (tab, entry_id) pairs."""
    out: set[tuple[str, str]] = set()
    for item in pairs or []:
        if isinstance(item, dict):
            tab = str(item.get("tab") or "")
            entry_id = str(item.get("id") or item.get("entry_id") or "")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            tab, entry_id = str(item[0]), str(item[1])
        else:
            continue
        if tab in VALID_TABS and entry_id and len(entry_id) <= 64:
            out.add((tab, entry_id))
    return out


async def merge_on_link(telegram_user_id: int,
                        device_favourites: Optional[Iterable] = None) -> dict:
    """Union of three sets: what the browser had, what the bot had, and anything already
    shared. Duplicates cannot survive, because the unique index and the local primary key
    both cover (tab, entry_id)."""
    from_device = _clean(device_favourites)
    from_bot = local_ids(telegram_user_id)

    try:
        already = await shared_ids(telegram_user_id)
    except supabase.SupabaseError:
        already = set()

    missing = sorted((from_device | from_bot) - already)
    if missing:
        await supabase.insert(
            TABLE,
            [{"telegram_user_id": telegram_user_id, "tab": tab, "entry_id": entry_id}
             for tab, entry_id in missing],
            upsert=True,
            returning=False,
        )

    db.execute("DELETE FROM favourites_local WHERE telegram_user_id = ?", (telegram_user_id,))

    total = len(already | from_device | from_bot)
    log.info(
        "merged favourites for %s: device %s, bot %s, already shared %s, total %s",
        telegram_user_id, len(from_device), len(from_bot), len(already), total,
    )
    return {
        "from_device": len(from_device),
        "from_bot": len(from_bot),
        "added": len(missing),
        "total": total,
    }


async def drop_shared(telegram_user_id: int) -> None:
    """Delete the collection, once every side holds its own copy."""
    try:
        await supabase.delete(TABLE, {"telegram_user_id": supabase.eq(telegram_user_id)})
    except supabase.SupabaseError:
        log.warning("could not clear the shared favourites for %s", telegram_user_id)


async def move_collection(from_telegram_user_id: int, to_telegram_user_id: int) -> int:
    """Move a collection to a different Telegram account, merging rather than colliding
    if the new one already had favourites of its own."""
    try:
        theirs = await shared_ids(to_telegram_user_id)
        ours = await shared_ids(from_telegram_user_id)
    except supabase.SupabaseError:
        return 0

    missing = sorted(ours - theirs)
    if missing:
        await supabase.insert(
            TABLE,
            [{"telegram_user_id": to_telegram_user_id, "tab": tab, "entry_id": entry_id}
             for tab, entry_id in missing],
            upsert=True,
            returning=False,
        )
    await drop_shared(from_telegram_user_id)
    return len(theirs | ours)


async def keep_local_copy(telegram_user_id: int) -> int:
    """Copy the collection into local storage, for use before the last link goes."""
    try:
        pairs = await shared_ids(telegram_user_id)
    except supabase.SupabaseError:
        return 0
    return _local_add_many(telegram_user_id, pairs)
