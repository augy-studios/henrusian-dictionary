"""The catalogue: fetching, caching, searching, and the word of the day.

Search behaviour and the word of the day deliberately match the Telegram bot and
main-site/script.js, so every surface agrees about what a query returns and which word
is today's.
"""

import hashlib
import json
import logging
import secrets
from datetime import date
from typing import Optional

import config
import db
from services import supabase

log = logging.getLogger("entries")

TABLES = {
    "dict": "henrusian15_dict",
    "idioms": "henrusian15_idioms",
    "names": "henrusian15_names",
}

LABELS = {"dict": "Words", "idioms": "Idioms", "names": "Names"}
SINGULAR = {"dict": "Word", "idioms": "Idiom", "names": "Name"}
TAB_ORDER = ["dict", "idioms", "names"]

# Placeholder row the web app also hides, see main-site/script.js
SKIP_WORDS = {"zz resume right here"}

SORT_CYCLE = ["alpha-asc", "alpha-desc", "date-desc", "date-asc"]
SORT_LABELS = {
    "alpha-asc": "A to Z",
    "alpha-desc": "Z to A",
    "date-desc": "Newest",
    "date-asc": "Oldest",
}

_cache: dict[str, list[dict]] = {tab: [] for tab in TABLES}


def load_from_disk() -> None:
    """Warm the in-memory cache from SQLite at boot, so the first search works before
    Supabase has been reached."""
    for row in db.query("SELECT tab, payload FROM entry_cache"):
        tab = row["tab"]
        if tab not in _cache:
            continue
        try:
            _cache[tab] = json.loads(row["payload"])
        except json.JSONDecodeError:
            _cache[tab] = []
    total = sum(len(v) for v in _cache.values())
    if total:
        log.info("loaded %s cached entries from disk", total)


async def refresh(tab: str) -> int:
    rows = await supabase.fetch_all(
        TABLES[tab], columns="id,word,definition,created_at", order="word.asc"
    )
    if tab == "dict":
        rows = [r for r in rows if (r.get("word") or "").strip().lower() not in SKIP_WORDS]

    for row in rows:
        row["id"] = str(row.get("id"))

    _cache[tab] = rows
    db.execute(
        """
        INSERT INTO entry_cache (tab, payload, count, fetched_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT (tab) DO UPDATE SET
            payload = excluded.payload, count = excluded.count, fetched_at = datetime('now')
        """,
        (tab, json.dumps(rows, separators=(",", ":")), len(rows)),
    )
    return len(rows)


async def refresh_all() -> dict[str, int]:
    counts = {}
    for tab in TABLES:
        try:
            counts[tab] = await refresh(tab)
        except supabase.SupabaseError:
            log.warning("could not refresh %s, keeping the cached copy", tab)
            counts[tab] = len(_cache[tab])
    return counts


def cache_age_seconds() -> Optional[int]:
    stamp = db.scalar("SELECT MIN(fetched_at) FROM entry_cache")
    if not stamp:
        return None
    return int((db.now() - db.from_iso(stamp)).total_seconds())


def all_entries(tab: str) -> list[dict]:
    return _cache.get(tab, [])


def counts() -> dict[str, int]:
    return {tab: len(_cache.get(tab, [])) for tab in TAB_ORDER}


def is_empty() -> bool:
    return not any(_cache.values())


def find(tab: str, entry_id: str) -> Optional[dict]:
    for entry in _cache.get(tab, []):
        if entry["id"] == str(entry_id):
            return entry
    return None


def _sort_key(entries: list[dict], mode: str) -> list[dict]:
    if mode in ("date-asc", "date-desc"):
        return sorted(
            entries,
            key=lambda e: e.get("created_at") or "",
            reverse=(mode == "date-desc"),
        )
    return sorted(
        entries,
        key=lambda e: (e.get("word") or "").lower(),
        reverse=(mode == "alpha-desc"),
    )


def search(query: str, tab: str = "all", sort: str = "alpha-asc") -> list[dict]:
    """Substring match over word and definition, exactly as the web app filters."""
    tabs = TAB_ORDER if tab == "all" else [tab]
    needle = (query or "").strip().lower()

    hits: list[dict] = []
    for name in tabs:
        for entry in _cache.get(name, []):
            if needle and needle not in (entry.get("word") or "").lower() \
                    and needle not in (entry.get("definition") or "").lower():
                continue
            hits.append({**entry, "tab": name})

    # An exact word match should never be buried under a definition match.
    if needle:
        exact = [e for e in hits if (e.get("word") or "").lower() == needle]
        starts = [e for e in hits if (e.get("word") or "").lower().startswith(needle) and e not in exact]
        rest = [e for e in hits if e not in exact and e not in starts]
        return exact + _sort_key(starts, sort) + _sort_key(rest, sort)

    return _sort_key(hits, sort)


def next_sort(mode: str) -> str:
    try:
        index = SORT_CYCLE.index(mode)
    except ValueError:
        index = 0
    return SORT_CYCLE[(index + 1) % len(SORT_CYCLE)]


def random_entry(tab: str = "all") -> Optional[dict]:
    pool = search("", tab)
    if not pool:
        return None
    return pool[secrets.randbelow(len(pool))]


def word_of_the_day(on: Optional[date] = None) -> Optional[dict]:
    """Deterministic per calendar date, and the same digest the Telegram bot uses, so
    both bots pick the same word on the same day."""
    pool = sorted(_cache.get("dict", []), key=lambda e: e["id"])
    if not pool:
        return None
    day = (on or date.today()).isoformat()
    digest = hashlib.sha256(f"henrusian-wotd:{day}".encode()).hexdigest()
    return {**pool[int(digest, 16) % len(pool)], "tab": "dict"}


def entry_url(tab: str, entry_id: str) -> str:
    return f"{config.WEB_APP_URL}/?tab={tab}&entry={entry_id}"
