import logging
import os

import discord
from discord import app_commands
from discord.ext import tasks

from birthdaybot.db import Database
from birthdaybot.i18n import t
from birthdaybot.media import MAX_MEDIA_BYTES, parse_media_limit
from birthdaybot.scheduler import Scheduler
from birthdaybot.ui import NoticeButton, register_commands, report_error

log = logging.getLogger(__name__)


class CommandTree(app_commands.CommandTree):
    async def on_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message(t("error.permissions"), ephemeral=True)
        else:
            await report_error(interaction, error)


class BirthdayBot(discord.Client):
    def __init__(
        self,
        database_url: str,
        test_guild_id: int | None = None,
        max_media_bytes: int = MAX_MEDIA_BYTES,
    ):
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.db = Database(database_url)
        self.tree = CommandTree(self)
        self.scheduler = Scheduler(self)
        self.test_guild_id = test_guild_id
        self.max_media_bytes = max_media_bytes
        register_commands(self)

    async def setup_hook(self):
        await self.db.open()
        self.add_dynamic_items(NoticeButton)
        if self.test_guild_id:
            guild = discord.Object(id=self.test_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        self.schedule.start()

    async def on_ready(self):
        log.info("BirthdayBot connected to %s servers", len(self.guilds))

    @tasks.loop(seconds=30)
    async def schedule(self):
        try:
            await self.scheduler.tick()
        except Exception:
            log.exception("Scheduler tick failed; will try again next tick")

    @schedule.before_loop
    async def before_schedule(self):
        await self.wait_until_ready()

    async def close(self):
        self.schedule.cancel()
        task = self.schedule.get_task()
        if task is not None:
            import asyncio

            try:
                await task
            except asyncio.CancelledError:
                pass
        await self.db.close()
        await super().close()


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    token = os.environ.get("DISCORD_TOKEN")
    database_url = os.environ.get("DATABASE_URL")
    if not token or not database_url:
        raise SystemExit("DISCORD_TOKEN and DATABASE_URL must be set")
    test_guild_id = os.environ.get("DISCORD_TEST_GUILD_ID")
    try:
        max_media_bytes = parse_media_limit(os.environ.get("MAX_MEDIA_BYTES"))
    except ValueError as error:
        raise SystemExit(str(error)) from error
    bot = BirthdayBot(
        database_url,
        int(test_guild_id) if test_guild_id else None,
        max_media_bytes,
    )
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
