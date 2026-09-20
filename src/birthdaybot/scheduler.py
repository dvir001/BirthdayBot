import logging
from datetime import UTC, datetime, timedelta

import discord

from birthdaybot.calendar import due_events, events_for_year
from birthdaybot.i18n import t
from birthdaybot.ui import channel_usable, media_file, notice_view

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, bot):
        self.bot = bot
        self.next_audit = datetime.min.replace(tzinfo=UTC)

    async def member(self, profile):
        guild = self.bot.get_guild(profile["guild_id"])
        if guild is None:
            await self.bot.db.membership(profile["guild_id"], profile["user_id"], False)
            return None
        if guild.unavailable:
            return None
        try:
            member = await guild.fetch_member(profile["user_id"])
        except discord.NotFound:
            await self.bot.db.membership(profile["guild_id"], profile["user_id"], False)
            return None
        await self.bot.db.membership(profile["guild_id"], profile["user_id"], True)
        return member

    async def tick(self):
        if not self.bot.is_ready():
            return
        async with self.bot.db.pool.connection() as connection:
            cursor = await connection.execute("SELECT pg_try_advisory_lock(481975002) AS acquired")
            if not (await cursor.fetchone())["acquired"]:
                return
            try:
                await self.process()
            finally:
                await connection.execute("SELECT pg_advisory_unlock(481975002)")

    async def process(self):
        now = datetime.now(UTC)
        profiles = await self.bot.db.profiles()
        for profile in profiles:
            if not profile["enabled"]:
                continue
            settings = await self.bot.db.settings(profile["guild_id"])
            if not settings or not settings["enabled"] or not settings["channel_id"]:
                continue
            for event in due_events(profile, now):
                try:
                    await self.deliver(profile, event, settings)
                except Exception:
                    log.exception("Scheduled delivery failed for guild %s", profile["guild_id"])
        if now >= self.next_audit:
            for profile in profiles:
                try:
                    await self.member(profile)
                except discord.HTTPException:
                    log.warning("Membership check unavailable for guild %s", profile["guild_id"])
            await self.bot.db.cleanup()
            self.next_audit = now + timedelta(hours=1)

    async def deliver(self, profile, event, settings):
        member = await self.member(profile)
        if member is None:
            return
        guild = member.guild
        channel = guild.get_channel(settings["channel_id"])
        if channel is None:
            channel = await guild.fetch_channel(settings["channel_id"])
        if not channel_usable(channel, guild.me):
            log.warning("Birthday channel unusable for guild %s", guild.id)
            return
        current = await self.bot.db.get_profile(
            profile["guild_id"], profile["user_id"], media=event.kind == "birthday"
        )
        if current is None or current["updated_at"] != profile["updated_at"]:
            return
        if event not in due_events(current, datetime.now(UTC)):
            return
        if not await self.bot.db.claim(current, event, settings["channel_id"]):
            return
        try:
            if event.kind == "notice":
                birthday_event = events_for_year(
                    current["month"],
                    current["day"],
                    current["timezone"],
                    [],
                    event.birthday.year,
                    current["announcement_time"],
                )[0]
                await member.send(
                    t(
                        "post.notice",
                        server=discord.utils.escape_markdown(guild.name),
                        time=discord.utils.format_dt(birthday_event.due_at, "F"),
                        local_time=current["announcement_time"].strftime("%H:%M"),
                        timezone=current["timezone"],
                    ),
                    view=notice_view(current, event.birthday),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            else:
                file = media_file(current) if event.kind == "birthday" else None
                await channel.send(
                    t(
                        f"post.{event.kind}",
                        mention=member.mention,
                        date=event.birthday.isoformat(),
                    ),
                    files=[file] if file else [],
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False,
                        roles=False,
                        users=[member],
                        replied_user=False,
                    ),
                )
        except Exception:
            await self.bot.db.finish(current, event, "failed")
            raise
        await self.bot.db.finish(current, event, "sent")
