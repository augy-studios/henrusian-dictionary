"""/favs, plus the star buttons that appear on every entry."""

import logging

from handlers import views
from handlers.common import cmd, safe, track
from services import favourites
from services.buttons import on_action

log = logging.getLogger("favourites")


def register(client):
    @client.on(cmd("favs", "favourites", "favorites", "saved"))
    @safe
    async def on_favourites(event):
        track(event)
        pack = await views.favourites_view(event.chat_id, event.sender_id, page=0)
        await views.send_view(event, pack)


@on_action("favs:page")
async def favs_page(event, params):
    pack = await views.favourites_view(event.chat_id, event.sender_id, page=int(params.get("p", 0)))
    await views.edit_view(event, pack)
    await event.answer()


@on_action("fav:toggle")
async def fav_toggle(event, params):
    tab = params.get("tab", "dict")
    entry_id = str(params.get("id"))
    now_saved = await favourites.toggle(event.sender_id, tab, entry_id)

    pack = await views.entry_view(
        event.chat_id, event.sender_id, tab=tab, entry_id=entry_id,
        back=params.get("back") or {"v": "home"},
    )
    await views.edit_view(event, pack)
    await event.answer("Saved" if now_saved else "Removed from your favourites")


@on_action("fav:remove")
async def fav_remove(event, params):
    tab = params.get("tab", "dict")
    entry_id = str(params.get("id"))
    still_saved = await favourites.toggle(event.sender_id, tab, entry_id)
    if still_saved:
        # It was not saved after all, so the toggle just added it. Undo, and say so.
        await favourites.toggle(event.sender_id, tab, entry_id)
        await event.answer("That entry was already removed.")
    else:
        await event.answer("Removed from your favourites")

    pack = await views.favourites_view(event.chat_id, event.sender_id, page=int(params.get("p", 0)))
    await views.edit_view(event, pack)
