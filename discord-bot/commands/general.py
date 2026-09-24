"""/help and /privacy, and the buttons that belong to them.

/help is the only overview screen. It says what the project is, lists every command, and
carries the buttons for the web app and the donation link.
"""

import discord
from discord import app_commands

import db
import ui
import views
from commands import DESCRIPTIONS
from services import favourites, subscriptions
from services.buttons import on_action


def setup(tree: app_commands.CommandTree) -> None:
    @tree.command(name="help", description=DESCRIPTIONS["help"])
    async def help_command(interaction: discord.Interaction):
        await ui.reply(interaction, views.help_view())

    @tree.command(name="privacy", description=DESCRIPTIONS["privacy"])
    async def privacy_command(interaction: discord.Interaction):
        await ui.reply(interaction, views.privacy_view(), ephemeral=True)


@on_action("home:show")
async def home_show(ctx: ui.Ctx, params):
    await ctx.show(views.help_view())


@on_action("noop")
async def noop(ctx: ui.Ctx, params):
    await ctx.interaction.response.defer()


@on_action("privacy:show")
async def privacy_show(ctx: ui.Ctx, params):
    await ctx.show(views.privacy_view())


@on_action("privacy:erase")
async def privacy_erase(ctx: ui.Ctx, params):
    await ctx.show(views.erase_confirm_view())


@on_action("privacy:erase_confirm")
async def privacy_erase_confirm(ctx: ui.Ctx, params):
    removed = favourites.clear(ctx.user_id)
    subscriptions.delete(subscriptions.USER, ctx.user_id)
    db.execute("DELETE FROM users WHERE discord_user_id = ?", (ctx.user_id,))
    db.execute("DELETE FROM callbacks WHERE user_id = ?", (ctx.user_id,))
    body = (
        f"Removed {removed} saved {'entry' if removed == 1 else 'entries'}, your daily word "
        "by DM, your buttons, and your record. Using a command again starts a fresh one."
    )
    await ctx.show(ui.pack("Erased", body))
