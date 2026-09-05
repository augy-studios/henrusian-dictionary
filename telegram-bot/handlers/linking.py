"""Pairing browsers with this Telegram account, and the Telegram half of the backup codes.

There is no account and no sign in anywhere in this. A link pairs one browser with one
Telegram account, and one Telegram account can pair with as many browsers as it likes. They
all share the same collection of favourites.

  /link    Lists the browsers you have paired, or explains how to pair one. Linking has to
           begin in the browser, since only the browser knows which device is being paired.
  /start   Receives the token from https://t.me/<bot>?start=<token> and completes a pairing.
  /code    Takes a token typed by hand, for a browser that cannot open the deep link, or a
           recovery code to move the whole collection onto this Telegram account.
  /unlink  Asks which browser to release, or all of them, and confirms before doing it.

Backup codes are created on the website. This bot only approves the request, and never sees
or shows a code.
"""

import logging

import config
import db
from handlers.common import args_of, cmd, on_pending, private_only, safe, track
from services import backup_codes, buttons, favourites, linking, scheduler
from services.buttons import act, link, on_action
from utils.rich import edit_rich, reply_rich, send_rich_message
from utils.text import esc, truncate

log = logging.getLogger("linking")


def sync_page() -> str:
    return f"{config.WEB_APP_URL}/link"


# -- status ----------------------------------------------------------------


async def status_body(user_id: int) -> tuple[str, str, list]:
    devices = await linking.linked_devices(user_id)

    if not devices:
        local = len(favourites.local_ids(user_id))
        body = (
            "No browser is paired with this Telegram account yet.\n\n"
            f"You have {local} saved {'entry' if local == 1 else 'entries'} here, kept just "
            "for this chat.\n\n"
            "<b>To pair one</b>, open the dictionary in your browser, then tap Sync with "
            "Telegram. That brings you straight back here, and one tap finishes it. Anything "
            "saved on either side is merged into one collection, with no duplicates."
        )
        rows = [
            [link("Open the dictionary", sync_page())],
            [act("How does this work?", "link:how")],
        ]
        return "Not paired", body, rows

    left = await backup_codes.remaining(user_id)
    saved = len(await favourites.ids_for(user_id))

    lines = [
        f"{'One browser is' if len(devices) == 1 else str(len(devices)) + ' browsers are'} "
        "sharing favourites with this chat.\n"
    ]
    for device in devices:
        lines.append(f"  {esc(linking.describe(device))}")
    lines.append("")
    lines.append(f"<b>Saved entries</b>: {saved}")
    lines.append(f"<b>Recovery codes left</b>: {left}")

    body = "\n".join(lines)
    if left == 0:
        body += (
            "\n\nYou have no recovery codes. Without one, a Telegram account you can no "
            "longer reach cannot release these pairings, so create a set on the website."
        )

    rows = [
        [link("Pair another browser", sync_page())],
        [link("Recovery codes on the website", sync_page())],
        [act("Remove a pairing", "unlink:ask")],
    ]
    return "Paired", body, rows


async def show_status_message(event):
    title, body, rows = await status_body(event.sender_id)
    await reply_rich(
        event, title=title, body=body,
        buttons=buttons.build(rows, chat_id=event.chat_id, user_id=event.sender_id),
    )


# -- completing a pairing --------------------------------------------------


