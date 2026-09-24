"""Screens.

Every screen is a pure function of its parameters, which is what makes the durable
buttons work: a message from months ago carries a token, the token carries the
parameters, and the screen can be rebuilt from scratch after a restart that cleared all
memory. Buttons are minted for whoever the screen is shown to, in ui.build_view.
"""

import math

import config
from commands import COMMANDS
from services import entries, favourites
from ui import Pack, Style, act, embed, link, pack
from utils.text import format_date, md, one_line, plural, truncate

STAR_ON = "★"
STAR_OFF = "☆"

LOADING = (
    "The catalogue is still loading. Please try again in a few seconds, and if this keeps "
    "happening the database may be unreachable."
)

INTRO = (
    "This is the Henrusian Dictionary on Discord, the open source dictionary for the "
    "Henrusian constructed language, 15th edition. It is built and maintained by Augy "
    "Studios under the UwU Apps umbrella and released under the MIT licence.\n\n"
    "Search words, idioms and names, save the ones you want to keep, and get a word of the "
    "day by DM or in a server channel. Everything here reads the same catalogue as the web "
    "app, so the two never disagree."
)


def _tab_label(tab: str) -> str:
    return entries.SINGULAR.get(tab, "Entry")


def _listing(number: int, entry: dict, preview: str) -> str:
    """One numbered line for a results or favourites page."""
    line = f"**{number}. {md(entry.get('word') or '-')}**  *{_tab_label(entry['tab'])}*"
    if preview:
        line += f"\n{md(preview)}"
    return line


