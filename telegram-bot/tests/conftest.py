"""Shared test fixtures.

Every test runs entirely offline. Telegram is replaced by small fakes, and Supabase by an
in-memory PostgREST stub that understands the handful of filters this project uses.
"""

import asyncio
import itertools
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Set before config is imported anywhere, since it validates on import.
os.environ.setdefault("TELEGRAM_API_ID", "12345")
os.environ.setdefault("TELEGRAM_API_HASH", "test-hash")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "1:test-token")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("DONATION_URL", "https://donate.example/coffee")
os.environ.setdefault("WEB_APP_URL", "https://henrusian.example")
os.environ.setdefault("BOT_OWNER_ID", "999")
os.environ.setdefault("BACKUP_CODE_PEPPER", "test-pepper")


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    """A fresh SQLite file per test, with the real schema applied."""
    import config
    import db

    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "bot.db")
    db._conn = None
    db.connect()
    db.apply_schema()
    yield db
    if db._conn is not None:
        db._conn.close()
        db._conn = None


@pytest.fixture
def run():
    """Run a coroutine to completion. Simpler than pulling in pytest-asyncio."""

    def _run(coro):
        return asyncio.run(coro)

    return _run


# -- PostgREST stub --------------------------------------------------------


class Postgrest:
    """Enough of PostgREST to exercise the real query strings the code builds."""

    UNIQUE = {
        "henrusian15_sync_favourites": ("telegram_user_id", "tab", "entry_id"),
        "henrusian15_sync_backup_codes": ("code_hash",),
    }
    NULLABLE = (
        "used_at", "revoked_at", "resolved_at", "consumed_at", "notified_at",
        "used_by", "used_by_telegram_id", "last_seen_at", "device_label",
        "telegram_username", "device_id", "by_telegram_user_id",
    )

    def __init__(self):
        self.store: dict[str, list[dict]] = {}
        self.ids = itertools.count(1)
        self.calls: list[tuple[str, str]] = []

    # -- helpers used by tests
    def rows(self, table):
        return self.store.setdefault(table, [])

    def seed(self, table, rows):
        for row in rows:
            row = dict(row)
            row.setdefault("id", next(self.ids))
            row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            for field in self.NULLABLE:
                row.setdefault(field, None)
            self.rows(table).append(row)
        return self.rows(table)

    def live(self, table):
        return [r for r in self.rows(table) if r.get("revoked_at") is None]

    # -- filter matching
    def _matches(self, row, params):
        for key, raw in params.items():
            if key in ("select", "order", "limit", "offset"):
                continue
            value = row.get(key)
            if raw == "is.null":
                if value is not None:
                    return False
            elif raw == "not.is.null":
                if value is None:
                    return False
            elif raw.startswith("eq."):
                wanted = raw[3:]
                if wanted in ("true", "false"):
                    if bool(value) is not (wanted == "true"):
                        return False
                elif str(value) != wanted:
                    return False
            elif raw.startswith("gt."):
                if not (value or "") > raw[3:]:
                    return False
            elif raw.startswith("gte."):
                if not (value or "") >= raw[4:]:
                    return False
            elif raw.startswith("lt."):
                if not (value or "") < raw[3:]:
                    return False
            else:
                raise AssertionError(f"stub does not understand the filter {key}={raw}")
        return True

    def handle(self, request):
        import httpx

        table = request.url.path.split("/rest/v1/")[-1].strip("/")
        params = dict(request.url.params)
        self.calls.append((request.method, table))
        rows = self.rows(table)

        if request.method == "GET":
            hits = [r for r in rows if self._matches(r, params)]
            order = params.get("order")
            if order:
                field, _, direction = order.partition(".")
                hits.sort(key=lambda r: (r.get(field) is None, r.get(field)),
                          reverse=direction.startswith("desc"))
            if "limit" in params:
                start = int(params.get("offset", 0))
                hits = hits[start : start + int(params["limit"])]
            return httpx.Response(200, json=hits)

        if request.method == "POST":
            payload = json.loads(request.content or b"{}")
            payload = payload if isinstance(payload, list) else [payload]
            merging = "merge-duplicates" in (request.headers.get("prefer") or "")
            out = []
            key = self.UNIQUE.get(table)
            for item in payload:
                item = {**item}
                item.setdefault("id", next(self.ids))
                item.setdefault("created_at", datetime.now(timezone.utc).isoformat())
                for field in self.NULLABLE:
                    item.setdefault(field, None)

                duplicate = None
                if key:
                    duplicate = next(
                        (r for r in rows if all(str(r.get(k)) == str(item.get(k)) for k in key)),
                        None,
                    )
                if duplicate is not None:
                    if not merging:
                        return httpx.Response(409, json={"message": "duplicate key"})
                    out.append(duplicate)
                    continue
                rows.append(item)
                out.append(item)
            return httpx.Response(201, json=out)

        if request.method == "PATCH":
            data = json.loads(request.content or b"{}")
            hits = [r for r in rows if self._matches(r, params)]
            for row in hits:
                row.update(data)
            return httpx.Response(200, json=hits)

        if request.method == "DELETE":
            hits = [r for r in rows if self._matches(r, params)]
            self.store[table] = [r for r in rows if r not in hits]
            return httpx.Response(200, json=[])

        return httpx.Response(405, json={})


