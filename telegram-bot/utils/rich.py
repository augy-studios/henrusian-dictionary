"""The rich message layer.

The brief asked for sendRichMessage. Telethon has no method by that name, so this is
it: one wrapper every handler uses instead of calling send_message directly. It always
applies HTML parse mode, the house copy rules, message splitting, and a single retry
after a flood wait.
"""

import asyncio
import logging

from telethon.errors import FloodWaitError, MessageNotModifiedError

from utils.text import sanitise, split_for_telegram

log = logging.getLogger("rich")


def compose(title: str | None = None, body: str = "", footer: str | None = None) -> str:
    """Bold title, then body, then a muted footer. Any part may be omitted."""
    parts: list[str] = []
    if title:
        parts.append(f"<b>{title}</b>")
    if body:
        parts.append(body.strip())
    if footer:
        parts.append(f"<i>{footer}</i>")
    return sanitise("\n\n".join(parts))


async def _with_flood_retry(coro_factory):
    try:
        return await coro_factory()
    except FloodWaitError as exc:
        wait = min(int(exc.seconds) + 1, 300)
        log.warning("flood wait for %ss, retrying once", wait)
        await asyncio.sleep(wait)
        return await coro_factory()


async def send_rich_message(
    client,
    chat,
    *,
    title: str | None = None,
    body: str = "",
    footer: str | None = None,
    buttons=None,
    reply_to=None,
    link_preview: bool = False,
    silent: bool = False,
):
    """Send a formatted message. Long bodies split, and only the last part keeps the buttons."""
    text = compose(title, body, footer)
    chunks = split_for_telegram(text)
    sent = None

    for index, chunk in enumerate(chunks):
        is_last = index == len(chunks) - 1
        sent = await _with_flood_retry(
            lambda chunk=chunk, is_last=is_last: client.send_message(
                chat,
                chunk,
                parse_mode="html",
                buttons=buttons if is_last else None,
                reply_to=reply_to if index == 0 else None,
                link_preview=link_preview,
                silent=silent,
            )
        )
    return sent


async def reply_rich(event, **kwargs):
    """send_rich_message aimed at the chat an event came from."""
    return await send_rich_message(event.client, event.chat_id, **kwargs)


async def edit_rich(event, *, title=None, body="", footer=None, buttons=None, link_preview=False):
    """Edit the message a callback came from, so paging never posts a new message.

    A body that grew past a single message cannot be edited in place, so it falls back
    to sending instead of failing.
    """
    text = compose(title, body, footer)
    chunks = split_for_telegram(text)
    if len(chunks) > 1:
        return await send_rich_message(
            event.client, event.chat_id, title=title, body=body, footer=footer,
            buttons=buttons, link_preview=link_preview,
        )
    try:
        return await _with_flood_retry(
            lambda: event.edit(chunks[0], parse_mode="html", buttons=buttons, link_preview=link_preview)
        )
    except MessageNotModifiedError:
        return None
