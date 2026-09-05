"""The daily word of the day, and the settings that control it.

Delivery times are stored as a local hour plus an IANA timezone, and the next run is
recalculated in that timezone every time the job fires. Daylight saving therefore needs
no migration and no special case.
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import config
import db
from handlers.common import cmd, on_pending, safe, track
from services import buttons, entries, external, scheduler
from services.buttons import act, on_action
from utils.rich import edit_rich, reply_rich, send_rich_message
from utils.text import esc

log = logging.getLogger("subscriptions")

HOUR_CHOICES = [6, 7, 8, 9, 12, 18, 21]


def _job_key(chat_id: int) -> str:
    return f"wotd:{chat_id}"


def valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def next_run_utc(hour: int, tz_name: str) -> datetime:
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo(config.DEFAULT_TIMEZONE)

    local_now = datetime.now(tz)
    target = local_now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= local_now:
        target += timedelta(days=1)
    return target


def subscription(chat_id: int):
    return db.one("SELECT * FROM subscriptions WHERE chat_id = ?", (chat_id,))


def _schedule(chat_id: int, hour: int, tz_name: str) -> datetime:
    when = next_run_utc(hour, tz_name)
    scheduler.enqueue(
        "daily_wotd",
        {"chat_id": chat_id},
        run_at=db.to_iso(when),
        dedupe_key=_job_key(chat_id),
    )
    return when


def _save(chat_id: int, user_id: int, hour: int, tz_name: str, include_quote: bool = True) -> None:
    db.execute(
        """
        INSERT INTO subscriptions (chat_id, user_id, hour, timezone, include_quote, active)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT (chat_id) DO UPDATE SET
            hour = excluded.hour, timezone = excluded.timezone,
            include_quote = excluded.include_quote, active = 1
        """,
        (chat_id, user_id, hour, tz_name, 1 if include_quote else 0),
    )


def _hour_rows(tz_name: str):
    rows = []
    row = []
    for hour in HOUR_CHOICES:
        row.append(act(f"{hour:02d}:00", "sub:hour", {"h": hour}))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([act(f"Timezone: {tz_name}", "settings:tz")])
    return rows


def settings_pack(chat_id: int, user_id: int) -> dict:
    """The settings screen, shared by the command and the callbacks."""
    row = subscription(chat_id)
    tz_name = row["timezone"] if row else db.user_timezone(user_id)

    if row and row["active"]:
        body = (
            f"<b>Daily word</b>: on, at {row['hour']:02d}:00\n"
            f"<b>Timezone</b>: {esc(tz_name)}\n"
            f"<b>Quote included</b>: {'yes' if row['include_quote'] else 'no'}"
        )
        rows = [
            [act("Change the time", "sub:ask"), act("Change timezone", "settings:tz")],
            [act("Quote: on" if row["include_quote"] else "Quote: off", "settings:quote")],
            [act("Stop the daily word", "sub:off")],
        ]
    else:
        body = (
            f"<b>Daily word</b>: off\n<b>Timezone</b>: {esc(tz_name)}\n\n"
            "Turn the daily word on and a new entry arrives here each morning."
        )
        rows = [
            [act("Turn on the daily word", "sub:ask")],
            [act("Change timezone", "settings:tz")],
        ]

    return {
        "title": "Settings",
        "body": body,
        "buttons": buttons.build(rows, chat_id=chat_id, user_id=user_id),
    }


def register(client):
    @client.on(cmd("sub", "subscribe", "daily"))
    @safe
    async def on_subscribe(event):
        track(event)
        tz_name = db.user_timezone(event.sender_id)
        existing = subscription(event.chat_id)
        body = (
            "Pick a delivery time and a word arrives here every day at that hour. You can "
            "change it or stop it at any time."
        )
        if existing and existing["active"]:
            body = (
                f"You already get the daily word at {existing['hour']:02d}:00 "
                f"{esc(existing['timezone'])}. Pick a different hour to move it."
            )
        await reply_rich(
            event, title="Word of the day", body=body,
            buttons=buttons.build(_hour_rows(tz_name), chat_id=event.chat_id, user_id=event.sender_id),
        )

    @client.on(cmd("unsub", "unsubscribe", "stopdaily"))
    @safe
    async def on_unsubscribe(event):
        track(event)
        existing = subscription(event.chat_id)
        if not existing or not existing["active"]:
            await reply_rich(
                event, title="Not subscribed",
                body="You are not getting a daily word here, so there is nothing to stop.",
            )
            return
        db.execute("UPDATE subscriptions SET active = 0 WHERE chat_id = ?", (event.chat_id,))
        scheduler.cancel(_job_key(event.chat_id))
        await reply_rich(
            event, title="Daily word stopped",
            body="No more daily messages. Send /sub whenever you want them back.",
        )

    @client.on(cmd("settings"))
    @safe
    async def on_settings(event):
        track(event)
        await reply_rich(event, **settings_pack(event.chat_id, event.sender_id))


# -- callbacks -------------------------------------------------------------


@on_action("sub:ask")
async def cb_sub_ask(event, params):
    tz_name = db.user_timezone(event.sender_id)
    await edit_rich(
        event, title="Word of the day",
        body="Pick the hour you want it to arrive.",
        buttons=buttons.build(_hour_rows(tz_name), chat_id=event.chat_id, user_id=event.sender_id),
    )
    await event.answer()


@on_action("sub:hour")
async def cb_sub_hour(event, params):
    hour = int(params.get("h", 8))
    tz_name = db.user_timezone(event.sender_id)
    existing = subscription(event.chat_id)
    include_quote = bool(existing["include_quote"]) if existing else True

    _save(event.chat_id, event.sender_id, hour, tz_name, include_quote)
    when = _schedule(event.chat_id, hour, tz_name)

    await edit_rich(
        event,
        title="Daily word is on",
        body=f"A word arrives here every day at {hour:02d}:00 {esc(tz_name)}.",
        footer=f"First one lands {when.strftime('%d %b at %H:%M')} your time.",
        buttons=buttons.build(
            [[act("Change the time", "sub:ask"), act("Stop it", "sub:off")]],
            chat_id=event.chat_id, user_id=event.sender_id,
        ),
    )
    await event.answer("Subscribed")


@on_action("sub:off")
async def cb_sub_off(event, params):
    db.execute("UPDATE subscriptions SET active = 0 WHERE chat_id = ?", (event.chat_id,))
    scheduler.cancel(_job_key(event.chat_id))
    await edit_rich(
        event, title="Daily word stopped",
        body="No more daily messages. Send /sub whenever you want them back.",
        buttons=buttons.build([[act("Turn it back on", "sub:ask")]],
                              chat_id=event.chat_id, user_id=event.sender_id),
    )
    await event.answer("Stopped")


@on_action("settings:tz")
async def cb_settings_tz(event, params):
    db.set_pending(event.sender_id, {"kind": "timezone", "chat_id": event.chat_id})
    await event.answer()
    await send_rich_message(
        event.client, event.chat_id,
        title="Which timezone?",
        body="Reply with an IANA timezone name, for example <code>Asia/Singapore</code>, "
             "<code>Europe/London</code> or <code>America/New_York</code>. Send /cancel to stop.",
    )


@on_action("settings:quote")
async def cb_settings_quote(event, params):
    row = subscription(event.chat_id)
    if not row:
        await event.answer("Turn the daily word on first.", alert=True)
        return
    db.execute(
        "UPDATE subscriptions SET include_quote = ? WHERE chat_id = ?",
        (0 if row["include_quote"] else 1, event.chat_id),
    )
    await edit_rich(event, **settings_pack(event.chat_id, event.sender_id))
    await event.answer("Updated")


@on_pending("timezone")
async def pending_timezone(event, pending):
    name = event.raw_text.strip()
    if not valid_timezone(name):
        await reply_rich(
            event,
            title="That timezone was not recognised",
            body="Use an IANA name such as <code>Asia/Singapore</code>. Send /cancel to stop.",
        )
        return

    db.set_pending(event.sender_id, None)
    db.execute("UPDATE users SET timezone = ? WHERE telegram_user_id = ?", (name, event.sender_id))

    row = subscription(event.chat_id)
    footer = None
    if row and row["active"]:
        db.execute("UPDATE subscriptions SET timezone = ? WHERE chat_id = ?", (name, event.chat_id))
        when = _schedule(event.chat_id, row["hour"], name)
        footer = f"The next daily word lands {when.strftime('%d %b at %H:%M')} your time."

    await reply_rich(
        event, title="Timezone saved", body=f"Times now use <b>{esc(name)}</b>.", footer=footer
    )


# -- jobs ------------------------------------------------------------------


@scheduler.job("daily_wotd")
async def daily_wotd(client, payload):
    chat_id = int(payload["chat_id"])
    row = subscription(chat_id)
    if not row or not row["active"]:
        scheduler.cancel(_job_key(chat_id))
        return

    entry = entries.word_of_the_day()
    if entry is None:
        log.warning("no catalogue for the daily word, retrying in an hour")
        scheduler.enqueue("daily_wotd", {"chat_id": chat_id}, delay_seconds=3600,
                          dedupe_key=_job_key(chat_id))
        return

    body = f"<b>{esc(entry.get('word') or '-')}</b>\n\n{esc(entry.get('definition') or '')}"
    if row["include_quote"]:
        quote = await external.quote_cached_or_fresh()
        if quote:
            body += f"\n\n<i>{esc(quote['text'])}</i>\n{esc(quote['author'])}"

    rows = [
        [act("Open it", "entry:open", {"tab": "dict", "id": entry["id"], "back": {"v": "home"}})],
        [act("Another entry", "random:roll", {"tab": "all"}), act("Stop the daily word", "sub:off")],
    ]
    await send_rich_message(
        client, chat_id, title="Word of the day", body=body,
        buttons=buttons.build(rows, chat_id=chat_id, user_id=row["user_id"]),
    )

    _schedule(chat_id, row["hour"], row["timezone"])
