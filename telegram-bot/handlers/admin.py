"""Owner commands. These are not registered with BotFather, so they stay out of the menu."""

import logging
import secrets

import config
import db
from handlers.common import args_of, cmd, owner_only, safe
from services import entries, external, scheduler, supabase
from utils.reply import reply_rich, send_rich_message
from utils.rich import compose, escape_md, table

log = logging.getLogger("admin")


def build_health() -> dict:
    """The /health screen: runtime counters as a key/value table."""
    counts = entries.counts()
    age = entries.cache_age_seconds()
    size_mb = config.SQLITE_PATH.stat().st_size / 1_048_576 if config.SQLITE_PATH.exists() else 0
    subs = db.scalar("SELECT COUNT(*) FROM subscriptions WHERE active = 1", (), 0)
    users = db.scalar("SELECT COUNT(*) FROM users", (), 0)
    tokens = db.scalar("SELECT COUNT(*) FROM callbacks", (), 0)
    failed = db.scalar("SELECT COUNT(*) FROM jobs WHERE status = 'failed'", (), 0)
    pending_out = db.scalar("SELECT COUNT(*) FROM outbox WHERE status = 'pending'", (), 0)

    rows = [
        ["Catalogue", f"{counts['dict']} words, {counts['idioms']} idioms, {counts['names']} names"],
        ["Cache age", "unknown" if age is None else f"{age // 60} minutes"],
        ["Users seen", users],
        ["Active subscriptions", subs],
        ["Button tokens", tokens],
        ["Jobs pending", f"{scheduler.pending_count()}, failed: {failed}"],
        ["Outbox pending", pending_out],
        ["Database", f"{size_mb:.1f} MB"],
        ["Last database error", supabase.last_error or "none"],
    ]
    return compose("Health", table(["Value"], rows))


def register(client):
    @client.on(cmd("health"))
    @owner_only
    @safe
    async def on_health(event):
        await reply_rich(event, build_health())

    @client.on(cmd("broadcast"))
    @owner_only
    @safe
    async def on_broadcast(event):
        message = args_of(event)
        if not message:
            await reply_rich(event, compose(
                "Nothing to send",
                "Send /broadcast followed by the message. It goes to every active "
                "subscriber, paced so Telegram does not rate limit it.",
            ))
            return

        targets = db.query("SELECT chat_id FROM subscriptions WHERE active = 1")
        if not targets:
            await reply_rich(event, compose(
                "No recipients",
                "Nobody has an active subscription, so there is nobody to send to.",
            ))
            return

        batch = secrets.token_hex(6)
        db.executemany(
            "INSERT INTO outbox (batch, chat_id, body) VALUES (?, ?, ?)",
            [(batch, row["chat_id"], message) for row in targets],
        )
        scheduler.enqueue("broadcast_chunk", {"batch": batch}, delay_seconds=2,
                          dedupe_key=f"broadcast:{batch}")

        await reply_rich(event, compose(
            "Broadcast queued",
            f"{len(targets)} recipients, sent {config.BROADCAST_CHUNK} at a time. "
            "The queue survives a restart, so an interrupted send resumes rather than "
            "starting over.",
        ))

    @client.on(cmd("refresh"))
    @owner_only
    @safe
    async def on_refresh(event):
        counts = await entries.refresh_all()
        external.prune_cache()
        await reply_rich(event, compose(
            "Catalogue refreshed",
            table(["Entries"], [[entries.LABELS[tab], count] for tab, count in counts.items()]),
        ))


@scheduler.job("broadcast_chunk")
async def broadcast_chunk(client, payload):
    """Send one chunk, then reschedule while rows remain."""
    batch = payload["batch"]
    rows = db.query(
        "SELECT * FROM outbox WHERE batch = ? AND status = 'pending' ORDER BY id LIMIT ?",
        (batch, config.BROADCAST_CHUNK),
    )
    if not rows:
        scheduler.cancel(f"broadcast:{batch}")
        return

    for row in rows:
        try:
            await send_rich_message(client, row["chat_id"],
                                    compose("A note from the maintainer", escape_md(row["body"])))
            db.execute(
                "UPDATE outbox SET status = 'sent', sent_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
        except Exception as exc:  # a blocked or deleted chat must not stall the batch
            log.warning("broadcast to %s failed: %s", row["chat_id"], exc)
            db.execute(
                "UPDATE outbox SET status = 'failed', error = ? WHERE id = ?",
                (str(exc)[:200], row["id"]),
            )

    remaining = db.scalar(
        "SELECT COUNT(*) FROM outbox WHERE batch = ? AND status = 'pending'", (batch,), 0
    )
    if remaining:
        scheduler.enqueue("broadcast_chunk", {"batch": batch},
                          delay_seconds=config.BROADCAST_CHUNK_DELAY,
                          dedupe_key=f"broadcast:{batch}")
    else:
        scheduler.cancel(f"broadcast:{batch}")
        if config.BOT_OWNER_ID:
            sent = db.scalar("SELECT COUNT(*) FROM outbox WHERE batch = ? AND status = 'sent'",
                             (batch,), 0)
            failed = db.scalar("SELECT COUNT(*) FROM outbox WHERE batch = ? AND status = 'failed'",
                               (batch,), 0)
            await send_rich_message(
                client, config.BOT_OWNER_ID,
                compose("Broadcast finished", f"Delivered to {sent} chats, {failed} failed."),
            )
