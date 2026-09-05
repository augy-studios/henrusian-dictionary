"""Shared handler plumbing: command patterns, guards, and the canonical command list."""

import functools
import logging
import re

from telethon import events

import config
import db
from utils.rich import reply_rich

log = logging.getLogger("handlers")

# The single source of truth for the command list. /start renders this, and SETUP.md
# carries the same text for BotFather. No entry mentions the bot by name.
#
# Searching has no command of its own on purpose: any plain message in a direct chat is
# treated as a search across all three catalogues, and the buttons on the results narrow it
# to Words, Idioms or Names. That is one fewer thing for anyone to remember.
COMMANDS: list[tuple[str, str]] = [
    ("start", "What this bot does and everything it can do"),
    ("random", "Show a random entry"),
    ("wotd", "Word of the day"),
    ("favs", "Show your saved entries"),
    ("link", "Share favourites with a browser, or check the link"),
    ("unlink", "Remove the link"),
    ("code", "Use a code from the website, to link or to recover"),
    ("sub", "Get a word of the day every morning"),
    ("unsub", "Stop the daily word"),
    ("settings", "Timezone and delivery preferences"),
    ("stats", "Catalogue sizes and latest additions"),
    ("privacy", "What data is stored"),
    ("cancel", "Cancel the current step"),
]

# Not registered with BotFather, so they stay out of the menu.
OWNER_COMMANDS: list[tuple[str, str]] = [
    ("broadcast", "Send a message to every subscriber"),
    ("health", "Runtime status"),
]


# Multi-step flows. A handler registered here receives (event, pending_dict) when the
# user's next plain message arrives, and is responsible for clearing the pending state.
_pending: dict[str, object] = {}


def on_pending(kind: str):
    def decorator(func):
        _pending[kind] = func
        return func

    return decorator


def pending_handler(kind: str):
    return _pending.get(kind)


def cmd(*names: str):
    """A NewMessage pattern that tolerates the @username Telegram appends in groups."""
    joined = "|".join(re.escape(name) for name in names)
    return events.NewMessage(
        pattern=re.compile(rf"^/(?:{joined})(?:@[\w_]+)?(?:\s+([\s\S]*))?$", re.IGNORECASE),
        incoming=True,
    )


def args_of(event) -> str:
    match = getattr(event, "pattern_match", None)
    if not match:
        return ""
    try:
        return (match.group(1) or "").strip()
    except IndexError:
        return ""


def is_private(event) -> bool:
    return bool(getattr(event, "is_private", False))


def safe(func):
    """Log and apologise rather than letting one bad update kill the handler task."""

    @functools.wraps(func)
    async def wrapper(event, *args, **kwargs):
        try:
            return await func(event, *args, **kwargs)
        except Exception:
            log.exception("handler %s failed", func.__name__)
            try:
                # A callback carries data and is answered in place; a message gets a reply.
                if getattr(event, "data", None) is not None:
                    await event.answer("Something went wrong. Please try again.", alert=True)
                else:
                    await reply_rich(
                        event,
                        title="Something went wrong",
                        body="That did not work. Please try again in a moment.",
                    )
            except Exception:
                pass

    return wrapper


def private_only(func):
    """Account commands stay in private chats, since codes must not land in a group."""

    @functools.wraps(func)
    async def wrapper(event, *args, **kwargs):
        if not is_private(event):
            await reply_rich(
                event,
                title="Please continue in a private chat",
                body="This command deals with your account, so it only works in a direct "
                     "message. Open a chat with the bot and try again there.",
            )
            return
        return await func(event, *args, **kwargs)

    return wrapper


def owner_only(func):
    @functools.wraps(func)
    async def wrapper(event, *args, **kwargs):
        if not config.BOT_OWNER_ID or event.sender_id != config.BOT_OWNER_ID:
            return
        return await func(event, *args, **kwargs)

    return wrapper


def track(event):
    """Upsert the sender so later commands have a row to read.

    Keyed on sender_id, which is always present. event.sender is fetched lazily by
    Telethon and is frequently None, so the names are treated as a bonus.
    """
    user_id = getattr(event, "sender_id", None)
    if not user_id:
        return None
    sender = getattr(event, "sender", None)
    return db.touch_user_id(
        int(user_id),
        getattr(sender, "username", None),
        getattr(sender, "first_name", None),
    )


async def tracked_sender(event):
    sender = await event.get_sender()
    if sender is None:
        return None
    return db.touch_user(sender)


def command_list_html() -> str:
    return "\n".join(f"/{name} {desc}" for name, desc in COMMANDS)


def botfather_command_block() -> str:
    return "\n".join(f"{name} - {desc}" for name, desc in COMMANDS)
