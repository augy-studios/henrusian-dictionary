"""The daily word: /sub /unsub /settings, their buttons, and the delivery job.

A person can have the word delivered by DM. Someone with Manage Server can also have it
posted to a channel, which needs the bot itself in that server, not only the user install.
"""

import logging

import discord
from discord import app_commands

import config
import db
import ui
from commands import DESCRIPTIONS
from services import entries, external, scheduler, subscriptions
from services.buttons import on_action
from services.subscriptions import CHANNEL, USER
from ui import Style, act, link
from utils.text import md

log = logging.getLogger("daily")

BOT_PERMISSIONS = discord.Permissions(view_channel=True, send_messages=True, embed_links=True)


def _when(value) -> str:
    """A Discord timestamp, which every reader sees in their own timezone."""
    stamp = int(value.timestamp())
    return f"<t:{stamp}:F> (<t:{stamp}:R>)"


def _where(target_type: str, target_id: int) -> str:
    return "by DM" if target_type == USER else f"in <#{target_id}>"


def _target(params: dict) -> tuple[str, int]:
    return params.get("t", USER), int(params.get("id", 0))


def _can_manage(interaction: discord.Interaction) -> bool:
    return interaction.guild_id is not None and interaction.permissions.manage_guild


def _allowed(interaction: discord.Interaction, target_type: str, target_id: int) -> bool:
    if target_type == USER:
        return interaction.user.id == target_id
    return _can_manage(interaction)


def _invite_url(interaction: discord.Interaction) -> str:
    return discord.utils.oauth_url(
        interaction.client.application_id,
        permissions=BOT_PERMISSIONS,
        guild=discord.Object(id=interaction.guild_id) if interaction.guild_id else discord.utils.MISSING,
        scopes=("bot", "applications.commands"),
    )


# -- screens ---------------------------------------------------------------


def settings_view(target_type: str, target_id: int, *, user_id: int,
                  title: str = "Daily word", guild_rows: list | None = None) -> ui.Pack:
    row = subscriptions.get(target_type, target_id)
    params = {"t": target_type, "id": target_id}

    if row and row["active"]:
        lines = [
            f"**Delivered** {_where(target_type, target_id)}, every day at "
            f"{row['hour']:02d}:00 {row['timezone']}",
            f"**Quote included** {'yes' if row['include_quote'] else 'no'}",
        ]
        upcoming = subscriptions.next_delivery(target_type, target_id)
        if upcoming:
            lines.append(f"**Next one** {_when(upcoming)}")
        rows = [[
            act("Quote: on" if row["include_quote"] else "Quote: off", "settings:quote", params),
            act("Stop the daily word", "sub:off", params, style=Style.danger),
        ]]
    else:
        tz_name = row["timezone"] if row else db.user_timezone(user_id)
        lines = [
            f"**Daily word** off {_where(target_type, target_id)}",
            f"**Timezone** {tz_name}",
        ]
        rows = [[act("Turn on the daily word", "sub:on", params, style=Style.primary)]]

    if guild_rows:
        lines.append("\n**Channels in this server**")
        lines += [f"<#{r['target_id']}> at {r['hour']:02d}:00 {r['timezone']}" for r in guild_rows]

    footer = "Change the hour or timezone with /settings, and pick a channel there for a server post."
    return ui.pack(title, "\n".join(lines), footer, rows)


def daily_post(target_type: str, target_id: int, entry: dict, quote: dict | None) -> ui.Pack:
    body = md(entry.get("definition") or "No definition available.")
    if quote:
        body += f"\n\n> *{md(quote['text'])}*\n> {md(quote['author'])}"

    second = [act("Another entry", "random:roll", {"tab": "all"})]
    if target_type == USER:
        second.append(act("Stop the daily word", "sub:off", {"t": USER, "id": target_id}))
        footer = None
    else:
        footer = "Someone with Manage Server can stop these with /unsub."

    rows = [
        [
            act("☆ Save", "fav:toggle", {"tab": "dict", "id": entry["id"], "back": {"v": "home"}}),
            link("Open in the app", entries.entry_url("dict", entry["id"])),
        ],
        second,
    ]
    return ui.pack(f"Word of the day: {entry.get('word') or '-'}", body, footer, rows)


