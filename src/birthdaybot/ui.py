import io
import logging
import re
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import discord
from discord import app_commands

from birthdaybot.calendar import REMINDERS, events_for_year, upcoming_birthday
from birthdaybot.i18n import t
from birthdaybot.media import validate_metadata, validate_video

log = logging.getLogger(__name__)

COMMON_TIMEZONES = (
    "UTC",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Anchorage",
    "Pacific/Honolulu",
    "America/Sao_Paulo",
    "America/Argentina/Buenos_Aires",
    "Europe/London",
    "Europe/Paris",
    "Europe/Athens",
    "Europe/Moscow",
    "Africa/Cairo",
    "Asia/Jerusalem",
    "Asia/Dubai",
    "Asia/Karachi",
    "Asia/Kolkata",
    "Asia/Dhaka",
    "Asia/Bangkok",
    "Asia/Singapore",
    "Asia/Tokyo",
    "Australia/Adelaide",
    "Australia/Sydney",
    "Pacific/Auckland",
)
TIMEZONES = tuple(sorted(available_timezones()))


def timezone_label(timezone: str) -> str:
    offset = datetime.now(UTC).astimezone(ZoneInfo(timezone)).utcoffset()
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, minutes = divmod(abs(minutes), 60)
    locations = t(f"timezone.{timezone}")
    return f"(UTC{sign}{hours:02d}:{minutes:02d}) {locations}"


def timezone_options(selected: str | None = None) -> list[discord.SelectOption]:
    return [
        discord.SelectOption(
            label=timezone_label(timezone),
            value=timezone,
            default=timezone == selected,
        )
        for timezone in COMMON_TIMEZONES
    ]


def timezone_choices(current: str) -> list[app_commands.Choice[str]]:
    query = current.casefold()
    matches = sorted(
        (timezone for timezone in TIMEZONES if query in timezone.casefold()),
        key=lambda timezone: (not timezone.casefold().startswith(query), timezone),
    )
    return [app_commands.Choice(name=timezone, value=timezone) for timezone in matches[:25]]


async def report_error(interaction: discord.Interaction, error: Exception):
    log.error("Interaction failed", exc_info=error)
    if interaction.response.is_done():
        await interaction.followup.send(t("error.generic"), ephemeral=True)
    else:
        await interaction.response.send_message(t("error.generic"), ephemeral=True)


def video_file(profile: dict) -> discord.File | None:
    if profile.get("video"):
        return discord.File(io.BytesIO(profile["video"]), filename=profile["video_name"])
    return None


async def dashboard(bot, guild_id: int, user_id: int):
    profile = await bot.db.get_profile(guild_id, user_id)
    if profile is None:
        return t("error.missing"), None
    settings = await bot.db.settings(guild_id)
    reminders = ", ".join(t(f"reminder.{value}") for value in profile["reminders"])
    content = (
        "**"
        + t("dashboard.title")
        + "**\n"
        + t(
            "dashboard.body",
            day=profile["day"],
            month=profile["month"],
            timezone=profile["timezone"],
            status=t("state.active" if profile["enabled"] else "state.paused"),
            reminders=reminders or t("state.none"),
            video=t("state.video" if profile["video_name"] else "state.none"),
            skip=profile["skip_date"] or t("state.none"),
            server=t(
                "state.active"
                if settings and settings["enabled"] and settings["channel_id"]
                else "state.server_disabled"
            ),
        )
    )
    return content, Dashboard(bot, guild_id, user_id, profile)


