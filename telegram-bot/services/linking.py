"""Pairing browsers with a Telegram account.

There are no accounts and no sign in anywhere in this project. A link is a pairing between
one browser and one Telegram account, so that favourites can be shared.

One Telegram account can pair with as many browsers as it likes, and they all share the same
collection. A browser belongs to one Telegram account at a time.

Linking always starts on the website, because only the browser knows which device is being
paired. The site mints a short lived token and sends the visitor to

    https://t.me/<bot>?start=<token>

Tapping Start hands the token to this bot, which claims it and creates the link. The same
token can also be typed in with /code, for anyone whose browser cannot open the deep link.
"""

import logging
from typing import Optional

import db
from services import supabase

log = logging.getLogger("linking")

LINKS = "henrusian15_sync_links"
TOKENS = "henrusian15_sync_tokens"

TOKEN_LENGTH = 8


def normalise_token(value: str) -> str:
    """Accept a token however it arrives: lower case, spaced, or with ambiguous letters."""
    cleaned = "".join(ch for ch in (value or "").upper() if ch.isalnum())
    return cleaned.translate(str.maketrans("ILOU", "1101"))


async def linked_devices(telegram_user_id: int) -> list[dict]:
    """Every browser currently paired with this Telegram account, newest first."""
    return await supabase.select(
        LINKS,
        params={
            "telegram_user_id": supabase.eq(telegram_user_id),
            "revoked_at": "is.null",
            "order": "linked_at.desc",
        },
    )


async def get_link(telegram_user_id: int) -> Optional[dict]:
    """The most recent live link, or None. Refreshes the local cache of the link state.

    Callers that only need to know whether anything is paired use this; callers that need to
    list the browsers use linked_devices.
    """
    rows = await linked_devices(telegram_user_id)
    row = rows[0] if rows else None
    db.execute(
        "UPDATE users SET linked = ?, linked_at = ? WHERE telegram_user_id = ?",
        (1 if row else 0, row["linked_at"] if row else None, telegram_user_id),
    )
    return row


def cached_linked(telegram_user_id: int) -> bool:
    """The last known state, for paths where a round trip is not worth it."""
    return bool(db.scalar(
        "SELECT linked FROM users WHERE telegram_user_id = ?", (telegram_user_id,), 0
    ))


async def claim_token(token: str, telegram_user_id: int,
                      username: Optional[str]) -> tuple[str, Optional[dict]]:
    """Turn a pairing token into a link.

    Returns a reason and, on success, the new link row plus the favourites the browser sent
    along with the token:

        ("ok", {"link": {...}, "device_favourites": [...], "first": bool})
        ("unknown", None)   no such token, already used, or expired
    """
    cleaned = normalise_token(token)
    if len(cleaned) != TOKEN_LENGTH:
        return "unknown", None

    row = await supabase.select_one(
        TOKENS,
        params={
            "token": supabase.eq(cleaned),
            "used_at": "is.null",
            "expires_at": f"gt.{db.now().isoformat()}",
        },
    )
    if row is None:
        return "unknown", None

    already = await linked_devices(telegram_user_id)

    # Claim the token first, conditional on it still being unused, so two taps on the same
    # deep link cannot both create a link.
    claimed = await supabase.update(
        TOKENS,
        {"token": supabase.eq(cleaned), "used_at": "is.null"},
        {"used_at": db.now().isoformat(), "used_by": telegram_user_id},
    )
    if not claimed:
        return "unknown", None

    link = await bind(
        telegram_user_id,
        device_id=row["device_id"],
        device_secret_hash=row["device_secret_hash"],
        device_label=row.get("device_label"),
        username=username,
    )
    favourites = row.get("favourites") or []
    if not isinstance(favourites, list):
        favourites = []

    db.execute(
        "INSERT INTO link_attempts (telegram_user_id, code, outcome) VALUES (?, ?, 'linked')",
        (telegram_user_id, cleaned),
    )
    return "ok", {
        "link": link,
        "device_favourites": favourites,
        "first": not already,
        "devices": len(already) + (0 if any(d["device_id"] == row["device_id"] for d in already) else 1),
    }