# -- turning it on ---------------------------------------------------------


def _resolve_settings(target_type: str, target_id: int, user_id: int, hour, tz_name, quote):
    existing = subscriptions.get(target_type, target_id)
    if hour is None:
        hour = existing["hour"] if existing else config.DEFAULT_HOUR
    if tz_name is None:
        tz_name = existing["timezone"] if existing else db.user_timezone(user_id)
    if quote is None:
        quote = bool(existing["include_quote"]) if existing else True
    return hour, tz_name, quote


async def enable_dm(interaction: discord.Interaction, *, hour=None, tz_name=None,
                    quote=None) -> ui.Pack | str:
    """Turn on delivery by DM. A short note is sent first, so a closed DM is found out now
    rather than silently at the first delivery."""
    uid = interaction.user.id
    hour, tz_name, quote = _resolve_settings(USER, uid, uid, hour, tz_name, quote)
    when = subscriptions.next_run(hour, tz_name)

    in_bot_dm = bool(interaction.context and interaction.context.dm_channel)
    if not in_bot_dm:
        note = ui.pack("Daily word is on",
                       f"A word arrives here every day at {hour:02d}:00 {tz_name}. "
                       f"The first one lands {_when(when)}.")
        try:
            await interaction.user.send(embed=note.embed)
        except discord.HTTPException:
            return (
                "I could not send you a DM. Discord only lets me DM people who allow it, "
                "usually by sharing a server with me and allowing direct messages from that "
                "server. Change that and try again, or ask someone with Manage Server to pick "
                "a channel instead."
            )

    subscriptions.enable(USER, uid, owner_id=uid, guild_id=None, hour=hour,
                         tz_name=tz_name, include_quote=quote)
    return settings_view(USER, uid, user_id=uid, title="Daily word is on")


async def enable_channel(interaction: discord.Interaction, channel_id: int, *, hour=None,
                         tz_name=None, quote=None) -> ui.Pack | str:
    if not _can_manage(interaction):
        return "Setting up a channel needs the Manage Server permission."

    channel = interaction.client.get_channel(channel_id)
    if getattr(channel, "guild", None) is not None and channel.guild.id != interaction.guild_id:
        return "That channel is in a different server. Run this from the server it belongs to."
    if channel is None or getattr(channel, "guild", None) is None:
        return (
            "I am not in this server, only installed on someone's account, so I cannot post "
            f"here. [Add me to the server]({_invite_url(interaction)}) and try again."
        )

    perms = channel.permissions_for(channel.guild.me)
    if not (perms.view_channel and perms.send_messages and perms.embed_links):
        return (f"I need View Channel, Send Messages and Embed Links in <#{channel_id}>. "
                "Adjust the channel's permissions and try again.")

    uid = interaction.user.id
    hour, tz_name, quote = _resolve_settings(CHANNEL, channel_id, uid, hour, tz_name, quote)
    subscriptions.enable(CHANNEL, channel_id, owner_id=uid, guild_id=channel.guild.id,
                         hour=hour, tz_name=tz_name, include_quote=quote)
    return settings_view(CHANNEL, channel_id, user_id=uid, title="Daily word is on")


async def _answer(interaction: discord.Interaction, result: ui.Pack | str) -> None:
    if isinstance(result, str):
        await ui.reply(interaction, ui.pack("Not quite", result), ephemeral=True)
    else:
        await ui.reply(interaction, result, ephemeral=True)


async def timezone_autocomplete(interaction: discord.Interaction, current: str):
    needle = current.strip().lower().replace(" ", "_")
    pool = subscriptions.all_timezones() if needle else subscriptions.COMMON_TIMEZONES
    matches = [name for name in pool if needle in name.lower()] if needle else pool
    return [app_commands.Choice(name=name, value=name) for name in matches[:25]]


# -- commands --------------------------------------------------------------