async def complete_link(event, token: str, *, quiet_on_failure: bool = False) -> bool:
    """Claim a pairing token and merge both sides. Used by /start and by /code."""
    sender = await event.get_sender()
    reason, result = await linking.claim_token(
        token, event.sender_id, getattr(sender, "username", None)
    )

    if reason != "ok":
        db.execute(
            "INSERT INTO link_attempts (telegram_user_id, code, outcome) "
            "VALUES (?, ?, 'link-failed')",
            (event.sender_id, linking.normalise_token(token)),
        )
        if quiet_on_failure:
            return False
        await reply_rich(
            event,
            title="That link has expired",
            body=(
                "Pairing tokens last ten minutes and work once. Open the dictionary again and "
                "tap Sync with Telegram for a fresh one."
            ),
            buttons=buttons.build([[link("Open the dictionary", sync_page())]],
                                  chat_id=event.chat_id, user_id=event.sender_id),
        )
        return False

    merged = await favourites.merge_on_link(event.sender_id, result["device_favourites"])
    device = result["link"].get("device_label") or "that browser"
    count = result["devices"]

    if result["first"]:
        body = (
            f"{esc(device)} and this chat now share one collection of favourites. Star "
            "something in either place and it shows up in the other."
        )
    else:
        body = (
            f"{esc(device)} has joined in, so {count} browsers now share the same collection "
            "with this chat."
        )

    if merged["from_device"] or merged["from_bot"]:
        body += (
            f"\n\n<b>Merged</b>: {merged['from_device']} from that browser and "
            f"{merged['from_bot']} from here, giving {merged['total']} in total. "
            "Anything saved twice was only kept once."
        )

    rows = [[act("Your favourites", "favs:page", {"p": 0})]]
    left = await backup_codes.remaining(event.sender_id)
    if left == 0:
        body += (
            "\n\nNext, create recovery codes on the website. They are the only way to release "
            "these pairings if you ever lose access to Telegram, and you will be asked to "
            "approve the request here first."
        )
        rows.insert(0, [link("Create recovery codes", sync_page())])

    await reply_rich(
        event, title="Paired", body=body,
        buttons=buttons.build(rows, chat_id=event.chat_id, user_id=event.sender_id),
    )
    return True


HOW_IT_WORKS = (
    "There are no accounts here, and nothing to sign in to. A pairing simply joins one "
    "browser to one Telegram account.\n\n"
    "<b>1.</b> Open the dictionary in your browser and tap Sync with Telegram.\n"
    "<b>2.</b> The browser hands you a link that opens this chat. Tap Start.\n"
    "<b>3.</b> That is it. Favourites from both sides are merged into one collection, and "
    "stay in step from then on.\n\n"
    "Pair as many browsers as you like, a laptop, a phone, a desktop at work. They all share "
    "the same collection.\n\n"
    "If a browser cannot open the link, it shows a short code instead. Send it here with "
    "/code and the pairing is made the same way.\n\n"
    "Either side can end a pairing at any time: /unlink here, or Remove the link on the "
    "website. Everyone keeps the favourites they have."
)


def register(client):
    @client.on(cmd("link", "links", "devices"))
    @private_only
    @safe
    async def on_link(event):
        track(event)
        await show_status_message(event)

    @client.on(cmd("unlink"))
    @private_only
    @safe
    async def on_unlink(event):
        track(event)
        devices = await linking.linked_devices(event.sender_id)
        if not devices:
            await reply_rich(
                event,
                title="Nothing to unlink",
                body="No browser is paired with this Telegram account at the moment.",
            )
            return
        await reply_rich(event, **(await unlink_prompt(event.chat_id, event.sender_id, devices)))

    @client.on(cmd("code", "recover"))
    @private_only
    @safe
    async def on_code(event):
        track(event)
        value = args_of(event)
        if not value:
            db.set_pending(event.sender_id, {"kind": "code"})
            await reply_rich(
                event,
                title="Send your code",
                body=(
                    "Reply with the code from the website. Both kinds work here:\n\n"
                    "An eight character pairing code such as <code>7QK4XM2P</code> pairs that "
                    "browser with this Telegram account.\n"
                    "A twelve character recovery code such as <code>ABCD-EFGH-JKMN</code> "
                    "moves an existing collection onto this Telegram account.\n\n"
                    "Send /cancel to stop."
                ),
            )
            return
        await redeem_any(event, value)


async def unlink_prompt(chat_id: int, user_id: int, devices: list) -> dict:
    """One row per paired browser, plus an option to release the lot."""
    rows = [
        [act(truncate(device.get("device_label") or "a browser", 28), "unlink:one",
             {"id": device["id"]})]
        for device in devices
    ]
    if len(devices) > 1:
        rows.append([act(f"All {len(devices)} browsers", "unlink:all")])
    rows.append([act("Keep them", "unlink:no")])

    body = (
        "Nothing happens until you choose.\n\n"
        "Everyone keeps the favourites they have now. This chat keeps its own copy, each "
        "browser keeps its own copy, and they simply stop being shared."
    )
    return {
        "title": "Which pairing should go?" if len(devices) > 1 else "Remove the pairing?",
        "body": body,
        "buttons": buttons.build(rows, chat_id=chat_id, user_id=user_id),
    }


