"""/start, /privacy, /cancel, and the home navigation buttons.

/start is the only overview screen. It says what the project is, how to search, and lists
every command, so there is no separate /help or /about. The donation link sits on a button
underneath it rather than behind a command of its own.
"""

import db
from handlers import views
from handlers.common import args_of, cmd, safe, track, tracked_sender
from services import linking
from services.buttons import on_action
from utils.rich import reply_rich

PRIVACY = (
    "<b>What is stored</b>\n"
    "Your Telegram numeric id, your username and first name, your timezone, and the time you "
    "last used the bot. If you save entries before linking, those saves are kept on the "
    "server that runs the bot until you link.\n\n"
    "<b>If you link a browser</b>\n"
    "The link records your Telegram id against an identifier that browser made up for itself, "
    "so favourites can be shared. There is no account, no email address and no password "
    "anywhere in this. Recovery codes are stored only as hashes, and a hash cannot be turned "
    "back into a code.\n\n"
    "<b>What is never stored</b>\n"
    "Message contents, other than a search term while the search runs. There is no logging of "
    "what you look up.\n\n"
    "<b>Removing your data</b>\n"
    "Send /unlink to break the link, and send /privacy again to see this notice. To have "
    "everything erased, including the local record, contact the maintainer through the repository."
)


def register(client):
    @client.on(cmd("start"))
    @safe
    async def on_start(event):
        from handlers import linking as linking_handlers

        user = await tracked_sender(event)
        payload = args_of(event)

        # https://t.me/henrusian_bot?start=<token> arrives here as /start <token>. The
        # website sends people through that link, and tapping Start is what pairs the two.
        if payload:
            if payload.lower() in ("link", "sync"):
                await linking_handlers.show_status_message(event)
                return
            if await linking_handlers.complete_link(event, payload):
                return
            # A payload that is not a usable token falls through to the normal welcome, since
            # complete_link has already explained what went wrong.

        linked = bool(await linking.get_link(event.sender_id)) if user else False
        pack = views.home_view(
            event.chat_id, event.sender_id,
            first_name=user["first_name"] if user else None,
            linked=linked,
        )
        await views.send_view(event, pack)

    @client.on(cmd("privacy"))
    @safe
    async def on_privacy(event):
        track(event)
        await reply_rich(event, title="Privacy", body=PRIVACY)

    @client.on(cmd("cancel"))
    @safe
    async def on_cancel(event):
        track(event)
        pending = db.get_pending(event.sender_id)
        db.set_pending(event.sender_id, None)
        if pending:
            await reply_rich(event, title="Cancelled", body="Nothing else is waiting on you.")
        else:
            await reply_rich(
                event,
                title="Nothing to cancel",
                body="There was no step in progress, so nothing changed.",
            )


@on_action("home:show")
async def show_home(event, params):
    user = db.get_user(event.sender_id)
    linked = linking.cached_linked(event.sender_id)
    pack = views.home_view(
        event.chat_id, event.sender_id,
        first_name=user["first_name"] if user else None,
        linked=linked,
    )
    await views.edit_view(event, pack)


@on_action("search:prompt")
async def prompt_search(event, params):
    await event.answer("Just send me a word and I will look it up.")


@on_action("noop")
async def noop(event, params):
    await event.answer()
