"""Text helpers, including the copy rules every outbound message goes through.

The dash sanitiser is the same one the Telegram bot uses. It is a safety net for copy that
slipped through review, not a licence to write dashes and let it clean up.
"""

import logging
import re

import discord

log = logging.getLogger("text")

_NUMERIC_RANGE = re.compile(r"(?<=\d)\s*[–—−―]\s*(?=\d)")
_SPACED_DASH = re.compile(r"\s+[–—―]\s+")
_TIGHT_DASH = re.compile(r"[–—―]")
_DOUBLE_PUNCT = re.compile(r",\s*,")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?])")


def sanitise(text: str) -> str:
    """Remove em dashes and en dashes, rephrasing so the result still reads properly."""
    if not text:
        return text

    original = text
    text = _NUMERIC_RANGE.sub(" to ", text)
    text = _SPACED_DASH.sub(", ", text)
    text = _TIGHT_DASH.sub(", ", text)
    text = text.replace("−", "-")
    text = _DOUBLE_PUNCT.sub(",", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)

    if text != original:
        log.debug("dash sanitiser rewrote outbound copy: %r", original[:120])
    return text


def md(value: str | None) -> str:
    """Escape database text so a stray asterisk in a definition cannot restyle the embed."""
    return discord.utils.escape_markdown(value or "")


def truncate(value: str, limit: int) -> str:
    value = (value or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def one_line(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def plural(count: int, singular: str, many: str | None = None) -> str:
    if count == 1:
        return f"1 {singular}"
    return f"{count} {many or singular + 's'}"


def format_date(value: str | None) -> str:
    """Render a Supabase timestamp the way the web app does, without the locale call."""
    if not value:
        return ""
    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
    if not match:
        return ""
    year, month, day = match.groups()
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    index = int(month) - 1
    if index < 0 or index > 11:
        return ""
    return f"{int(day)} {months[index]} {year}"
