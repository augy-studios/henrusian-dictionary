"""Reading the catalogue: /search /random /wotd /favs /stats, and their buttons."""

import logging

import discord
from discord import app_commands

import ui
import views
from commands import DESCRIPTIONS
from services import entries, favourites, scheduler
from services.buttons import on_action

log = logging.getLogger("lookup")

CATALOGUES = [
    app_commands.Choice(name="All", value="all"),
    app_commands.Choice(name="Words", value="dict"),
    app_commands.Choice(name="Idioms", value="idioms"),
    app_commands.Choice(name="Names", value="names"),
]


def _tab(choice: app_commands.Choice[str] | None) -> str:
    return choice.value if choice else "all"


def setup(tree: app_commands.CommandTree) -> None:
    @tree.command(name="search", description=DESCRIPTIONS["search"])
    @app_commands.describe(
        query="A word, or part of one, or anything in a definition",
        catalogue="Search one catalogue instead of all three",
        private="Show the results only to you",
    )
    @app_commands.choices(catalogue=CATALOGUES)
    async def search_command(interaction: discord.Interaction,
                             query: app_commands.Range[str, 1, 100],
                             catalogue: app_commands.Choice[str] | None = None,
                             private: bool = False):
        screen = views.results_view(q=query.strip(), tab=_tab(catalogue))
        await ui.reply(interaction, screen, ephemeral=private)

    @search_command.autocomplete("query")
    async def search_autocomplete(interaction: discord.Interaction, current: str):
        needle = current.strip().lower()
        if not needle:
            return []
        seen = set()
        choices = []
        for tab in entries.TAB_ORDER:
            for entry in entries.all_entries(tab):
                word = (entry.get("word") or "").strip()
                if not word or word.lower() in seen or not word.lower().startswith(needle):
                    continue
                seen.add(word.lower())
                choices.append(app_commands.Choice(name=word[:100], value=word[:100]))
                if len(choices) == 25:
                    return choices
        return choices

    @tree.command(name="random", description=DESCRIPTIONS["random"])
    @app_commands.describe(catalogue="Pick from one catalogue instead of all three")
    @app_commands.choices(catalogue=CATALOGUES)
    async def random_command(interaction: discord.Interaction,
                             catalogue: app_commands.Choice[str] | None = None):
        tab = _tab(catalogue)
        entry = entries.random_entry(tab)
        if entry is None:
            await ui.reply(interaction, ui.pack("Not ready yet", views.LOADING), ephemeral=True)
            return
        await ui.reply(interaction, views.entry_view(
            interaction.user.id, tab=entry["tab"], entry_id=entry["id"],
            back={"v": "random", "tab": tab},
        ))

    @tree.command(name="wotd", description=DESCRIPTIONS["wotd"])
    async def wotd_command(interaction: discord.Interaction):
        entry = entries.word_of_the_day()
        if entry is None:
            await ui.reply(interaction, ui.pack("Not ready yet", views.LOADING), ephemeral=True)
            return
        await ui.reply(interaction, views.entry_view(
            interaction.user.id, tab="dict", entry_id=entry["id"], heading_prefix="Word of the day",
        ))

    @tree.command(name="favs", description=DESCRIPTIONS["favs"])
    async def favs_command(interaction: discord.Interaction):
        await ui.reply(interaction, views.favourites_view(interaction.user.id), ephemeral=True)

    @tree.command(name="stats", description=DESCRIPTIONS["stats"])
    async def stats_command(interaction: discord.Interaction):
        await ui.reply(interaction, views.stats_view())


# -- buttons ---------------------------------------------------------------


@on_action("results:page")
async def results_page(ctx: ui.Ctx, params):
    await ctx.show(views.results_view(
        q=params.get("q", ""), tab=params.get("tab", "all"),
        sort=params.get("sort", "alpha-asc"), page=int(params.get("p", 0)),
    ))


@on_action("results:tab")
async def results_tab(ctx: ui.Ctx, params):
    await ctx.show(views.results_view(
        q=params.get("q", ""), tab=params.get("tab", "all"), sort=params.get("sort", "alpha-asc"),
    ))


@on_action("results:sort")
async def results_sort(ctx: ui.Ctx, params):
    await ctx.show(views.results_view(
        q=params.get("q", ""), tab=params.get("tab", "all"),
        sort=entries.next_sort(params.get("sort", "alpha-asc")),
    ))


@on_action("entry:open")
async def entry_open(ctx: ui.Ctx, params):
    await ctx.show(views.entry_view(
        ctx.user_id, tab=params.get("tab", "dict"), entry_id=str(params.get("id")),
        back=params.get("back"),
    ))


@on_action("random:roll")
async def random_roll(ctx: ui.Ctx, params):
    tab = params.get("tab", "all")
    entry = entries.random_entry(tab)
    if entry is None:
        await ctx.notice(views.LOADING)
        return
    await ctx.show(views.entry_view(
        ctx.user_id, tab=entry["tab"], entry_id=entry["id"], back={"v": "random", "tab": tab},
    ))


@on_action("wotd:show")
async def wotd_show(ctx: ui.Ctx, params):
    entry = entries.word_of_the_day()
    if entry is None:
        await ctx.notice(views.LOADING)
        return
    await ctx.show(views.entry_view(
        ctx.user_id, tab="dict", entry_id=entry["id"], heading_prefix="Word of the day",
    ))


@on_action("fav:toggle")
async def fav_toggle(ctx: ui.Ctx, params):
    tab = params.get("tab", "dict")
    entry_id = str(params.get("id"))
    if entries.find(tab, entry_id) is None:
        await ctx.notice("That entry is no longer in the catalogue.")
        return
    favourites.toggle(ctx.user_id, tab, entry_id)
    await ctx.show(views.entry_view(ctx.user_id, tab=tab, entry_id=entry_id, back=params.get("back")))


@on_action("favs:page")
async def favs_page(ctx: ui.Ctx, params):
    await ctx.show(views.favourites_view(ctx.user_id, page=int(params.get("p", 0))))


# -- jobs ------------------------------------------------------------------


@scheduler.job("refresh_entries")
async def refresh_entries(bot, payload):
    counts = await entries.refresh_all()
    log.info("catalogue refreshed: %s", ", ".join(f"{k}={v}" for k, v in counts.items()))