def setup(tree: app_commands.CommandTree) -> None:
    @tree.command(name="sub", description=DESCRIPTIONS["sub"])
    @app_commands.describe(
        hour="Hour of the day it arrives, 0 to 23, in your timezone",
        timezone="An IANA timezone such as Asia/Singapore",
        channel="Post it in this channel instead of by DM. Needs Manage Server",
    )
    @app_commands.autocomplete(timezone=timezone_autocomplete)
    async def sub_command(interaction: discord.Interaction,
                          hour: app_commands.Range[int, 0, 23] | None = None,
                          timezone: str | None = None,
                          channel: discord.TextChannel | None = None):
        if timezone is not None and not subscriptions.valid_timezone(timezone):
            await _answer(interaction, f"`{md(timezone)}` is not a timezone I know. "
                                       "Pick one from the list, such as Asia/Singapore.")
            return

        if channel is None:
            if timezone is not None:
                db.set_user_timezone(interaction.user.id, timezone)
            result = await enable_dm(interaction, hour=hour, tz_name=timezone)
        else:
            result = await enable_channel(interaction, channel.id, hour=hour, tz_name=timezone)
        await _answer(interaction, result)

    @tree.command(name="unsub", description=DESCRIPTIONS["unsub"])
    @app_commands.describe(channel="Stop the post in this channel instead of your DMs")
    async def unsub_command(interaction: discord.Interaction,
                            channel: discord.TextChannel | None = None):
        target_type, target_id = (USER, interaction.user.id) if channel is None else (CHANNEL, channel.id)
        if not _allowed(interaction, target_type, target_id):
            await _answer(interaction, "Stopping a channel's daily word needs the Manage Server permission.")
            return

        if not subscriptions.stop(target_type, target_id):
            await _answer(interaction, f"There is no daily word {_where(target_type, target_id)} to stop.")
            return

        await ui.reply(interaction, ui.pack(
            "Daily word stopped",
            f"No more daily words {_where(target_type, target_id)}. Use /sub whenever you want them back.",
            None, [[act("Turn it back on", "sub:on", {"t": target_type, "id": target_id})]],
        ), ephemeral=True)

    @tree.command(name="settings", description=DESCRIPTIONS["settings"])
    @app_commands.describe(
        timezone="An IANA timezone such as Asia/Singapore",
        hour="Hour of the day the daily word arrives, 0 to 23",
        quote="Attach a quote to the daily word",
        channel="Change a channel's daily word instead of yours. Needs Manage Server",
    )
    @app_commands.autocomplete(timezone=timezone_autocomplete)
    async def settings_command(interaction: discord.Interaction,
                               timezone: str | None = None,
                               hour: app_commands.Range[int, 0, 23] | None = None,
                               quote: bool | None = None,
                               channel: discord.TextChannel | None = None):
        uid = interaction.user.id
        target_type, target_id = (USER, uid) if channel is None else (CHANNEL, channel.id)
        if not _allowed(interaction, target_type, target_id):
            await _answer(interaction, "Changing a channel's daily word needs the Manage Server permission.")
            return

        if timezone is not None and not subscriptions.valid_timezone(timezone):
            await _answer(interaction, f"`{md(timezone)}` is not a timezone I know. "
                                       "Pick one from the list, such as Asia/Singapore.")
            return

        if target_type == USER and timezone is not None:
            db.set_user_timezone(uid, timezone)

        changing = hour is not None or quote is not None or timezone is not None
        if changing and subscriptions.get(target_type, target_id):
            subscriptions.update(target_type, target_id, hour=hour, tz_name=timezone, include_quote=quote)
        elif changing and target_type == CHANNEL:
            await _answer(interaction, f"There is no daily word in <#{target_id}> yet. "
                                       "Start one with /sub and pick the channel.")
            return
        elif (hour is not None or quote is not None) and target_type == USER:
            await _answer(interaction, "The daily word is off, so there is no hour or quote to "
                                       "change yet. Start it with /sub.")
            return

        guild_rows = None
        if target_type == USER and _can_manage(interaction):
            guild_rows = subscriptions.active_in_guild(interaction.guild_id)
        await ui.reply(interaction, settings_view(
            target_type, target_id, user_id=uid, title="Settings", guild_rows=guild_rows,
        ), ephemeral=True)


