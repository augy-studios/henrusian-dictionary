"""Reading the catalogue: /random, /wotd, /stats, and the plain text search.

Searching deliberately has no command. Any message in a direct chat that is not a command
is a search across all three catalogues, and the filter buttons on the results narrow it
to Words, Idioms or Names.
"""

import logging

from telethon import events

import db
from handlers import common, views
from handlers.common import cmd, safe, track
from services import backup_codes, entries, external, scheduler
from services.buttons import on_action
from utils import ratelimit
from utils.reply import reply_rich
from utils.rich import compose, table
from utils.text import format_date

log = logging.getLogger("search")

LOADING = (
    "The catalogue is still loading. Please try again in a few seconds, and if this keeps "
    "happening the database may be unreachable."
)


async def run_search(event, query: str, tab: str = "all"):
    if entries.is_empty():
        await reply_rich(event, compose("Not ready yet", LOADING))
        return

    if not ratelimit.allow(event.sender_id, "search", 30, 60):
        wait = ratelimit.retry_after(event.sender_id, "search", 60)
        await reply_rich(event, compose(
            "Slow down a moment",
            f"That is a lot of searches at once. Please try again in {wait} seconds.",
        ))
        return

    pack = views.results_view(event.chat_id, event.sender_id, q=query, tab=tab, sort="alpha-asc", page=0)
    await views.send_view(event, pack)


def build_stats() -> dict:
    """The /stats screen: one table row per catalogue, then the total."""
    counts = entries.counts()
    rows = [[entries.LABELS[tab], counts[tab]] for tab in entries.TAB_ORDER]
    rows.append(["Total", sum(counts.values())])

    newest = ""
    for tab in entries.TAB_ORDER:
        for entry in entries.all_entries(tab):
            stamp = entry.get("created_at") or ""
            if stamp > newest:
                newest = stamp

    age = entries.cache_age_seconds()
    footer_bits = []
    if newest:
        footer_bits.append(f"Newest entry added {format_date(newest)}")
    if age is not None:
        footer_bits.append(f"catalogue refreshed {age // 60} minutes ago")

    return compose("Catalogue", table(["Entries"], rows),
                   ", ".join(footer_bits) if footer_bits else None)


def register(client):
    @client.on(cmd("random", "roll"))
    @safe
    async def on_random(event):
        track(event)
        entry = entries.random_entry()
        if entry is None:
            await reply_rich(event, compose("Not ready yet", LOADING))
            return
        pack = await views.entry_view(
            event.chat_id, event.sender_id,
            tab=entry["tab"], entry_id=entry["id"], back={"v": "random", "tab": "all"},
        )
        await views.send_view(event, pack)

    @client.on(cmd("wotd", "daily"))
    @safe
    async def on_wotd(event):
        track(event)
        entry = entries.word_of_the_day()
        if entry is None:
            await reply_rich(event, compose("Not ready yet", LOADING))
            return
        pack = await views.entry_view(
            event.chat_id, event.sender_id,
            tab="dict", entry_id=entry["id"], back={"v": "home"},
            heading_prefix="Word of the day",
        )
        await views.send_view(event, pack)

    @client.on(cmd("stats"))
    @safe
    async def on_stats(event):
        track(event)
        rich = build_stats()
        await reply_rich(event, rich)

    # Any plain message in a private chat is either an answer to a pending step or a search.
    @client.on(events.NewMessage(
        incoming=True,
        func=lambda e: bool(e.is_private and (e.raw_text or "").strip()
                            and not (e.raw_text or "").strip().startswith("/")),
    ))
    @safe
    async def on_plain_text(event):
        track(event)
        pending = db.get_pending(event.sender_id)
        if pending:
            handler = common.pending_handler(pending.get("kind", ""))
            if handler is not None:
                await handler(event, pending)
                return
            db.set_pending(event.sender_id, None)

        await run_search(event, event.raw_text.strip())


# -- callbacks -------------------------------------------------------------


@on_action("results:page")
async def results_page(event, params):
    pack = views.results_view(
        event.chat_id, event.sender_id,
        q=params.get("q", ""), tab=params.get("tab", "all"),
        sort=params.get("sort", "alpha-asc"), page=int(params.get("p", 0)),
    )
    await views.edit_view(event, pack)
    await event.answer()


@on_action("results:tab")
async def results_tab(event, params):
    pack = views.results_view(
        event.chat_id, event.sender_id,
        q=params.get("q", ""), tab=params.get("tab", "all"),
        sort=params.get("sort", "alpha-asc"), page=0,
    )
    await views.edit_view(event, pack)
    await event.answer()


@on_action("results:sort")
async def results_sort(event, params):
    nxt = entries.next_sort(params.get("sort", "alpha-asc"))
    pack = views.results_view(
        event.chat_id, event.sender_id,
        q=params.get("q", ""), tab=params.get("tab", "all"), sort=nxt, page=0,
    )
    await views.edit_view(event, pack)
    await event.answer(f"Sorted {entries.SORT_LABELS[nxt]}")


@on_action("entry:open")
async def entry_open(event, params):
    pack = await views.entry_view(
        event.chat_id, event.sender_id,
        tab=params.get("tab", "dict"), entry_id=str(params.get("id")),
        back=params.get("back") or {"v": "home"},
    )
    await views.edit_view(event, pack)
    await event.answer()


@on_action("random:roll")
async def random_roll(event, params):
    entry = entries.random_entry(params.get("tab", "all"))
    if entry is None:
        await event.answer("The catalogue is still loading.", alert=True)
        return
    pack = await views.entry_view(
        event.chat_id, event.sender_id,
        tab=entry["tab"], entry_id=entry["id"],
        back={"v": "random", "tab": params.get("tab", "all")},
    )
    await views.edit_view(event, pack)
    await event.answer()


@on_action("wotd:show")
async def wotd_show(event, params):
    entry = entries.word_of_the_day()
    if entry is None:
        await event.answer("The catalogue is still loading.", alert=True)
        return
    pack = await views.entry_view(
        event.chat_id, event.sender_id, tab="dict", entry_id=entry["id"], back={"v": "home"},
        heading_prefix="Word of the day",
    )
    await views.edit_view(event, pack)
    await event.answer()


# -- jobs ------------------------------------------------------------------


@scheduler.job("refresh_entries")
async def refresh_entries(client, payload):
    counts = await entries.refresh_all()
    log.info("catalogue refreshed: %s", ", ".join(f"{k}={v}" for k, v in counts.items()))


@scheduler.job("prune_cache")
async def prune_cache(client, payload):
    removed = external.prune_cache()
    if removed:
        log.info("pruned %s expired api cache rows", removed)

    stale = backup_codes.expire_stale()
    if stale:
        log.info("expired %s recovery code requests that were never approved", stale)
