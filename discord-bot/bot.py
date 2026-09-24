#!/usr/bin/env python3
"""Entry point.

Start with ./run.sh inside tmux. The process is designed to be killed and restarted at
any moment: every piece of state that matters lives in SQLite, including the button
tokens and the job queue, so nothing is lost by a restart.
"""

import asyncio
import hashlib
import json
import logging
import logging.handlers
import sys

import discord
from discord import app_commands

import config
import db
import ui
from commands import daily, general, lookup
from services import buttons, entries, external, scheduler, subscriptions, supabase

log = logging.getLogger("bot")

COMMAND_MODULES = [general, lookup, daily]

# Exit code run.sh treats as fatal, so a bad token does not become a restart loop.
EXIT_CONFIG = 2


def setup_logging() -> None:
    config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)-14s %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        config.LOG_PATH, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


class Tree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.type == discord.InteractionType.application_command:
            db.touch_user(interaction.user)
        return True

    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        command = interaction.command.name if interaction.command else "?"
        log.error("/%s failed", command, exc_info=error)
        try:
            await ui.notice(interaction, "Something went wrong. Please try again.")
        except discord.HTTPException:
            pass


class DictionaryBot(discord.Client):
    def __init__(self) -> None:
        # Slash commands and buttons need no privileged intents. Guilds is enough to
        # resolve a channel for the daily post.
        super().__init__(intents=discord.Intents(guilds=True))
        self.tree = Tree(
            self,
            allowed_installs=app_commands.AppInstallationType(guild=True, user=True),
            allowed_contexts=app_commands.AppCommandContext(
                guild=True, dm_channel=True, private_channel=True
            ),
        )
        self.worker: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        for module in COMMAND_MODULES:
            module.setup(self.tree)

        # One dynamic item routes every button the bot has ever sent back to SQLite.
        self.add_dynamic_items(ui.TokenButton)
        log.info("button actions: %s", ", ".join(buttons.registered_actions()))

        await self.sync_commands()
        self.seed_jobs()
        self.worker = asyncio.create_task(scheduler.worker(self))

        # A first fill so the catalogue is fresh. A failure here is survivable, because the
        # cached copy on disk is still usable.
        try:
            counts = await entries.refresh_all()
            log.info("catalogue: %s", ", ".join(f"{k}={v}" for k, v in counts.items()))
        except Exception:
            log.exception("initial catalogue load failed, continuing with the cached copy")

    async def sync_commands(self) -> None:
        """Register commands with Discord only when they changed, since the endpoint is
        rate limited and a restart loop should not spend the daily allowance."""
        payload = [command.to_dict(self.tree) for command in self.tree.get_commands()]
        digest = hashlib.sha256(
            json.dumps([self.application_id, payload], sort_keys=True, default=str).encode()
        ).hexdigest()
        if db.get_meta("commands_hash") == digest:
            log.info("slash commands unchanged, skipping sync")
            return
        synced = await self.tree.sync()
        db.set_meta("commands_hash", digest)
        log.info("synced %s slash commands", len(synced))

    def seed_jobs(self) -> None:
        scheduler.ensure_recurring("refresh_entries", config.ENTRY_REFRESH_SECONDS)
        scheduler.ensure_recurring("prune_cache", 3600)
        subscriptions.restore_jobs()

    async def on_ready(self) -> None:
        log.info("signed in as %s (%s), in %s servers", self.user, self.user.id, len(self.guilds))

    async def close(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
        await supabase.close()
        await external.close()
        await super().close()
        log.info("stopped")


async def main() -> int:
    config.verify()
    setup_logging()

    db.connect()
    db.apply_schema()
    entries.load_from_disk()

    bot = DictionaryBot()
    try:
        async with bot:
            await bot.start(config.DISCORD_TOKEN)
    except discord.LoginFailure:
        log.error("Discord rejected DISCORD_TOKEN. Check the value in .env.")
        return EXIT_CONFIG
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nStopped.")
