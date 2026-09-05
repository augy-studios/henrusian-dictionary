#!/usr/bin/env python3
"""Entry point.

Start with ./run.sh inside tmux. The process is designed to be killed and restarted at
any moment: every piece of state that matters lives in SQLite or in Supabase, including
the button tokens and the job queue, so nothing is lost by a restart.
"""

import asyncio
import logging
import logging.handlers
import sys

from telethon import TelegramClient, events

import config
import db
from handlers import admin, favourites, inline, linking, search, start, subscriptions
from services import buttons, entries, external, scheduler, supabase

log = logging.getLogger("bot")

HANDLER_MODULES = [start, search, favourites, linking, subscriptions, admin, inline]


def setup_logging() -> None:
    config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)-14s %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        config.LOG_PATH, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    # Telethon is chatty at INFO once connected.
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def register_callbacks(client) -> None:
    """One dispatcher for every inline button in the bot.

    The callback data is only a token. The action and its parameters are read back from
    SQLite, which is why a button keeps working after a restart, and indefinitely.
    """

    @client.on(events.CallbackQuery())
    async def on_callback(event):
        record = buttons.resolve(event.data)
        if record is None:
            await event.answer(
                "This button is no longer available. Send /start to begin again.", alert=True
            )
            return

        owner = record.get("user_id")
        if owner and event.sender_id != owner:
            await event.answer(
                "This message belongs to someone else. Send /start for your own.", alert=True
            )
            return

        handler = buttons.handler_for(record["action"])
        if handler is None:
            log.warning("no handler registered for action %r", record["action"])
            await event.answer("That action is not available any more.", alert=True)
            return

        sender = await event.get_sender()
        if sender is not None:
            db.touch_user(sender)

        try:
            await handler(event, record["params"])
        except Exception:
            log.exception("callback %s failed", record["action"])
            try:
                await event.answer("Something went wrong. Please try again.", alert=True)
            except Exception:
                pass


def seed_jobs() -> None:
    """Recurring work, plus any daily subscription whose job row went missing."""
    scheduler.ensure_recurring("refresh_entries", config.ENTRY_REFRESH_SECONDS)
    scheduler.ensure_recurring("prune_cache", 3600)
    # The website cannot message anybody, so this is what turns a recovery code request
    # raised there into an approval prompt here.
    scheduler.ensure_recurring("code_request_poll", config.CODE_POLL_SECONDS)
    # An unlink from the browser only revokes the row. This is the side that keeps a copy of
    # the shared favourites and tells the person it happened.
    scheduler.ensure_recurring("link_sweep", config.LINK_SWEEP_SECONDS)

    for row in db.query("SELECT chat_id, hour, timezone FROM subscriptions WHERE active = 1"):
        key = f"wotd:{row['chat_id']}"
        if db.one("SELECT 1 FROM jobs WHERE dedupe_key = ?", (key,)):
            continue
        when = subscriptions.next_run_utc(row["hour"], row["timezone"])
        scheduler.enqueue("daily_wotd", {"chat_id": row["chat_id"]},
                          run_at=db.to_iso(when), dedupe_key=key)
        log.info("restored the daily job for chat %s", row["chat_id"])


async def main() -> None:
    config.verify()
    setup_logging()

    db.connect()
    db.apply_schema()
    entries.load_from_disk()

    config.SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(config.SESSION_PATH), config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH)

    for module in HANDLER_MODULES:
        if hasattr(module, "register"):
            module.register(client)
    register_callbacks(client)

    log.info("callback actions: %s", ", ".join(buttons.registered_actions()))

    await client.start(bot_token=config.TELEGRAM_BOT_TOKEN)
    me = await client.get_me()
    log.info("signed in as @%s", me.username)

    seed_jobs()
    worker = asyncio.create_task(scheduler.worker(client))

    # A first fill so the catalogue is ready before anyone searches. A failure here is
    # survivable, because the cached copy on disk is still usable.
    try:
        counts = await entries.refresh_all()
        log.info("catalogue: %s", ", ".join(f"{k}={v}" for k, v in counts.items()))
    except Exception:
        log.exception("initial catalogue load failed, continuing with the cached copy")

    try:
        await client.run_until_disconnected()
    finally:
        worker.cancel()
        await supabase.close()
        await external.close()
        log.info("stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