def _chunk(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _nav_row(action: str, base: dict, page: int, total_pages: int) -> list:
    """Prev, a disabled page counter, Next. The counter is a token button too, because a
    plain custom_id would keep the whole view alive in discord.py's memory forever."""
    return [
        act("Prev", action, {**base, "p": page - 1}, disabled=page <= 0),
        act(f"{page + 1} of {total_pages}", "noop", {"page": page + 1}, disabled=True),
        act("Next", action, {**base, "p": page + 1}, disabled=page >= total_pages - 1),
    ]


# -- help ------------------------------------------------------------------


def help_view() -> Pack:
    lines = "\n".join(f"**/{name}** {desc[0].lower() + desc[1:]}" for name, desc in COMMANDS)
    body = f"{INTRO}\n\n**Commands**\n{lines}"
    rows = [
        [
            link("Open the dictionary", config.WEB_APP_URL),
            link("Support the project", config.DONATION_URL),
            link("Source code", config.REPO_URL),
        ],
        [
            act("Word of the day", "wotd:show", style=Style.primary),
            act("Random entry", "random:roll", {"tab": "all"}),
            act("Your favourites", "favs:page", {"p": 0}),
        ],
    ]
    return pack("Henrusian Dictionary", body, "Start with /search followed by any word.", rows)


# -- search results --------------------------------------------------------


def results_view(*, q: str = "", tab: str = "all", sort: str = "alpha-asc", page: int = 0) -> Pack:
    if entries.is_empty():
        return pack("Not ready yet", LOADING)

    hits = entries.search(q, tab, sort)
    per_page = config.RESULTS_PER_PAGE
    total_pages = max(1, math.ceil(len(hits) / per_page))
    page = max(0, min(page, total_pages - 1))
    window = hits[page * per_page : page * per_page + per_page]

    scope = "all catalogues" if tab == "all" else entries.LABELS[tab].lower()
    title = truncate(f"Search: {q}", 200) if q else f"Browsing {scope}"
    base = {"q": q, "tab": tab, "sort": sort}

    if not hits:
        body = f"Nothing matched **{md(q)}** in {scope}."
        return pack(title, body, None, [_tab_row(q, tab, sort)])

    lines = []
    entry_buttons = []
    for offset, entry in enumerate(window, start=1):
        number = page * per_page + offset
        preview = truncate(one_line(entry.get("definition") or "No definition available."), 90)
        lines.append(_listing(number, entry, preview))
        entry_buttons.append(act(
            truncate(f"{number}. {one_line(entry.get('word') or '-')}", 40), "entry:open",
            {"tab": entry["tab"], "id": entry["id"], "back": {"v": "results", **base, "p": page}},
        ))

    rows = _chunk(entry_buttons, 4)
    rows.append(_tab_row(q, tab, sort))
    sort_button = act(f"Sort: {entries.SORT_LABELS[sort]}", "results:sort", base)
    if total_pages > 1:
        rows.append([sort_button, *_nav_row("results:page", base, page, total_pages)])
    else:
        rows.append([sort_button])

    many = "matches" if tab == "all" else entries.LABELS[tab].lower()
    footer = plural(len(hits), "match" if tab == "all" else _tab_label(tab).lower(), many)
    return pack(title, "\n\n".join(lines), footer, rows)


def _tab_row(q: str, tab: str, sort: str) -> list:
    row = []
    for name in ["all"] + entries.TAB_ORDER:
        label = "All" if name == "all" else entries.LABELS[name]
        style = Style.primary if name == tab else Style.secondary
        row.append(act(label, "results:tab", {"q": q, "tab": name, "sort": sort}, style=style))
    return row


# -- a single entry --------------------------------------------------------


def entry_view(user_id: int, *, tab: str, entry_id: str, back: dict | None = None,
               heading_prefix: str | None = None) -> Pack:
    back = back or {"v": "home"}
    entry = entries.find(tab, entry_id)
    if entry is None:
        return pack("Entry not found", "That entry is no longer in the catalogue.", None,
                    [[act("Menu", "home:show")]])

    saved = favourites.is_favourite(user_id, tab, entry_id)
    body = f"*{_tab_label(tab)}*\n\n{md(entry.get('definition') or 'No definition available.')}"

    added = format_date(entry.get("created_at"))
    footer = f"Added {added}" if added else None

    star = act(
        f"{STAR_ON} Saved" if saved else f"{STAR_OFF} Save",
        "fav:toggle",
        {"tab": tab, "id": entry_id, "back": back},
        style=Style.success if saved else Style.secondary,
    )
    rows = [[star, link("Open in the app", entries.entry_url(tab, entry_id))]]

    if back.get("v") == "results":
        rows.append([act("Back to results", "results:page", {
            "q": back.get("q", ""), "tab": back.get("tab", "all"),
            "sort": back.get("sort", "alpha-asc"), "p": back.get("p", 0),
        })])
    elif back.get("v") == "favs":
        rows.append([act("Back to favourites", "favs:page", {"p": back.get("p", 0)})])
    elif back.get("v") == "random":
        rows.append([act("Another random", "random:roll", {"tab": back.get("tab", "all")},
                         style=Style.primary)])
    else:
        rows.append([act("Menu", "home:show")])

    title = entry.get("word") or "-"
    if heading_prefix:
        title = f"{heading_prefix}: {title}"
    return pack(title, body, footer, rows)


# -- favourites ------------------------------------------------------------


def favourites_view(user_id: int, *, page: int = 0) -> Pack:
    ids = favourites.ids_for(user_id)
    resolved = []
    for tab, entry_id in ids:
        entry = entries.find(tab, entry_id)
        if entry:
            resolved.append({**entry, "tab": tab})
    resolved.sort(key=lambda e: (entries.TAB_ORDER.index(e["tab"]), (e.get("word") or "").lower()))

    if not resolved:
        body = (
            "You have not saved anything yet. Open any entry and press Save, and it appears "
            "here. Saved entries belong to your Discord account and are private to you."
        )
        return pack("Your favourites", body, None, [[act("Menu", "home:show")]])

    per_page = config.FAVS_PER_PAGE
    total_pages = max(1, math.ceil(len(resolved) / per_page))
    page = max(0, min(page, total_pages - 1))
    window = resolved[page * per_page : page * per_page + per_page]

    lines = []
    entry_buttons = []
    for offset, entry in enumerate(window, start=1):
        number = page * per_page + offset
        lines.append(_listing(number, entry, truncate(one_line(entry.get("definition") or ""), 80)))
        entry_buttons.append(act(
            truncate(f"{number}. {one_line(entry.get('word') or '-')}", 40), "entry:open",
            {"tab": entry["tab"], "id": entry["id"], "back": {"v": "favs", "p": page}},
        ))

    rows = _chunk(entry_buttons, 4)
    if total_pages > 1:
        rows.append(_nav_row("favs:page", {}, page, total_pages))
    rows.append([act("Menu", "home:show")])

    missing = len(ids) - len(resolved)
    footer = plural(len(resolved), "saved entry", "saved entries")
    if missing > 0:
        footer += f", and {missing} that are no longer in the catalogue"
    return pack("Your favourites", "\n\n".join(lines), footer, rows)


# -- stats and privacy -----------------------------------------------------


def stats_view() -> Pack:
    counts = entries.counts()
    out = embed("Catalogue")
    for tab in entries.TAB_ORDER:
        out.add_field(name=entries.LABELS[tab], value=f"{counts[tab]:,}", inline=True)
    out.add_field(name="Total", value=f"{sum(counts.values()):,}", inline=False)

    newest = ""
    for tab in entries.TAB_ORDER:
        for entry in entries.all_entries(tab):
            stamp = entry.get("created_at") or ""
            if stamp > newest:
                newest = stamp

    bits = []
    if newest:
        bits.append(f"Newest entry added {format_date(newest)}")
    age = entries.cache_age_seconds()
    if age is not None:
        bits.append(f"catalogue refreshed {age // 60} minutes ago")
    if bits:
        out.set_footer(text=", ".join(bits))
    return Pack(out, [[link("Open the dictionary", config.WEB_APP_URL)]])


PRIVACY = (
    "**What is stored**\n"
    "Your Discord user id, username and display name, your timezone, the time you last "
    "used a command, the entries you save, and your daily word settings if you turn it on. "
    "For a server channel subscription, the server and channel ids and who set it up.\n\n"
    "**What is never stored**\n"
    "Message contents. The bot cannot read messages at all, only the commands you run and "
    "the buttons you press. A search term is kept only as part of the buttons on its results, "
    "which is what lets those buttons keep working, and there is no log of what you look up.\n\n"
    "**Where it lives**\n"
    "In a SQLite file on the server that runs the bot. Nothing about you is sent to the "
    "dictionary's database or to the web app, and your saved entries here are separate "
    "from any you keep in a browser.\n\n"
    "**Removing your data**\n"
    "Press the button below to erase your saved entries, your DM subscription, the buttons "
    "made for you, and your record. Channel subscriptions belong to the server, and /unsub "
    "removes those."
)


def privacy_view() -> Pack:
    return pack("Privacy", PRIVACY, None, [[act("Erase my data", "privacy:erase", style=Style.danger)]])


def erase_confirm_view() -> Pack:
    body = (
        "This deletes your saved entries, stops your daily word by DM, and removes your "
        "record. Buttons on messages made for you, search results included, stop working. "
        "It cannot be undone."
    )
    return pack("Erase everything?", body, None, [[
        act("Yes, erase it", "privacy:erase_confirm", style=Style.danger),
        act("Keep it", "privacy:show"),
    ]])
