"""Inline mode, so an entry can be quoted straight into another chat.

Inline results carry a plain link button and no callback buttons. A callback arriving
from an inline message has no chat of ours behind it, and a button that silently does
nothing is worse than no button at all.
"""

import logging

from telethon import Button, events

from services import entries
from utils.text import esc, one_line, truncate

log = logging.getLogger("inline")

MAX_RESULTS = 20


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

            results = []
            for entry in hits:
                word = entry.get("word") or "-"
                definition = entry.get("definition") or "No definition available."
                results.append(
                    event.builder.article(
                        title=word,
                        description=truncate(one_line(definition), 100),
                        text=(
                            f"<b>{esc(word)}</b>  <i>{esc(entries.SINGULAR[entry['tab']])}</i>\n\n"
                            f"{esc(definition)}"
                        ),
                        parse_mode="html",
                        link_preview=False,
                        buttons=[
                            Button.url("Open in the app",
                                       entries.entry_url(entry["tab"], entry["id"]))
                        ],
                    )
                )
            await event.answer(results, cache_time=60)
        except Exception:
            log.exception("inline query failed")