class BirthdayModal(discord.ui.Modal):
    def __init__(self, bot, guild_id: int, user_id: int, profile=None):
        super().__init__(title=t("setup.title"), timeout=600)
        self.bot, self.guild_id, self.user_id = bot, guild_id, user_id
        self.birthday = discord.ui.TextInput(
            placeholder=t("setup.date_placeholder"),
            min_length=3,
            max_length=5,
            default=f"{profile['day']:02d}/{profile['month']:02d}" if profile else None,
        )
        self.timezone = discord.ui.Select(
            placeholder=t("setup.timezone_placeholder"),
            options=timezone_options(profile["timezone"] if profile else None),
        )
        self.reminders = discord.ui.Select(
            placeholder=t("setup.reminders_placeholder"),
            min_values=0,
            max_values=3,
            required=False,
            options=[
                discord.SelectOption(
                    label=t(f"reminder.{value}"),
                    value=value,
                    default=bool(profile and value in profile["reminders"]),
                )
                for value in REMINDERS
            ],
        )
        self.upload = discord.ui.FileUpload(required=False, min_values=0, max_values=1)
        for text, component in [
            ("setup.date", self.birthday),
            ("setup.timezone", self.timezone),
            ("setup.reminders", self.reminders),
        ]:
            self.add_item(discord.ui.Label(text=t(text), component=component))
        self.add_item(
            discord.ui.Label(
                text=t("setup.video"),
                description=t("setup.video_hint"),
                component=self.upload,
            )
        )

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message(t("error.owner"), ephemeral=True)
            return
        try:
            if not re.fullmatch(r"\d{1,2}/\d{1,2}", self.birthday.value.strip()):
                raise ValueError
            day, month = map(int, self.birthday.value.strip().split("/"))
            date(2000, month, day)
        except ValueError:
            await interaction.response.send_message(t("error.date"), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        data, filename = None, None
        if self.upload.values:
            attachment = self.upload.values[0]
            try:
                extension = validate_metadata(
                    attachment.filename, attachment.size, attachment.content_type
                )
                data = await attachment.read()
                validate_video(data, extension)
                filename = f"birthday{extension}"
            except ValueError as error:
                await interaction.followup.send(t(str(error)), ephemeral=True)
                return
        await self.bot.db.save_profile(
            self.guild_id,
            self.user_id,
            month,
            day,
            self.timezone.values[0],
            list(self.reminders.values),
            data,
            filename,
        )
        content, view = await dashboard(self.bot, self.guild_id, self.user_id)
        await interaction.followup.send(content, view=view, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await report_error(interaction, error)


class OwnedView(discord.ui.View):
    def __init__(self, bot, guild_id: int, user_id: int):
        super().__init__(timeout=600)
        self.bot, self.guild_id, self.user_id = bot, guild_id, user_id

    async def interaction_check(self, interaction: discord.Interaction):
        allowed = interaction.user.id == self.user_id and interaction.guild_id == self.guild_id
        if not allowed:
            await interaction.response.send_message(t("error.owner"), ephemeral=True)
        return allowed

    async def on_error(self, interaction, error, item):
        await report_error(interaction, error)


class Dashboard(OwnedView):
    def __init__(self, bot, guild_id: int, user_id: int, profile: dict):
        super().__init__(bot, guild_id, user_id)
        self.toggle.label = t("action.pause" if profile["enabled"] else "action.resume")
        self.remove_media.disabled = not bool(profile["video_name"])
        self.restore.disabled = profile["skip_date"] is None

    async def refresh(self, interaction):
        content, view = await dashboard(self.bot, self.guild_id, self.user_id)
        await interaction.edit_original_response(content=content, view=view)

    @discord.ui.button(label=t("action.edit"), style=discord.ButtonStyle.primary)
    async def edit(self, interaction, button):
        profile = await self.bot.db.get_profile(self.guild_id, self.user_id)
        await interaction.response.send_modal(
            BirthdayModal(self.bot, self.guild_id, self.user_id, profile)
        )

    @discord.ui.button(label=t("action.preview"))
    async def preview(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        profile = await self.bot.db.get_profile(self.guild_id, self.user_id, media=True)
        if profile is None:
            await interaction.followup.send(t("error.missing"), ephemeral=True)
            return
        if profile["video"] and len(profile["video"]) > interaction.filesize_limit:
            await interaction.followup.send(t("error.video_limit"), ephemeral=True)
            return
        embed = discord.Embed(
            title=t("preview.title"),
            description=t("post.birthday", mention=interaction.user.mention),
        )
        embed.set_footer(text=t("preview.footer"))
        file = video_file(profile)
        await interaction.followup.send(
            embed=embed,
            files=[file] if file else [],
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(label=t("action.pause"))
    async def toggle(self, interaction, button):
        await interaction.response.defer()
        profile = await self.bot.db.get_profile(self.guild_id, self.user_id)
        if profile:
            await self.bot.db.set_enabled(self.guild_id, self.user_id, not profile["enabled"])
        await self.refresh(interaction)

    @discord.ui.button(label=t("action.skip"), row=1)
    async def skip(self, interaction, button):
        await interaction.response.defer()
        profile = await self.bot.db.get_profile(self.guild_id, self.user_id)
        if profile:
            birthday = upcoming_birthday(
                profile["month"], profile["day"], profile["timezone"], datetime.now(UTC)
            )
            await self.bot.db.skip(self.guild_id, self.user_id, birthday)
        await self.refresh(interaction)

    @discord.ui.button(label=t("action.unskip"), row=1)
    async def restore(self, interaction, button):
        await interaction.response.defer()
        await self.bot.db.skip(self.guild_id, self.user_id, None)
        await self.refresh(interaction)

    @discord.ui.button(label=t("action.remove_video"), row=2)
    async def remove_media(self, interaction, button):
        await interaction.response.defer()
        await self.bot.db.remove_video(self.guild_id, self.user_id)
        await self.refresh(interaction)

    @discord.ui.button(label=t("action.remove"), style=discord.ButtonStyle.danger, row=2)
    async def remove(self, interaction, button):
        await interaction.response.edit_message(
            content=t("confirm.remove"), view=ConfirmRemoval(self.bot, self.guild_id, self.user_id)
        )


class ConfirmRemoval(OwnedView):
    @discord.ui.button(label=t("action.confirm_remove"), style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        await interaction.response.defer()
        await self.bot.db.remove(self.guild_id, self.user_id)
        await interaction.edit_original_response(content=t("result.removed"), view=None)

    @discord.ui.button(label=t("action.cancel"))
    async def cancel(self, interaction, button):
        await interaction.response.edit_message(content=t("result.cancelled"), view=None)


class NoticeButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"birthday:(?P<action>skip|pause):(?P<guild>\d+):(?P<user>\d+):(?P<date>\d{4}-\d{2}-\d{2})",
):
    def __init__(self, action: str, guild_id: int, user_id: int, birthday: date):
        self.action, self.guild_id, self.user_id, self.birthday = (
            action,
            guild_id,
            user_id,
            birthday,
        )
        super().__init__(
            discord.ui.Button(
                label=t("action.skip_notice" if action == "skip" else "action.pause"),
                custom_id=f"birthday:{action}:{guild_id}:{user_id}:{birthday.isoformat()}",
                style=discord.ButtonStyle.secondary,
            )
        )

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(
            match["action"],
            int(match["guild"]),
            int(match["user"]),
            date.fromisoformat(match["date"]),
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            if interaction.user.id != self.user_id:
                await interaction.response.send_message(t("error.owner"), ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True, thinking=True)
            db = interaction.client.db
            profile = await db.get_profile(self.guild_id, self.user_id)
            if profile is None:
                await interaction.followup.send(t("error.missing"), ephemeral=True)
                return
            event = events_for_year(
                profile["month"], profile["day"], profile["timezone"], [], self.birthday.year
            )[0]
            if event.birthday != self.birthday or event.due_at <= datetime.now(UTC):
                await interaction.followup.send(t("error.expired"), ephemeral=True)
                return
            if self.action == "skip":
                await db.skip(self.guild_id, self.user_id, self.birthday)
                content = t("result.skipped", date=self.birthday.isoformat())
            else:
                await db.set_enabled(self.guild_id, self.user_id, False)
                content = t("result.paused")
            await interaction.followup.send(content, ephemeral=True)
        except Exception as error:
            await report_error(interaction, error)


def notice_view(profile: dict, birthday: date):
    view = discord.ui.View(timeout=None)
    for action in ("skip", "pause"):
        view.add_item(NoticeButton(action, profile["guild_id"], profile["user_id"], birthday))
    return view


def channel_usable(channel, member) -> bool:
    if not isinstance(channel, discord.TextChannel) or member is None:
        return False
    permissions = channel.permissions_for(member)
    return all(
        (
            permissions.view_channel,
            permissions.send_messages,
            permissions.attach_files,
            permissions.embed_links,
        )
    )


def register_commands(bot):
    @bot.tree.command(name="birthday", description=t("command.birthday"))
    @app_commands.guild_only()
    @app_commands.describe(timezone=t("command.timezone_option"))
    async def birthday(interaction: discord.Interaction, timezone: str | None = None):
        profile = await bot.db.get_profile(interaction.guild_id, interaction.user.id)
        if profile is None:
            await interaction.response.send_modal(
                BirthdayModal(bot, interaction.guild_id, interaction.user.id)
            )
        else:
            if timezone is not None:
                try:
                    ZoneInfo(timezone)
                except (ZoneInfoNotFoundError, ValueError):
                    await interaction.response.send_message(t("error.timezone"), ephemeral=True)
                    return
                await bot.db.set_timezone(interaction.guild_id, interaction.user.id, timezone)
            await interaction.response.defer(ephemeral=True)
            content, view = await dashboard(bot, interaction.guild_id, interaction.user.id)
            await interaction.followup.send(content, view=view, ephemeral=True)

    @birthday.autocomplete("timezone")
    async def birthday_timezone(interaction: discord.Interaction, current: str):
        return timezone_choices(current)

    admin = app_commands.Group(
        name="birthday-admin",
        description=t("command.admin"),
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @admin.command(name="channel", description=t("command.channel"))
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(channel=t("command.channel_option"))
    async def channel(interaction: discord.Interaction, channel: discord.TextChannel):
        if channel.guild.id != interaction.guild_id or not channel_usable(
            channel, interaction.guild.me
        ):
            await interaction.response.send_message(t("error.channel"), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await bot.db.configure(interaction.guild_id, channel_id=channel.id)
        await interaction.followup.send(
            t("result.channel", channel=channel.mention), ephemeral=True
        )

    @admin.command(name="enabled", description=t("command.enabled"))
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(enabled=t("command.enabled_option"))
    async def enabled(interaction: discord.Interaction, enabled: bool):
        await interaction.response.defer(ephemeral=True)
        settings = await bot.db.settings(interaction.guild_id)
        if enabled and (not settings or not settings["channel_id"]):
            await interaction.followup.send(t("error.no_channel"), ephemeral=True)
            return
        await bot.db.configure(interaction.guild_id, enabled=enabled)
        await interaction.followup.send(
            t("result.enabled", state=t("state.active" if enabled else "state.paused")),
            ephemeral=True,
        )

    bot.tree.add_command(admin)
