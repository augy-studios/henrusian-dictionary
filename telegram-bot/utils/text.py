"""Text helpers, including the copy rules every outbound message goes through.

The dash sanitiser is a safety net for copy that slipped through review, not a licence
to write dashes and let it clean up. Anything it changes is logged at debug level so
the source string can be fixed properly.
"""

import html
import logging
import re

log = logging.getLogger("text")

EM_DASH = "—"
EN_DASH = "–"
MINUS_SIGN = "−"
HORIZONTAL_BAR = "―"

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
    text = text.replace(MINUS_SIGN, "-")
    text = _DOUBLE_PUNCT.sub(",", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)

    if text != original:
        log.debug("dash sanitiser rewrote outbound copy: %r", original[:120])
    return text


def esc(value) -> str:
    """HTML escape anything headed for a message body."""
    return html.escape(str(value if value is not None else ""), quote=False)


def truncate(value: str, limit: int) -> str:
    value = (value or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def one_line(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def split_for_telegram(text: str, limit: int = 4000) -> list[str]:
    """Split on paragraph boundaries, then line boundaries, then hard characters."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 2:
            cut = window.rfind("\n")
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


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
    months = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    index = int(month) - 1
    if index < 0 or index > 11:
        return ""
    return f"{int(day)} {months[index]} {year}"