# -- buttons ---------------------------------------------------------------


@on_action("sub:on")
async def sub_on(ctx: ui.Ctx, params):
    target_type, target_id = _target(params)
    if not _allowed(ctx.interaction, target_type, target_id):
        await ctx.notice("Only the person it belongs to, or someone with Manage Server for a "
                         "channel, can change this.")
        return
    if target_type == USER:
        result = await enable_dm(ctx.interaction)
    else:
        result = await enable_channel(ctx.interaction, target_id)
    if isinstance(result, str):
        await ctx.notice(result)
    else:
        await ctx.show(result)


@on_action("sub:off")
async def sub_off(ctx: ui.Ctx, params):
    target_type, target_id = _target(params)
    if not _allowed(ctx.interaction, target_type, target_id):
        await ctx.notice("Only the person it belongs to, or someone with Manage Server for a "
                         "channel, can change this.")
        return
    subscriptions.stop(target_type, target_id)
    await ctx.show(ui.pack(
        "Daily word stopped",
        f"No more daily words {_where(target_type, target_id)}. Use /sub whenever you want them back.",
        None, [[act("Turn it back on", "sub:on", params)]],
    ))


@on_action("settings:quote")
async def settings_quote(ctx: ui.Ctx, params):
    target_type, target_id = _target(params)
    if not _allowed(ctx.interaction, target_type, target_id):
        await ctx.notice("Only the person it belongs to, or someone with Manage Server for a "
                         "channel, can change this.")
        return
    row = subscriptions.get(target_type, target_id)
    if row is None:
        await ctx.notice("Turn the daily word on first.")
        return
    subscriptions.update(target_type, target_id, include_quote=not row["include_quote"])
    await ctx.show(settings_view(target_type, target_id, user_id=ctx.user_id, title="Settings"))


# -- jobs ------------------------------------------------------------------


@scheduler.job("daily_wotd")
async def daily_wotd(bot: discord.Client, payload):
    target_type, target_id = payload.get("t", USER), int(payload["id"])
    row = subscriptions.get(target_type, target_id)
    if not row or not row["active"]:
        scheduler.cancel(subscriptions.job_key(target_type, target_id))
        return

    entry = entries.word_of_the_day()
    if entry is None:
        log.warning("no catalogue for the daily word, retrying in an hour")
        scheduler.enqueue("daily_wotd", payload, delay_seconds=3600,
                          dedupe_key=subscriptions.job_key(target_type, target_id))
        return

    quote = await external.quote() if row["include_quote"] else None
    screen = daily_post(target_type, target_id, entry, quote)
    # Owned by nobody, so every click gets a private screen and the post itself never changes.
    view = ui.build_view(screen.rows, None)

    try:
        if target_type == USER:
            destination = bot.get_user(target_id) or await bot.fetch_user(target_id)
        else:
            destination = bot.get_channel(target_id) or await bot.fetch_channel(target_id)
        await destination.send(embed=screen.embed, view=view)
    except (discord.Forbidden, discord.NotFound) as exc:
        failures = subscriptions.record_failure(target_type, target_id)
        if failures >= config.MAX_DELIVERY_FAILURES:
            subscriptions.stop(target_type, target_id)
            log.warning("stopped the daily word for %s %s after %s failed deliveries: %s",
                        target_type, target_id, failures, exc)
            return
        log.warning("daily word for %s %s could not be delivered (%s of %s): %s",
                    target_type, target_id, failures, config.MAX_DELIVERY_FAILURES, exc)
    else:
        subscriptions.reset_failures(target_type, target_id)

    subscriptions.schedule(target_type, target_id, row["hour"], row["timezone"])


@scheduler.job("prune_cache")
async def prune_cache(bot, payload):
    removed = external.prune_cache()
    if removed:
        log.info("pruned %s expired api cache rows", removed)