# -- redeeming either kind of code -----------------------------------------


async def redeem_any(event, value: str):
    """One entry point for both kinds. The lengths differ, so there is no guessing."""
    cleaned = backup_codes.normalise(value)

    locked = backup_codes.locked_out(event.sender_id)
    if locked:
        await reply_rich(
            event,
            title="Too many attempts",
            body=f"Several codes have failed here. Please try again in "
                 f"{max(1, locked // 60)} minutes.",
        )
        return

    if len(cleaned) == linking.TOKEN_LENGTH:
        await complete_link(event, cleaned)
        return
    if len(cleaned) == backup_codes.GROUPS * backup_codes.GROUP_LENGTH:
        await _redeem_recovery(event, cleaned)
        return

    await reply_rich(
        event,
        title="That does not look like a code",
        body=(
            "A pairing code is eight characters, and a recovery code is twelve, usually "
            f"written in three groups of four. What arrived was {len(cleaned)} characters "
            "long.\n\nCheck it on the website and send it again."
        ),
    )


async def _redeem_recovery(event, code: str):
    owner = await backup_codes.redeem(code, event.sender_id)
    if not owner:
        await reply_rich(
            event,
            title="That code did not work",
            body=(
                "It may have been used already, replaced by a newer set, or simply mistyped. "
                "Check it and try again, or open the website to create a fresh set."
            ),
        )
        return

    if int(owner) == int(event.sender_id):
        await reply_rich(
            event,
            title="Nothing to move",
            body="That code belongs to this Telegram account, which already holds the "
                 "collection. The code has been spent, so keep the rest somewhere safe.",
        )
        return

    sender = await event.get_sender()
    moved_devices = await linking.move_collection(
        owner, event.sender_id, getattr(sender, "username", None)
    )
    total = await favourites.move_collection(owner, event.sender_id)
    await favourites.merge_on_link(event.sender_id)
    left = await backup_codes.remaining(owner)

    # The codes travel with the collection, since they protect it rather than an account.
    await backup_codes.move_codes(owner, event.sender_id)

    body = (
        f"This Telegram account now holds the collection. "
        f"{moved_devices} {'browser' if moved_devices == 1 else 'browsers'} came across, and "
        f"your {total} saved {'entry' if total == 1 else 'entries'} are back."
    )
    body += f"\n\nRecovery codes left: {left}."
    if left <= 2:
        body += " That is running low, so create a new set on the website."

    await reply_rich(
        event, title="Recovered", body=body,
        buttons=buttons.build([[link("Recovery codes on the website", sync_page())]],
                              chat_id=event.chat_id, user_id=event.sender_id),
    )

    try:
        await send_rich_message(
            event.client, int(owner),
            title="Your collection moved",
            body="Somebody used a recovery code to move these pairings to a different "
                 "Telegram account. If that was not you, open the dictionary on your device "
                 "and create a new set of recovery codes straight away.",
        )
    except Exception:
        log.info("could not notify the previous holder %s", owner)


@on_pending("code")
async def pending_code(event, pending):
    db.set_pending(event.sender_id, None)
    await redeem_any(event, event.raw_text.strip())


# -- callbacks -------------------------------------------------------------


@on_action("link:status")
async def cb_link_status(event, params):
    title, body, rows = await status_body(event.sender_id)
    await edit_rich(
        event, title=title, body=body,
        buttons=buttons.build(rows, chat_id=event.chat_id, user_id=event.sender_id),
    )
    await event.answer()


@on_action("link:how")
async def cb_link_how(event, params):
    await edit_rich(
        event, title="How pairing works", body=HOW_IT_WORKS,
        buttons=buttons.build(
            [[link("Open the dictionary", sync_page())], [act("Back", "link:status")]],
            chat_id=event.chat_id, user_id=event.sender_id,
        ),
    )
    await event.answer()


