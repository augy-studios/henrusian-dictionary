"""Durable interaction buttons, the storage half.

Every action button's custom_id is "hd:<token>", and the action plus its parameters live
in the callbacks table. Tokens are never expired, which is what lets a message from months
ago still page, save and navigate after any number of restarts. The Discord half, which
turns a click back into a handler call, is in ui.py.
"""

import json
import logging
import secrets
from typing import Awaitable, Callable, Optional

import db

log = logging.getLogger("buttons")

TOKEN_BYTES = 9  # 12 characters of urlsafe base64
PREFIX = "hd:"

# action name -> coroutine(ctx, params)
_actions: dict[str, Callable[..., Awaitable[None]]] = {}


def on_action(name: str):
    """Register a button handler. Handlers take (ctx: ui.Ctx, params: dict)."""

    def decorator(func):
        if name in _actions:
            raise RuntimeError(f"duplicate button action registered: {name}")
        _actions[name] = func
        return func

    return decorator


def handler_for(action: str):
    return _actions.get(action)


def registered_actions() -> list[str]:
    return sorted(_actions)


def mint(action: str, params: dict, user_id: int | None) -> str:
    """Reuse an identical row when one already exists, so the table does not grow
    without bound as the same view is re-rendered."""
    payload = json.dumps(params, sort_keys=True, separators=(",", ":"))
    existing = db.scalar(
        """
        SELECT token FROM callbacks
        WHERE action = ? AND params = ? AND IFNULL(user_id, -1) = IFNULL(?, -1)
        LIMIT 1
        """,
        (action, payload, user_id),
    )
    if existing:
        return existing

    token = secrets.token_urlsafe(TOKEN_BYTES)
    db.execute(
        "INSERT INTO callbacks (token, action, params, user_id) VALUES (?, ?, ?, ?)",
        (token, action, payload, user_id),
    )
    return token


def resolve(token: str) -> Optional[dict]:
    """Look a token up and record the use. Returns None for an unknown token."""
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

    return {"token": token, "action": row["action"], "params": params, "user_id": row["user_id"]}