async def bind(telegram_user_id: int, *, device_id: str, device_secret_hash: str,
               device_label: Optional[str], username: Optional[str]) -> dict:
    """Create the link row for one device, replacing any live link that device already had.

    Other browsers paired with the same Telegram account are left alone, which is what makes
    several of them possible.
    """
    await supabase.update(
        LINKS,
        {"device_id": supabase.eq(device_id), "revoked_at": "is.null"},
        {"revoked_at": db.now().isoformat()},
        returning=False,
    )

    rows = await supabase.insert(
        LINKS,
        {
            "device_id": device_id,
            "device_secret_hash": device_secret_hash,
            "device_label": device_label,
            "telegram_user_id": telegram_user_id,
            "telegram_username": username,
            "linked_at": db.now().isoformat(),
        },
    )
    link = rows[0] if rows else {}
    db.execute(
        "UPDATE users SET linked = 1, linked_at = datetime('now') WHERE telegram_user_id = ?",
        (telegram_user_id,),
    )
    return link


async def move_collection(from_telegram_user_id: int, to_telegram_user_id: int,
                          username: Optional[str]) -> int:
    """Hand every browser, and the collection with it, to a different Telegram account.

    Used by the recovery path. Favourites move in services.favourites, since a merge may be
    needed when the new Telegram account already had some of its own.
    """
    await supabase.update(
        LINKS,
        {"telegram_user_id": supabase.eq(to_telegram_user_id), "revoked_at": "is.null"},
        {"revoked_at": db.now().isoformat()},
        returning=False,
    )
    moved = await supabase.update(
        LINKS,
        {"telegram_user_id": supabase.eq(from_telegram_user_id), "revoked_at": "is.null"},
        {"telegram_user_id": to_telegram_user_id, "telegram_username": username},
    )

    db.execute(
        "UPDATE users SET linked = 0, linked_at = NULL WHERE telegram_user_id = ?",
        (from_telegram_user_id,),
    )
    db.execute(
        "UPDATE users SET linked = 1, linked_at = datetime('now') WHERE telegram_user_id = ?",
        (to_telegram_user_id,),
    )
    return len(moved) if isinstance(moved, list) else 0


async def unlink_all(telegram_user_id: int) -> int:
    """Revoke every live link for this Telegram account. Returns how many were removed."""
    rows = await linked_devices(telegram_user_id)
    if not rows:
        return 0

    await supabase.update(
        LINKS,
        {"telegram_user_id": supabase.eq(telegram_user_id), "revoked_at": "is.null"},
        {"revoked_at": db.now().isoformat()},
        returning=False,
    )
    db.execute(
        "UPDATE users SET linked = 0, linked_at = NULL WHERE telegram_user_id = ?",
        (telegram_user_id,),
    )
    return len(rows)


async def unlink_device(telegram_user_id: int, link_id: int) -> Optional[dict]:
    """Revoke one browser, leaving the others paired."""
    row = await supabase.select_one(
        LINKS,
        params={
            "id": supabase.eq(link_id),
            "telegram_user_id": supabase.eq(telegram_user_id),
            "revoked_at": "is.null",
        },
    )
    if row is None:
        return None

    await supabase.update(
        LINKS,
        {"id": supabase.eq(link_id), "revoked_at": "is.null"},
        {"revoked_at": db.now().isoformat()},
        returning=False,
    )
    await get_link(telegram_user_id)
    return row


def describe(row: dict) -> str:
    """A short label for one paired browser."""
    label = (row or {}).get("device_label") or "a browser"
    since = ((row or {}).get("linked_at") or "")[:10]
    return f"{label}, since {since}" if since else label
