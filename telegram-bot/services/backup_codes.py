"""Two factor backup codes, for the case where Telegram itself is unreachable.

With no accounts in the picture, what a code protects is the collection: it releases every
paired browser when Telegram cannot be reached, or moves the whole collection onto a new
Telegram account from here. The codes therefore cannot live in the bot's own database, and are kept
in Supabase where the website can verify them too.

Division of responsibility:

  The website   creates a request, and reveals the codes once, after approval.
  This bot      sends the approval notification and records the decision. It never
                generates or displays a set on its own.
  Both          hash a code the same way, so a code issued on the site redeems here.

On hashing: a code carries 60 bits of entropy (12 Crockford base32 characters) and is
stored as a SHA-256 digest of `pepper:code`, so it can be looked up by index. A per row
salt would force a scan across every unused code on every redemption. Single use, the
pepper, and the lockout below cover the rest.
"""

import hashlib
import logging
import secrets
from datetime import timedelta
from typing import Optional

import config
import db
from services import supabase

log = logging.getLogger("backup_codes")

TABLE = "henrusian15_sync_backup_codes"
REQUESTS = "henrusian15_sync_code_requests"
ATTEMPTS = "henrusian15_sync_recovery_attempts"

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
GROUPS = 3
GROUP_LENGTH = 4


def _raw() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(GROUPS * GROUP_LENGTH))


def pretty(raw: str) -> str:
    return "-".join(raw[i : i + GROUP_LENGTH] for i in range(0, len(raw), GROUP_LENGTH))


def normalise(value: str) -> str:
    """Accept a code however it was typed: spaces, dashes, lower case, ambiguous letters."""
    cleaned = "".join(ch for ch in (value or "").upper() if ch.isalnum())
    return cleaned.translate(str.maketrans("ILOU", "1101"))


def digest(raw: str) -> str:
    """Must stay byte for byte identical to the web app's implementation."""
    return hashlib.sha256(f"{config.BACKUP_CODE_PEPPER}:{normalise(raw)}".encode()).hexdigest()


async def remaining(telegram_user_id: int) -> int:
    rows = await supabase.select(
        TABLE,
        columns="id",
        params={
            "telegram_user_id": supabase.eq(telegram_user_id),
            "used_at": "is.null",
            "revoked_at": "is.null",
        },
    )
    return len(rows)


# -- approval requests -----------------------------------------------------
#
# A request is raised on the website by the linked device. Nothing is issued at that point. The
# bot notices the pending row, sends a notification here, and only an approval in Telegram
# lets the site reveal the set. Rejecting leaves everything as it was, which is what makes
# an unexpected request a useful warning rather than something already done.


async def awaiting_notification() -> list[dict]:
    """Pending requests the bot has not announced yet."""
    return await supabase.select(
        REQUESTS,
        columns="id,telegram_user_id,device_label,status,expires_at,requested_at",
        params={
            "status": supabase.eq("pending"),
            "notified_at": "is.null",
            "expires_at": f"gt.{db.now().isoformat()}",
            "order": "requested_at.asc",
            "limit": 20,
        },
    )


async def mark_notified(request_id) -> None:
    await supabase.update(
        REQUESTS,
        {"id": supabase.eq(request_id)},
        {"notified_at": db.now().isoformat()},
        returning=False,
    )


async def get_request(request_id) -> Optional[dict]:
    return await supabase.select_one(REQUESTS, params={"id": supabase.eq(request_id)})


async def claim_request(request_id, telegram_user_id: int) -> tuple[str, Optional[dict]]:
    """Move a request from pending to approved, exactly once.

    Returns a reason and the row: "ok", "missing", "expired", or "settled" for one that was
    already approved, rejected, consumed or superseded.
    """
    row = await get_request(request_id)
    if row is None or int(row.get("telegram_user_id") or 0) != int(telegram_user_id):
        return "missing", None
    if row.get("status") != "pending":
        return "settled", row

    expires = row.get("expires_at") or ""
    if expires and expires < db.now().isoformat():
        await supabase.update(
            REQUESTS,
            {"id": supabase.eq(request_id), "status": supabase.eq("pending")},
            {"status": "expired", "resolved_at": db.now().isoformat()},
            returning=False,
        )
        return "expired", row

    claimed = await supabase.update(
        REQUESTS,
        {"id": supabase.eq(request_id), "status": supabase.eq("pending")},
        {"status": "approved", "resolved_at": db.now().isoformat()},
    )
    if not claimed:
        return "settled", row
    return "ok", row


async def move_codes(from_telegram_user_id: int, to_telegram_user_id: int) -> int:
    """Codes protect the collection, so they travel with it when it changes hands.

    The set that was already on the receiving side is revoked, since two live sets for one
    collection would be confusing and only one of them is written down anywhere.
    """
    await supabase.update(
        TABLE,
        {
            "telegram_user_id": supabase.eq(to_telegram_user_id),
            "used_at": "is.null",
            "revoked_at": "is.null",
        },
        {"revoked_at": db.now().isoformat()},
        returning=False,
    )
    moved = await supabase.update(
        TABLE,
        {"telegram_user_id": supabase.eq(from_telegram_user_id)},
        {"telegram_user_id": to_telegram_user_id},
    )
    return len(moved) if isinstance(moved, list) else 0


