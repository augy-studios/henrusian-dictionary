"""Third party knowledge sources.

Every source here is free, keyless, and open source. Each call is cached in SQLite and
has a fallback, because a bot command should not fail just because one small public API
is having a bad afternoon.

  Quotes         api.quotable.io          MIT, github.com/lukePeavey/quotable
  Quotes, backup zenquotes.io             free tier, no key
  Facts          uselessfacts.jsph.pl     open source, github.com/Sv443/useless-facts
  Facts, backup  numbersapi.com           free, no key
  Glosses        api.dictionaryapi.dev    open source, github.com/meetDeveloper/freeDictionaryAPI
"""

import json
import logging
from datetime import timedelta
from typing import Any, Optional

import httpx

import db

log = logging.getLogger("external")

TIMEOUT = httpx.Timeout(5.0)
_client: Optional[httpx.AsyncClient] = None


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True,
                                    headers={"User-Agent": "henrusian-bot"})
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def cache_get(key: str) -> Optional[Any]:
    row = db.one("SELECT payload, expires_at FROM api_cache WHERE key = ?", (key,))
    if row is None:
        return None
    if db.from_iso(row["expires_at"]) < db.now():
        return None
    try:
        return json.loads(row["payload"])
    except json.JSONDecodeError:
        return None


def cache_put(key: str, value: Any, ttl_seconds: int) -> None:
    db.execute(
        """
        INSERT INTO api_cache (key, payload, expires_at) VALUES (?, ?, ?)
        ON CONFLICT (key) DO UPDATE SET payload = excluded.payload, expires_at = excluded.expires_at
        """,
        (key, json.dumps(value), db.to_iso(db.now() + timedelta(seconds=ttl_seconds))),
    )


def prune_cache() -> int:
    cursor = db.execute("DELETE FROM api_cache WHERE expires_at < ?", (db.to_iso(db.now()),))
    return cursor.rowcount or 0


async def _get_json(url: str) -> Optional[Any]:
    try:
        response = await client().get(url)
        if response.status_code >= 400:
            log.warning("%s returned HTTP %s", url, response.status_code)
            return None
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("%s failed: %s", url, exc)
        return None


# -- quotes ----------------------------------------------------------------


async def quote() -> Optional[dict]:
    """A random quote. Cached briefly, so a burst of taps does not hammer the source."""
    data = await _get_json("https://api.quotable.io/random")
    if isinstance(data, dict) and data.get("content"):
        return {
            "text": data["content"].strip(),
            "author": (data.get("author") or "Unknown").strip(),
            "source": "quotable.io",
        }

    data = await _get_json("https://zenquotes.io/api/random")
    if isinstance(data, list) and data and data[0].get("q"):
        return {
            "text": data[0]["q"].strip(),
            "author": (data[0].get("a") or "Unknown").strip(),
            "source": "zenquotes.io",
        }

    cached = cache_get("quote:last")
    return cached


async def quote_cached_or_fresh() -> Optional[dict]:
    result = await quote()
    if result:
        cache_put("quote:last", result, 86400)
    return result


# -- facts -----------------------------------------------------------------


async def fact() -> Optional[dict]:
    data = await _get_json("https://uselessfacts.jsph.pl/api/v2/facts/random?language=en")
    if isinstance(data, dict) and data.get("text"):
        return {"text": data["text"].strip(), "source": "uselessfacts.jsph.pl"}

    data = await _get_json("http://numbersapi.com/random/trivia?json")
    if isinstance(data, dict) and data.get("text"):
        return {"text": data["text"].strip(), "source": "numbersapi.com"}

    return cache_get("fact:last")


async def fact_cached_or_fresh() -> Optional[dict]:
    result = await fact()
    if result:
        cache_put("fact:last", result, 86400)
    return result


# -- English glosses -------------------------------------------------------


async def gloss(word: str) -> Optional[str]:
    """One short English definition, used to enrich an entry. Fails quietly, because this
    is a nicety and never the point of the message."""
    key = f"gloss:{word.lower()}"
    cached = cache_get(key)
    if cached is not None:
        return cached or None

    data = await _get_json(f"https://api.dictionaryapi.dev/api/v2/entries/en/{word.lower()}")
    text = None
    if isinstance(data, list) and data:
        meanings = data[0].get("meanings") or []
        if meanings:
            definitions = meanings[0].get("definitions") or []
            if definitions:
                text = (definitions[0].get("definition") or "").strip() or None

    cache_put(key, text or "", 86400 * 7)
    return text
