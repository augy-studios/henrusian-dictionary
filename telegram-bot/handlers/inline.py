"""Inline mode, so an entry can be quoted straight into another chat.

Inline results carry a plain link button and no callback buttons. A callback arriving
from an inline message has no chat of ours behind it, and a button that silently does
nothing is worse than no button at all.

Telethon's event.builder.article cannot carry a rich message, so the results are built as
raw InputBotInlineResult objects and answered with SetInlineBotResultsRequest. If Telegram
rejects that, the same entries go out as plain text articles through the builder.
"""

import logging

from telethon import Button, events, types
from telethon.tl import functions

from services import entries
from utils.rich import compose, escape_md
from utils.text import one_line, truncate

log = logging.getLogger("inline")

MAX_RESULTS = 20
CACHE_SECONDS = 60


def build_inline_entry(entry: dict) -> tuple[dict, list]:
    """The message an inline result sends: the word as a heading, its type, the definition."""
    word = entry.get("word") or "-"
    definition = entry.get("definition") or "No definition available."
    rich = compose(
        escape_md(word),
        f"*{escape_md(entries.SINGULAR[entry['tab']])}*\n\n{escape_md(definition)}",
    )
    buttons = [Button.url("Open in the app", entries.entry_url(entry["tab"], entry["id"]))]
    return rich, buttons


def register(client):
    @client.on(events.InlineQuery())
    async def on_inline(event):
        try:
            query = (event.text or "").strip()
            if entries.is_empty():
                await event.answer([], switch_pm="Open the bot to load the catalogue",
                                   switch_pm_param="start")
                return

            hits = entries.search(query, "all", "alpha-asc")[:MAX_RESULTS]
            if not hits:
                await event.answer([], switch_pm="No matches, open the bot to search",
                                   switch_pm_param="start")
                return

            built = [(entry, *build_inline_entry(entry)) for entry in hits]
            results = [
                types.InputBotInlineResult(
                    id=f"{entry['tab']}:{entry['id']}",
                    type="article",
                    title=entry.get("word") or "-",
                    description=truncate(one_line(entry.get("definition") or ""), 100),
                    send_message=types.InputBotInlineMessageRichMessage(
                        rich_message=types.InputRichMessageMarkdown(markdown=rich["markdown"]),
                        reply_markup=client.build_reply_markup(buttons),
                    ),
                )
                for entry, rich, buttons in built
            ]

            try:
                await client(functions.messages.SetInlineBotResultsRequest(
                    query_id=event.query.query_id, results=results, cache_time=CACHE_SECONDS,
                ))
            except Exception as err:
                log.warning("[inline] rich results failed, falling back: %s", err)
                await event.answer(
                    [
                        event.builder.article(
                            title=entry.get("word") or "-",
                            description=truncate(one_line(entry.get("definition") or ""), 100),
                            text=rich["fallback"],
                            link_preview=False,
                            buttons=buttons,
                        )
                        for entry, rich, buttons in built
                    ],
                    cache_time=CACHE_SECONDS,
                )
        except Exception:
            log.exception("inline query failed")
