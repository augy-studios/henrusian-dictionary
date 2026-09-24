"""Screens, buttons and the one dispatcher every button click goes through.

A screen is a Pack: an embed plus rows of Btn. Screens are built by pure functions in
views.py, so any old button can rebuild its screen from its stored parameters alone.

Every action button is a TokenButton, a discord.py DynamicItem whose custom_id is
"hd:<token>". It is registered once at startup, so discord.py routes a click on any
message the bot has ever sent back here, whether or not this process sent it. The token
is looked up in SQLite, and the action registered for it runs.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import discord

import config
import db
from services import buttons
from utils.text import sanitise, truncate

log = logging.getLogger("ui")

Style = discord.ButtonStyle


@dataclass
class Btn:
    """A button before it has a token. Either an action button or a plain link."""

    label: str
    action: Optional[str] = None
    params: Optional[dict] = None
    url: Optional[str] = None
    style: Style = Style.secondary
    disabled: bool = False


def act(label: str, action: str, params: dict | None = None, *,
        style: Style = Style.secondary, disabled: bool = False) -> Btn:
    return Btn(label=label, action=action, params=params or {}, style=style, disabled=disabled)


def link(label: str, url: str) -> Btn:
    return Btn(label=label, url=url, style=Style.link)


@dataclass
class Pack:
    embed: discord.Embed
    rows: list[list[Btn]] = field(default_factory=list)


def embed(title: str, body: str | None = None, footer: str | None = None) -> discord.Embed:
    """The one place an embed is made, so the colour and the copy rules are never missed."""
    out = discord.Embed(
        title=truncate(sanitise(title), 256),
        description=truncate(sanitise(body), 4096) if body else None,
        colour=config.EMBED_COLOUR,
    )
    if footer:
        out.set_footer(text=truncate(sanitise(footer), 2048))
    return out


def pack(title: str, body: str | None = None, footer: str | None = None,
         rows: list[list[Btn]] | None = None) -> Pack:
    return Pack(embed(title, body, footer), rows or [])


class TokenButton(discord.ui.DynamicItem[discord.ui.Button],
                  template=r"hd:(?P<token>[A-Za-z0-9_\-]{6,64})"):
    def __init__(self, token: str, *, label: str = "Open", style: Style = Style.secondary,
                 disabled: bool = False, row: int | None = None) -> None:
        super().__init__(
            discord.ui.Button(label=label, style=style, disabled=disabled,
                              custom_id=f"{buttons.PREFIX}{token}"),
            row=row,
        )
        self.token = token

    @classmethod
    async def from_custom_id(cls, interaction, item, match, /):
        return cls(match["token"])

    async def callback(self, interaction: discord.Interaction) -> None:
        await dispatch(interaction, self.token)


def build_view(rows: list[list[Btn]], user_id: int | None) -> Optional[discord.ui.View]:
    """Turn rows of Btn into a view, persisting every action token for user_id.

    Discord allows five rows of five. Anything beyond that is a bug in a screen, so it is
    logged and dropped rather than failing the whole message.
    """
    if len(rows) > 5 or any(len(row) > 5 for row in rows):
        log.warning("a screen asked for more than five rows or five buttons in a row")

    view = discord.ui.View(timeout=None)
    for index, row in enumerate(rows[:5]):
        for item in row[:5]:
            label = truncate(sanitise(item.label), 80)
            if item.url:
                view.add_item(discord.ui.Button(label=label, url=item.url, row=index))
                continue
            token = buttons.mint(item.action, item.params or {}, user_id)
            view.add_item(TokenButton(token, label=label, style=item.style,
                                      disabled=item.disabled, row=index))
    return view if view.children else None


async def reply(interaction: discord.Interaction, screen: Pack, *, ephemeral: bool = False) -> None:
    """Answer a slash command with a screen owned by whoever ran it."""
    kwargs = {"embed": screen.embed, "ephemeral": ephemeral}
    view = build_view(screen.rows, interaction.user.id)
    if view is not None:
        kwargs["view"] = view
    if interaction.response.is_done():
        await interaction.followup.send(**kwargs)
    else:
        await interaction.response.send_message(**kwargs)


async def notice(interaction: discord.Interaction, text: str) -> None:
    """A short private message, the closest thing Discord has to a toast."""
    if interaction.response.is_done():
        await interaction.followup.send(sanitise(text), ephemeral=True)
    else:
        await interaction.response.send_message(sanitise(text), ephemeral=True)


class Ctx:
    """What a button handler gets. show() edits the message for its owner, and gives
    anybody else a private copy of the next screen, so one person's click never changes a
    message someone else is reading."""

    def __init__(self, interaction: discord.Interaction, owner_id: int | None):
        self.interaction = interaction
        self.user = interaction.user
        self.user_id = interaction.user.id
        self.mine = owner_id is not None and owner_id == self.user_id

    async def show(self, screen: Pack) -> None:
        view = build_view(screen.rows, self.user_id)
        if self.mine and not self.interaction.response.is_done():
            await self.interaction.response.edit_message(embed=screen.embed, view=view)
            return
        await reply(self.interaction, screen, ephemeral=True)

    async def notice(self, text: str) -> None:
        await notice(self.interaction, text)


async def dispatch(interaction: discord.Interaction, token: str) -> None:
    record = buttons.resolve(token)
    if record is None:
        await notice(interaction, "This button is no longer available. Use /help to start again.")
        return

    handler = buttons.handler_for(record["action"])
    if handler is None:
        log.warning("no handler registered for action %r", record["action"])
        await notice(interaction, "That action is not available any more.")
        return

    db.touch_user(interaction.user)
    try:
        await handler(Ctx(interaction, record["user_id"]), record["params"])
    except Exception:
        log.exception("button %s failed", record["action"])
        try:
            await notice(interaction, "Something went wrong. Please try again.")
        except discord.HTTPException:
            pass
