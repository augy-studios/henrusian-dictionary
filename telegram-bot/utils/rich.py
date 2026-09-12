"""Rich Markdown formatting, and the message payload every view produces.

Telegram's Rich Messages take GitHub-flavoured Markdown: `# Heading`, `**bold**`,
`*italic*`, bullet lists and pipe tables. A view builds that markdown once, and compose()
pairs it with a plain text fallback derived from the same markdown, which is what the
request's mandatory message field carries and what an old client shows:

    rich = {"markdown": "...", "fallback": "..."}

Anything dynamic (names, user input, catalogue text) goes through escape_md, and table
cells through escape_cell. Markup the code writes itself is left alone.

The house copy rules still apply: the dash sanitiser runs over every payload.
"""

import re

from utils.text import sanitise

_MD_SPECIAL = re.compile(r"([\\*_~`|\[\]#>=])")


def escape_md(text) -> str:
    """Escape user/data text for Telegram's Rich Markdown dialect."""
    return _MD_SPECIAL.sub(r"\\\1", str(text if text is not None else ""))


def escape_cell(text) -> str:
    """Escape for a GFM table cell; also flattens newlines so the row stays intact."""
    return escape_md(str(text if text is not None else "").replace("\n", " "))


def table(headers: list[str], rows: list[list]) -> str:
    """A pipe table whose first column is a row label, so the header starts blank.

    Headers are authored text and stay as written. Every cell in rows is escaped.
    """
    lines = ["| " + " | ".join(["", *headers]) + " |",
             "| " + " | ".join(["---"] * (len(headers) + 1)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(escape_cell(v) for v in row) + " |")
    return "\n".join(lines)


def bullets(items: list[str]) -> str:
    """A bullet list. Items are markdown, already escaped where they need to be."""
    return "\n".join(f"- {item}" for item in items)


def compose(title: str | None = None, body: str = "", footer: str | None = None) -> dict:
    """Heading, then body, then a muted footer, as a rich payload. Any part may be omitted.

    The title and footer are inline markdown like the body: escape them if they carry data.
    """
    parts: list[str] = []
    if title:
        parts.append(f"# {title}")
    if body:
        parts.append(body.strip())
    if footer:
        parts.append(f"*{footer}*")
    markdown = sanitise("\n\n".join(parts))
    return {"markdown": markdown, "fallback": to_plain(markdown)}


# -- markdown to plain text --------------------------------------------------
#
# Escaped characters are parked in the private use area while the markup is stripped, so a
# literal asterisk from a definition cannot be mistaken for emphasis, then put back.

_ESCAPED = re.compile(r"\\([\\*_~`|\[\]#>=])")
_PARK_BASE = 0xE000
_PARKED = re.compile("[\ue000-\ue07f]")

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_INLINE = [
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),
    (re.compile(r"__(.+?)__"), r"\1"),
    (re.compile(r"~~(.+?)~~"), r"\1"),
    (re.compile(r"\*(.+?)\*"), r"\1"),
    (re.compile(r"(?<!\w)_(.+?)_(?!\w)"), r"\1"),
    (re.compile(r"`(.+?)`"), r"\1"),
    (re.compile(r"\[(.+?)\]\((.+?)\)"), r"\1"),
]


def to_plain(markdown: str) -> str:
    """The same information as the markdown, with the markup taken out."""
    text = _ESCAPED.sub(lambda m: chr(_PARK_BASE + ord(m.group(1))), markdown)

    out: list[str] = []
    lines = text.split("\n")
    index = 0
    while index < len(lines):
        if _TABLE_ROW.match(lines[index]):
            block = []
            while index < len(lines) and _TABLE_ROW.match(lines[index]):
                block.append(lines[index])
                index += 1
            out.extend(_plain_table(block))
            continue
        out.append(_plain_line(lines[index]))
        index += 1

    plain = "\n".join(out)
    return _PARKED.sub(lambda m: chr(ord(m.group(0)) - _PARK_BASE), plain)


def _plain_line(line: str) -> str:
    line = _HEADING.sub("", line)
    for pattern, replacement in _INLINE:
        line = pattern.sub(replacement, line)
    return line


def _cells(row: str) -> list[str]:
    inner = row.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [_plain_line(cell.strip()) for cell in inner.split("|")]


def _plain_table(block: list[str]) -> list[str]:
    """Header row dropped when it is only a label column, rows as `label: value`."""
    out: list[str] = []
    for position, row in enumerate(block):
        if _TABLE_RULE.match(row):
            continue
        cells = _cells(row)
        is_header = position + 1 < len(block) and _TABLE_RULE.match(block[position + 1])
        filled = [cell for cell in cells if cell]
        if is_header:
            if len(filled) > 1:
                out.append(" | ".join(filled))
            continue
        if len(cells) == 2:
            out.append(f"{cells[0]}: {cells[1]}")
        else:
            out.append(" | ".join(filled))
    return out
