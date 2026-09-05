"""View rendering.

Every view is a pure function of its parameters, which is what makes the durable buttons
work: a message from months ago carries a token, the token carries the parameters, and
the view can be rebuilt from scratch even after a restart that cleared all memory.
"""

import math

import config
import db
from services import buttons, entries, favourites
from services.buttons import act, link
from utils.rich import edit_rich, reply_rich
from utils.text import esc, format_date, one_line, plural, truncate

STAR_ON = "★"
STAR_OFF = "☆"

INTRO = (
    "This is the Henrusian Dictionary in Telegram, the open source dictionary for the "
    "Henrusian constructed language, 15th edition. It is built and maintained by Augy "
    "Studios under the UwU Apps umbrella and released under the MIT licence.\n\n"
    "Search words, idioms and names, save the ones you want to keep, and get a word of the "
    "day if you like. Everything here reads the same catalogue as the web app, so the two "
    "never disagree.\n\n"
    "<b>To search, just send a word.</b> No command needed. The buttons on the results "
    "narrow them to Words, Idioms or Names, and change the sort order."
)


def _tab_label(tab: str) -> str:
    return entries.SINGULAR.get(tab, "Entry")


async def send_view(event, pack: dict):
    """Post a packed view and record what the message now shows."""
    sent = await reply_rich(
        event,
        title=pack["title"],
        body=pack["body"],
        footer=pack["footer"],
        buttons=pack["buttons"],
    )
    if sent is not None and pack.get("view"):
        db.remember_view(event.chat_id, sent.id, pack["view"], pack["params"])
    return sent


async def edit_view(event, pack: dict):
    """Replace the contents of the message a callback came from."""
    await edit_rich(
        event,
        title=pack["title"],
        body=pack["body"],
        footer=pack["footer"],
        buttons=pack["buttons"],
    )
    message_id = getattr(event, "message_id", None)
    if message_id and pack.get("view"):
        db.remember_view(event.chat_id, message_id, pack["view"], pack["params"])


def _pack(title, body, footer, rows, chat_id, user_id, view=None, params=None):
    return {
        "title": title,
        "body": body,
        "footer": footer,
        "buttons": buttons.build(rows, chat_id=chat_id, user_id=user_id),
        "view": view,
        "params": params or {},
    }


# -- home ------------------------------------------------------------------


def home_view(chat_id, user_id, *, first_name: str | None = None, linked: bool = False):
    greeting = f"Hello {esc(first_name)}. " if first_name else ""
    body = greeting + INTRO + "\n\n<b>Commands</b>\n" + _command_lines()

    rows = [
        [link("Open the dictionary", config.WEB_APP_URL)],
        [link("Support the project", config.DONATION_URL)],
        [link("Source code", config.REPO_URL)],
        [act("Word of the day", "wotd:show"), act("Random entry", "random:roll", {"tab": "all"})],
        [
            act("Your favourites", "favs:page", {"p": 0}),
            act("Link status", "link:status") if linked else act("Sync with Telegram", "link:status"),
        ],
    ]
    footer = "To search, just send me a word. There is no command to remember."
    return _pack("Henrusian Dictionary", body, footer, rows, chat_id, user_id, "home")


def _command_lines() -> str:
    from handlers.common import COMMANDS

    return "\n".join(f"/{name} {esc(desc.lower())}" for name, desc in COMMANDS)


# -- search results --------------------------------------------------------


def results_view(chat_id, user_id, *, q: str = "", tab: str = "all", sort: str = "alpha-asc", page: int = 0):
    hits = entries.search(q, tab, sort)
    per_page = config.RESULTS_PER_PAGE
    total_pages = max(1, math.ceil(len(hits) / per_page)) if hits else 1
    page = max(0, min(page, total_pages - 1))
    window = hits[page * per_page : page * per_page + per_page]

    scope = "all catalogues" if tab == "all" else entries.LABELS[tab].lower()
    title = f"Search: {esc(q)}" if q else f"Browsing {scope}"

    if not hits:
        body = (
            f"Nothing matched <b>{esc(q)}</b> in {esc(scope)}."
            if q
            else "The catalogue has not loaded yet. Please try again in a moment."
        )
        rows = [_tab_row(q, tab, sort), [act("Back", "home:show")]]
        return _pack(title, body, None, rows, chat_id, user_id, "results",
                     {"q": q, "tab": tab, "sort": sort, "p": page})

    lines = []
    result_rows = []
    for offset, entry in enumerate(window, start=1):
        number = page * per_page + offset
        preview = truncate(one_line(entry.get("definition") or "No definition available."), 90)
        lines.append(
            f"<b>{number}. {esc(entry.get('word') or '-')}</b>  "
            f"<i>{esc(_tab_label(entry['tab']))}</i>\n{esc(preview)}"
        )
        label = truncate(f"{number}. {one_line(entry.get('word') or '-')}", 24)
        result_rows.append(
            act(label, "entry:open", {
                "tab": entry["tab"],
                "id": entry["id"],
                "back": {"v": "results", "q": q, "tab": tab, "sort": sort, "p": page},
            })
        )

    rows = [result_rows[i : i + 2] for i in range(0, len(result_rows), 2)]
    rows.append(_tab_row(q, tab, sort))
    rows.append([act(f"Sort: {entries.SORT_LABELS[sort]}", "results:sort",
                     {"q": q, "tab": tab, "sort": sort})])

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(act("Prev", "results:page", {"q": q, "tab": tab, "sort": sort, "p": page - 1}))
        nav.append(act(f"{page + 1} of {total_pages}", "noop"))
        if page < total_pages - 1:
            nav.append(act("Next", "results:page", {"q": q, "tab": tab, "sort": sort, "p": page + 1}))
        rows.append(nav)

    footer = plural(len(hits), _tab_label(tab).lower() if tab != "all" else "match",
                    "matches" if tab == "all" else entries.LABELS[tab].lower())
    return _pack(title, "\n\n".join(lines), footer, rows, chat_id, user_id, "results",
                 {"q": q, "tab": tab, "sort": sort, "p": page})


