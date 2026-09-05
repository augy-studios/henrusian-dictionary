"""Thin PostgREST client, mirroring what main-site/api/entries.js does server side.

The service role key bypasses row level security, so this module is the only place that
touches it, and it never appears in a log line.
"""

import logging
from typing import Any, Optional

import httpx

import config

log = logging.getLogger("supabase")

_client: Optional[httpx.AsyncClient] = None
last_error: Optional[str] = None

PAGE = 1000


class SupabaseError(RuntimeError):
    pass


def _headers(prefer: str | None = None) -> dict[str, str]:
    headers = {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=f"{config.SUPABASE_URL}/rest/v1",
            timeout=httpx.Timeout(15.0),
        )
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _request(method: str, path: str, **kwargs) -> Any:
    global last_error
    try:
        response = await client().request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        last_error = f"{type(exc).__name__}: {exc}"
        raise SupabaseError("Could not reach the database.") from exc

    if response.status_code >= 400:
        last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        log.error("supabase %s %s failed: %s", method, path, last_error)
        raise SupabaseError("The database rejected the request.")

    last_error = None
    if not response.content:
        return []
    try:
        return response.json()
    except ValueError:
        return []


async def select(table: str, *, columns: str = "*", params: dict | None = None) -> list[dict]:
    query = {"select": columns}
    query.update(params or {})
    return await _request("GET", f"/{table}", params=query, headers=_headers())


async def select_one(table: str, *, columns: str = "*", params: dict | None = None) -> Optional[dict]:
    query = dict(params or {})
    query["limit"] = 1
    rows = await select(table, columns=columns, params=query)
    return rows[0] if rows else None


async def insert(table: str, rows: list[dict] | dict, *, upsert: bool = False, returning: bool = True) -> list[dict]:
    prefer = ["return=representation" if returning else "return=minimal"]
    if upsert:
        prefer.append("resolution=merge-duplicates")
    return await _request(
        "POST", f"/{table}", json=rows, headers=_headers(",".join(prefer))
    )


async def update(table: str, filters: dict, data: dict, *, returning: bool = True) -> list[dict]:
    prefer = "return=representation" if returning else "return=minimal"
    return await _request(
        "PATCH", f"/{table}", params=filters, json=data, headers=_headers(prefer)
    )


async def delete(table: str, filters: dict) -> list[dict]:
    return await _request(
        "DELETE", f"/{table}", params=filters, headers=_headers("return=minimal")
    )


async def fetch_all(table: str, *, columns: str, order: str) -> list[dict]:
    """Page through every row, because PostgREST caps a single response at 1000."""
    rows: list[dict] = []
    offset = 0
    while True:
        page = await _request(
            "GET",
            f"/{table}",
            params={"select": columns, "order": order, "limit": PAGE, "offset": offset},
            headers=_headers(),
        )
        rows.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE
    return rows


def eq(value) -> str:
    """PostgREST filter shorthand, so callers read as params={'id': eq(5)}."""
    return f"eq.{value}"
