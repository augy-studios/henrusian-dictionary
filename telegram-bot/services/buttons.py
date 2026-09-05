"""Durable interaction buttons.

Telegram caps callback data at 64 bytes, so any scheme that packs state into the button
itself breaks as soon as the state grows. Instead every button carries a short opaque
token, and the action plus its parameters live in SQLite. Tokens are never expired,
which is what lets a message from months ago still page, star and navigate after any
number of restarts.
"""

import json
import logging
import secrets
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from telethon import Button

import db

log = logging.getLogger("buttons")

TOKEN_BYTES = 9  # 12 characters of urlsafe base64, comfortably inside the 64 byte cap

# action name -> coroutine(event, params)
_actions: dict[str, Callable[..., Awaitable[None]]] = {}


def on_action(name: str):
    """Register a callback handler. Handlers take (event, params: dict)."""

    def decorator(func):
        if name in _actions:
            raise RuntimeError(f"duplicate callback action registered: {name}")
        _actions[name] = func
        return func

    return decorator


def handler_for(action: str):
    return _actions.get(action)


def registered_actions() -> list[str]:
    return sorted(_actions)


@dataclass
class Btn:
    """A button before it has a token. Either an action button or a plain URL button."""

    label: str
    action: Optional[str] = None
    params: Optional[dict] = None
    url: Optional[str] = None


def act(label: str, action: str, params: dict | None = None) -> Btn:
    return Btn(label=label, action=action, params=params or {})


def link(label: str, url: str) -> Btn:
    return Btn(label=label, url=url)


def _mint(action: str, params: dict, chat_id: int | None, user_id: int | None) -> str:
    """Reuse an identical row when one already exists, so the table does not grow
    without bound as the same view is re-rendered."""
    payload = json.dumps(params, sort_keys=True, separators=(",", ":"))
    existing = db.scalar(
        """
        SELECT token FROM callbacks
        WHERE action = ? AND params = ?
          AND IFNULL(chat_id, -1) = IFNULL(?, -1)
          AND IFNULL(user_id, -1) = IFNULL(?, -1)
        LIMIT 1
        """,
        (action, payload, chat_id, user_id),
    )
    if existing:
        return existing

    token = secrets.token_urlsafe(TOKEN_BYTES)
    db.execute(
        "INSERT INTO callbacks (token, action, params, chat_id, user_id) VALUES (?, ?, ?, ?, ?)",
        (token, action, payload, chat_id, user_id),
    )
    return token


def build(rows: list[list[Btn]], *, chat_id: int | None = None, user_id: int | None = None):
    """Turn rows of Btn into Telethon buttons, persisting every action token."""
    out = []
    for row in rows:
        built = []
        for item in row:
            if item.url:
                built.append(Button.url(item.label, item.url))
                continue
            token = _mint(item.action, item.params or {}, chat_id, user_id)
            built.append(Button.inline(item.label, token.encode()))
        if built:
            out.append(built)
    return out or None


def resolve(token: bytes | str) -> Optional[dict]:
    """Look a token up and record the use. Returns None for an unknown token."""
    if isinstance(token, bytes):
        try:
            token = token.decode()
        except UnicodeDecodeError:
            return None

    row = db.one("SELECT * FROM callbacks WHERE token = ?", (token,))
    if row is None:
        return None

    db.execute(
        "UPDATE callbacks SET use_count = use_count + 1, last_used_at = datetime('now') "
        "WHERE token = ?",
        (token,),
    )
    try:
        params = json.loads(row["params"])
    except json.JSONDecodeError:
        params = {}

    return {
        "token": token,
        "action": row["action"],
        "params": params,
        "chat_id": row["chat_id"],
        "user_id": row["user_id"],
    }