def _tab_row(q, tab, sort):
    row = []
    for name in ["all"] + entries.TAB_ORDER:
        label = "All" if name == "all" else entries.LABELS[name]
        if name == tab:
            label = f"[{label}]"
        row.append(act(label, "results:tab", {"q": q, "tab": name, "sort": sort}))
    return row


# -- a single entry --------------------------------------------------------


async def entry_view(chat_id, user_id, *, tab: str, entry_id: str, back: dict | None = None,
                     gloss: str | None = None):
    entry = entries.find(tab, entry_id)
    if entry is None:
        rows = [[act("Back", "home:show")]]
        return _pack("Entry not found", "That entry is no longer in the catalogue.", None,
                     rows, chat_id, user_id, "entry", {"tab": tab, "id": entry_id})

    saved = await favourites.is_favourite(user_id, tab, entry_id)

    body = f"<i>{esc(_tab_label(tab))}</i>\n\n{esc(entry.get('definition') or 'No definition available.')}"
    if gloss:
        body += f"\n\n<i>In English: {esc(gloss)}</i>"

    added = format_date(entry.get("created_at"))
    footer = f"Added {added}" if added else None

    star = act(
        f"{STAR_ON} Saved" if saved else f"{STAR_OFF} Save",
        "fav:toggle",
        {"tab": tab, "id": entry_id, "back": back or {"v": "home"}},
    )
    rows = [[star], [link("Open in the app", entries.entry_url(tab, entry_id))]]

    back = back or {}
    if back.get("v") == "results":
        rows.append([act("Back to results", "results:page", {
            "q": back.get("q", ""), "tab": back.get("tab", "all"),
            "sort": back.get("sort", "alpha-asc"), "p": back.get("p", 0),
        })])
    elif back.get("v") == "favs":
        rows.append([act("Back to favourites", "favs:page", {"p": back.get("p", 0)})])
    elif back.get("v") == "random":
        rows.append([act("Another random", "random:roll", {"tab": back.get("tab", "all")})])
    else:
        rows.append([act("Back", "home:show")])

    return _pack(esc(entry.get("word") or "-"), body, footer, rows, chat_id, user_id,
                 "entry", {"tab": tab, "id": entry_id, "back": back})


# -- favourites ------------------------------------------------------------


async def favourites_view(chat_id, user_id, *, page: int = 0):
    from services import linking

    ids = await favourites.ids_for(user_id)
    resolved = []
    for tab, entry_id in ids:
        entry = entries.find(tab, entry_id)
        if entry:
            resolved.append({**entry, "tab": tab})
    resolved.sort(key=lambda e: (e["tab"], (e.get("word") or "").lower()))

    per_page = config.RESULTS_PER_PAGE
    total_pages = max(1, math.ceil(len(resolved) / per_page)) if resolved else 1
    page = max(0, min(page, total_pages - 1))
    window = resolved[page * per_page : page * per_page + per_page]

    linked = linking.cached_linked(user_id)

    if not resolved:
        body = (
            "You have not saved anything yet. Open any entry and tap Save, and it appears here."
        )
        rows = [[act("Search", "search:prompt")], [act("Back", "home:show")]]
        if not linked:
            rows.insert(1, [act("Sync with Telegram", "link:status")])
        return _pack("Your favourites", body, None, rows, chat_id, user_id, "favs", {"p": page})

    lines = []
    entry_rows = []
    for offset, entry in enumerate(window, start=1):
        number = page * per_page + offset
        preview = truncate(one_line(entry.get("definition") or ""), 80)
        lines.append(
            f"<b>{number}. {esc(entry.get('word') or '-')}</b>  <i>{esc(_tab_label(entry['tab']))}</i>"
            + (f"\n{esc(preview)}" if preview else "")
        )
        entry_rows.append(
            act(truncate(f"{number}. {one_line(entry.get('word') or '-')}", 20), "entry:open",
                {"tab": entry["tab"], "id": entry["id"], "back": {"v": "favs", "p": page}})
        )
        entry_rows.append(
            act(f"{STAR_ON}", "fav:remove", {"tab": entry["tab"], "id": entry["id"], "p": page})
        )

    rows = [entry_rows[i : i + 2] for i in range(0, len(entry_rows), 2)]

    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(act("Prev", "favs:page", {"p": page - 1}))
        nav.append(act(f"{page + 1} of {total_pages}", "noop"))
        if page < total_pages - 1:
            nav.append(act("Next", "favs:page", {"p": page + 1}))
        rows.append(nav)

    rows.append([act("Back", "home:show")])

    missing = len(ids) - len(resolved)
    footer = plural(len(resolved), "saved entry", "saved entries")
    if missing > 0:
        footer += f", and {missing} that are no longer in the catalogue"
    if not linked:
        footer += ". These are stored on this device only until you link an account"

    return _pack("Your favourites", "\n\n".join(lines), footer, rows, chat_id, user_id,
                 "favs", {"p": page})