@pytest.fixture
def rest(monkeypatch):
    """Point the Supabase client at the stub."""
    import httpx

    import config
    from services import supabase

    stub = Postgrest()
    monkeypatch.setattr(
        supabase,
        "_client",
        httpx.AsyncClient(
            transport=httpx.MockTransport(stub.handle),
            base_url=f"{config.SUPABASE_URL}/rest/v1",
        ),
    )
    return stub


# -- catalogue -------------------------------------------------------------

WORDS = [
    ("henlo", "a greeting, informal"),
    ("wataa", "water"),
    ("aaa", "the first thing"),
    ("mimi", "small"),
    ("koko", "here"),
    ("lala", "there"),
    ("popo", "a friend"),
    ("rara", "rare"),
    ("susu", "milk"),
    ("zzz", "sleep"),
]


@pytest.fixture
def catalogue():
    """Fill the in-memory catalogue without touching the network."""
    from services import entries

    entries._cache["dict"] = [
        {
            "id": str(index),
            "word": word,
            "definition": definition,
            "created_at": f"2026-0{(index % 9) + 1}-01T00:00:00+00:00",
        }
        for index, (word, definition) in enumerate(WORDS)
    ]
    entries._cache["idioms"] = [
        {"id": "100", "word": "henlo wataa", "definition": "to greet warmly",
         "created_at": "2026-01-01T00:00:00+00:00"}
    ]
    entries._cache["names"] = [
        {"id": "200", "word": "Henrus", "definition": "the founder",
         "created_at": "2026-01-01T00:00:00+00:00"}
    ]
    yield entries
    entries._cache = {tab: [] for tab in entries.TABLES}


# -- Telegram fakes --------------------------------------------------------


class FakeClient:
    """Records what would have been sent."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send_message(self, chat, text, **kwargs):
        self.sent.append({"chat": chat, "text": text, "buttons": kwargs.get("buttons"), **kwargs})
        return type("Message", (), {"id": len(self.sent)})()

    async def send_file(self, chat, file, **kwargs):
        self.sent.append({"chat": chat, "file": file, **kwargs})
        return type("Message", (), {"id": len(self.sent)})()

    def on(self, event):  # so handler modules can register against it
        def decorator(func):
            self.handlers = getattr(self, "handlers", [])
            self.handlers.append((event, func))
            return func

        return decorator


class FakeSender:
    def __init__(self, user_id, username="augy", first_name="Augy"):
        self.id = user_id
        self.username = username
        self.first_name = first_name


class FakeEvent:
    """Stands in for both a NewMessage and a CallbackQuery."""

    def __init__(self, sender_id=4242, text="", data=None, client=None, is_private=True,
                 chat_id=None):
        self.sender_id = sender_id
        self.chat_id = chat_id if chat_id is not None else sender_id
        self.raw_text = text
        self.message_id = 77
        self.data = data.encode() if isinstance(data, str) else data
        self.client = client or FakeClient()
        self.is_private = is_private
        self.answered = None
        self.alerted = False
        self.edited = None
        self.edited_buttons = None
        self.pattern_match = None

    async def answer(self, text=None, alert=False):
        self.answered = text
        self.alerted = alert

    async def edit(self, text, **kwargs):
        self.edited = text
        self.edited_buttons = kwargs.get("buttons")
        return self

    async def get_sender(self):
        return FakeSender(self.sender_id)

    # Convenience for assertions
    @property
    def sent(self):
        return self.client.sent

    def last_text(self):
        return self.client.sent[-1]["text"] if self.client.sent else None


@pytest.fixture
def client():
    return FakeClient()


@pytest.fixture
def event(client):
    def _event(**kwargs):
        kwargs.setdefault("client", client)
        return FakeEvent(**kwargs)

    return _event


@pytest.fixture
def known_user(database):
    """A tracked Telegram user, which the pending flows and favourites need."""
    import db

    db.touch_user_id(4242, "augy", "Augy")
    return 4242