@on_action("unlink:ask")
async def cb_unlink_ask(event, params):
    devices = await linking.linked_devices(event.sender_id)
    if not devices:
        await event.answer("Nothing is paired.", alert=True)
        return
    await edit_rich(event, **(await unlink_prompt(event.chat_id, event.sender_id, devices)))
    await event.answer()


@on_action("unlink:one")
async def cb_unlink_one(event, params):
    row = await linking.unlink_device(event.sender_id, params.get("id"))
    if row is None:
        await event.answer("That pairing has already gone.", alert=True)
        await cb_link_status(event, {})
        return

    remaining = await linking.linked_devices(event.sender_id)
    kept = 0
    if not remaining:
        # The last one, so this chat takes its own copy and the shared rows go.
        kept = await favourites.keep_local_copy(event.sender_id)
        await favourites.drop_shared(event.sender_id)

    label = row.get("device_label") or "That browser"
    body = f"{esc(label)} no longer shares favourites with this chat."
    if remaining:
        body += (
            f"\n\n{len(remaining)} {'browser is' if len(remaining) == 1 else 'browsers are'} "
            "still paired, and the collection carries on as it was."
        )
    else:
        body += (
            f"\n\nThat was the last one. Your {kept} saved "
            f"{'entry' if kept == 1 else 'entries'} stayed here, and each browser keeps its "
            "own copy. Nothing was lost."
        )

    await edit_rich(
        event, title="Pairing removed", body=body,
        buttons=buttons.build([[link("Pair a browser", sync_page())]],
                              chat_id=event.chat_id, user_id=event.sender_id),
    )
    await event.answer()


@on_action("unlink:all")
async def cb_unlink_all(event, params):
    kept = await favourites.keep_local_copy(event.sender_id)
    removed = await linking.unlink_all(event.sender_id)
    await favourites.drop_shared(event.sender_id)

    await edit_rich(
        event,
        title="Pairings removed" if removed else "Nothing to remove",
        body=(
            f"{removed} {'browser is' if removed == 1 else 'browsers are'} no longer sharing "
            f"favourites with this chat. Your {kept} saved "
            f"{'entry' if kept == 1 else 'entries'} stayed here, and each browser keeps its "
            "own copy."
            if removed
            else "Nothing was paired, so nothing changed."
        ),
        buttons=buttons.build([[link("Pair a browser", sync_page())]],
                              chat_id=event.chat_id, user_id=event.sender_id),
    )
    await event.answer()


@on_action("unlink:no")
async def cb_unlink_no(event, params):
    title, body, rows = await status_body(event.sender_id)
    await edit_rich(
        event, title=title, body=body,
        buttons=buttons.build(rows, chat_id=event.chat_id, user_id=event.sender_id),
    )
    await event.answer("Nothing changed")


@on_action("codes:approve")
async def cb_codes_approve(event, params):
    """Approve a request raised on the website. The site reveals the codes, not the bot."""
    request_id = params.get("r")
    reason, request = await backup_codes.claim_request(request_id, event.sender_id)

    if reason == "missing":
        await event.answer("That request is no longer available.", alert=True)
        return
    if reason == "settled":
        await event.answer("That request has already been dealt with.", alert=True)
        return
    if reason == "expired":
        await edit_rich(
            event, title="The request expired",
            body="Nothing was approved in time, so no codes were created and the ones you "
                 "already have still work. Ask again on the website when you are ready.",
            buttons=buttons.build([[link("Open the website", sync_page())]],
                                  chat_id=event.chat_id, user_id=event.sender_id),
        )
        await event.answer()
        return

    await edit_rich(
        event,
        title="Approved",
        body=(
            "Your new recovery codes are ready. Go back to the browser that asked for them to "
            "see them, where they are shown once and then never again.\n\n"
            "Any unused codes from before stop working the moment the new set appears."
        ),
        footer="They are deliberately not sent through Telegram, so they do not sit in your "
               "chat history.",
        buttons=buttons.build([[link("Show my codes", sync_page())]],
                              chat_id=event.chat_id, user_id=event.sender_id),
    )
    await event.answer("Approved")


