"""Read only PostgREST client for the catalogue, mirroring main-site/api/entries.js.

The service role key bypasses row level security, so this module is the only place that
touches it, and it never appears in a log line. Nothing here writes to Supabase.
"""

import logging
from typing import Optional

import httpx

import config

log = logging.getLogger("supabase")

_client: Optional[httpx.AsyncClient] = None
last_error: Optional[str] = None

PAGE = 1000


class SupabaseError(RuntimeError):
    pass


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=f"{config.SUPABASE_URL}/rest/v1",
            timeout=httpx.Timeout(15.0),
            headers={
                "apikey": config.SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
            },
        )
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def fetch_all(table: str, *, columns: str, order: str) -> list[dict]:
    """Page through every row, because PostgREST caps a single response at 1000."""
    global last_error
    rows: list[dict] = []
    offset = 0
    while True:
        try:
            response = await client().get(
                f"/{table}",
                params={"select": columns, "order": order, "limit": PAGE, "offset": offset},
            )
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            raise SupabaseError("Could not reach the database.") from exc

        if response.status_code >= 400:
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            log.error("supabase GET %s failed: %s", table, last_error)
            raise SupabaseError("The database rejected the request.")

        page = response.json()
        rows.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE

    last_error = None
    return rows
