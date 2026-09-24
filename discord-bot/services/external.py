"""Third party knowledge sources.

Every source here is free and keyless. Each call has a fallback and a cached last good
answer, because a daily delivery should not fail just because one small public API is
having a bad afternoon.

  Quotes         api.quotable.io   MIT, github.com/lukePeavey/quotable
  Quotes, backup zenquotes.io      free tier, no key
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
                                    headers={"User-Agent": "henrusian-discord-bot"})
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def cache_get(key: str) -> Optional[Any]:
    row = db.one("SELECT payload, expires_at FROM api_cache WHERE key = ?", (key,))
    if row is None or db.from_iso(row["expires_at"]) < db.now():
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


async def quote() -> Optional[dict]:
    """A random quote, or the last good one if both sources are down."""
    result = None

    data = await _get_json("https://api.quotable.io/random")
    if isinstance(data, dict) and data.get("content"):
        result = {"text": data["content"].strip(), "author": (data.get("author") or "Unknown").strip()}

    if result is None:
        data = await _get_json("https://zenquotes.io/api/random")
        if isinstance(data, list) and data and data[0].get("q"):
            result = {"text": data[0]["q"].strip(), "author": (data[0].get("a") or "Unknown").strip()}

    if result is None:
        return cache_get("quote:last")

    cache_put("quote:last", result, 86400)
    return result