@on_action("codes:reject")
async def cb_codes_reject(event, params):
    rejected = await backup_codes.reject_request(params.get("r"), event.sender_id)
    await edit_rich(
        event,
        title="Request rejected" if rejected else "Nothing to reject",
        body=(
            "No codes were created and the ones you already have still work.\n\n"
            "If you did not ask for this, somebody may be using one of the browsers paired "
            "with this chat. Removing that pairing stops it immediately."
            if rejected
            else "That request had already been dealt with, so nothing changed."
        ),
        buttons=buttons.build([[act("Remove a pairing", "unlink:ask")]],
                              chat_id=event.chat_id, user_id=event.sender_id)
        if rejected
        else None,
    )
    await event.answer()


# -- jobs ------------------------------------------------------------------


@scheduler.job("link_sweep")
async def link_sweep(client, payload):
    """Notice pairings that were removed from a browser.

    The website only revokes the row, because it cannot know when this side has taken its
    copy. This is that step: when the last browser goes, keep the favourites locally, clear
    the shared rows, and say what happened.
    """
    cached = db.query("SELECT telegram_user_id FROM users WHERE linked = 1")
    for row in cached:
        telegram_user_id = row["telegram_user_id"]
        try:
            devices = await linking.linked_devices(telegram_user_id)
        except Exception:
            continue
        if devices:
            continue

        kept = await favourites.keep_local_copy(telegram_user_id)
        await favourites.drop_shared(telegram_user_id)
        db.execute(
            "UPDATE users SET linked = 0, linked_at = NULL WHERE telegram_user_id = ?",
            (telegram_user_id,),
        )
        log.info("last pairing for %s went, kept %s favourites locally", telegram_user_id, kept)

        try:
            await send_rich_message(
                client, telegram_user_id,
                title="The last pairing was removed",
                body=(
                    "No browser is sharing favourites with this chat any more.\n\n"
                    f"The {kept} saved {'entry' if kept == 1 else 'entries'} you had are kept "
                    "here, and each browser keeps its own copy. Nothing was lost."
                ),
                buttons=buttons.build([[link("Pair again", sync_page())]],
                                      chat_id=telegram_user_id, user_id=telegram_user_id),
            )
        except Exception:
            log.info("could not tell %s that the pairing was removed", telegram_user_id)


@scheduler.job("code_request_poll")
async def code_request_poll(client, payload):
    """Announce recovery code requests raised on the website.

    The website cannot message anybody, so this is the step that turns a request into an
    approval prompt. Marking the row as notified first means a send that fails is not retried
    forever.
    """
    try:
        pending = await backup_codes.awaiting_notification()
    except Exception:
        log.exception("could not read pending recovery code requests")
        return

    for request in pending:
        telegram_user_id = request.get("telegram_user_id")
        if not telegram_user_id:
            continue

        await backup_codes.mark_notified(request["id"])
        left = await backup_codes.remaining(telegram_user_id)
        asked_by = request.get("device_label") or "A browser"
        warning = (
            f"Approving replaces the {left} unused {'code' if left == 1 else 'codes'} you "
            f"already have with {config.BACKUP_CODE_COUNT} new ones."
            if left
            else f"Approving creates {config.BACKUP_CODE_COUNT} codes."
        )

        rows = [
            [act("Approve", "codes:approve", {"r": request["id"]})],
            [act("Reject this request", "codes:reject", {"r": request["id"]})],
        ]
        try:
            await send_rich_message(
                client, int(telegram_user_id),
                title="Approve new recovery codes",
                body=(
                    f"{esc(asked_by)} has asked for a new set of recovery codes.\n\n"
                    f"{warning} They are shown once, on the website, right after you approve "
                    "here.\n\nIf that was not you, reject it. Nothing changes until you choose."
                ),
                footer="This request expires shortly, so approve it while you are here.",
                buttons=buttons.build(rows, chat_id=int(telegram_user_id),
                                      user_id=int(telegram_user_id)),
            )
        except Exception:
            log.warning("could not deliver a code request to %s", telegram_user_id)