async def reject_request(request_id, telegram_user_id: int) -> bool:
    rejected = await supabase.update(
        REQUESTS,
        {
            "id": supabase.eq(request_id),
            "telegram_user_id": supabase.eq(telegram_user_id),
            "status": supabase.eq("pending"),
        },
        {"status": "rejected", "resolved_at": db.now().isoformat()},
    )
    return bool(rejected)


# -- redemption ------------------------------------------------------------


def locked_out(telegram_user_id: int) -> int:
    """Seconds left on a lockout for this Telegram account, or 0.

    Counted locally as well as in Supabase, so a locked out caller cannot make the bot talk
    to the database at all.
    """
    window = db.to_iso(db.now() - timedelta(minutes=config.RECOVERY_LOCKOUT_MINUTES))
    failures = db.scalar(
        "SELECT COUNT(*) FROM link_attempts "
        "WHERE telegram_user_id = ? AND outcome = 'recover-failed' AND created_at >= ?",
        (telegram_user_id, window),
        0,
    )
    if failures < config.RECOVERY_LOCKOUT_ATTEMPTS:
        return 0

    oldest = db.scalar(
        "SELECT MIN(created_at) FROM link_attempts "
        "WHERE telegram_user_id = ? AND outcome = 'recover-failed' AND created_at >= ?",
        (telegram_user_id, window),
    )
    if not oldest:
        return 0
    unlock_at = db.from_iso(oldest) + timedelta(minutes=config.RECOVERY_LOCKOUT_MINUTES)
    return max(0, int((unlock_at - db.now()).total_seconds()))


async def collection_locked_out(telegram_user_id: int) -> int:
    """Seconds left on a lockout for the collection itself, whichever client was used.

    This is what stops someone hopping between Telegram accounts to reset the per link
    limit. It can only count attempts that are attributable, meaning every attempt made from
    the linked device on the website, plus bot attempts on a code that exists but is spent
    or revoked. A wholly wrong code cannot be pinned to a collection by anybody, which is what
    the 60 bits of entropy and the pepper are there for.
    """
    since = (db.now() - timedelta(minutes=config.RECOVERY_LOCKOUT_MINUTES)).isoformat()
    rows = await supabase.select(
        ATTEMPTS,
        columns="created_at",
        params={
            "telegram_user_id": supabase.eq(telegram_user_id),
            "succeeded": "eq.false",
            "created_at": f"gte.{since}",
            "order": "created_at.asc",
        },
    )
    if len(rows) < config.RECOVERY_LOCKOUT_ATTEMPTS:
        return 0

    oldest = rows[0].get("created_at") or ""
    try:
        unlock_at = db.from_iso(oldest[:19].replace("T", " ")) + timedelta(
            minutes=config.RECOVERY_LOCKOUT_MINUTES
        )
    except ValueError:
        return config.RECOVERY_LOCKOUT_MINUTES * 60
    return max(0, int((unlock_at - db.now()).total_seconds()))


def _record_local(telegram_user_id: int, outcome: str) -> None:
    db.execute(
        "INSERT INTO link_attempts (telegram_user_id, outcome) VALUES (?, ?)",
        (telegram_user_id, outcome),
    )


async def _record(by_telegram_user_id: int, succeeded: bool,
                  telegram_user_id: Optional[int] = None) -> None:
    _record_local(by_telegram_user_id, "recover-ok" if succeeded else "recover-failed")
    try:
        await supabase.insert(
            ATTEMPTS,
            {
                "telegram_user_id": telegram_user_id,
                "by_telegram_user_id": by_telegram_user_id,
                "source": "bot",
                "succeeded": succeeded,
            },
            returning=False,
        )
    except supabase.SupabaseError:
        # The local record is enough to enforce the per Telegram lockout, so a failure to
        # write the shared log must not block a legitimate recovery.
        log.warning("could not record the recovery attempt in the database")


async def redeem(code: str, telegram_user_id: int) -> Optional[int]:
    """Spend a code, returning the Telegram account whose collection it unlocks, or None.

    The update is conditional on used_at still being null, so two racing redemptions cannot
    both succeed.
    """
    code_hash = digest(code)

    row = await supabase.select_one(
        TABLE,
        columns="id,telegram_user_id,used_at,revoked_at",
        params={"code_hash": supabase.eq(code_hash)},
    )
    if row is None:
        # Not attributable to any collection, so only the per Telegram counter moves.
        await _record(telegram_user_id, False)
        return None

    owner = row["telegram_user_id"]

    if row.get("used_at") or row.get("revoked_at"):
        # A code that exists but is spent or revoked does name a collection, so this
        # attempt counts against it too.
        await _record(telegram_user_id, False, owner)
        return None

    locked = await collection_locked_out(owner)
    if locked:
        await _record(telegram_user_id, False, owner)
        return None

    claimed = await supabase.update(
        TABLE,
        {"id": supabase.eq(row["id"]), "used_at": "is.null"},
        {"used_at": db.now().isoformat(), "used_by_telegram_id": telegram_user_id},
    )
    if not claimed:
        await _record(telegram_user_id, False, owner)
        return None

    await _record(telegram_user_id, True, owner)
    return owner
