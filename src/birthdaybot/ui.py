import io
import logging
import re
from collections import defaultdict
from datetime import UTC, date, datetime, time
from importlib.resources import files
from zoneinfo import ZoneInfo

import discord
from discord import app_commands

from birthdaybot.calendar import REMINDERS, events_for_year, upcoming_birthday
from birthdaybot.i18n import t
from birthdaybot.media import (
    BYTES_PER_MB,
    DEFAULT_MAX_MEDIA_MB,
    validate_media,
    validate_metadata,
)

log = logging.getLogger(__name__)

REGION_PREFIXES = {
    "africa": ("Africa/",),
    "americas": ("America/",),
    "asia": ("Asia/",),
    "europe": ("Europe/",),
    "oceania": ("Australia/", "Pacific/"),
    "atlantic_indian": ("Atlantic/", "Indian/"),
    "polar": ("Antarctica/", "Arctic/"),
    "utc": (),
}


def canonical_timezones() -> tuple[str, ...]:
    table = files("tzdata.zoneinfo").joinpath("zone1970.tab").read_text(encoding="utf-8")
    records = (line for line in table.splitlines() if line and not line.startswith("#"))
    zones = {line.split("\t")[2] for line in records}
    return tuple(sorted(zones | {"UTC"}))


TIMEZONES = canonical_timezones()


def utc_offset(timezone: str) -> int:
    offset = datetime.now(UTC).astimezone(ZoneInfo(timezone)).utcoffset()
    return int(offset.total_seconds() // 60)


def offset_label(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    hours, minutes = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def location_label(timezone: str) -> str:
    return " / ".join(part.replace("_", " ") for part in timezone.split("/")[1:]) or "UTC"


def region_timezones(region: str) -> list[str]:
    if region == "utc":
        return ["UTC"]
    return [timezone for timezone in TIMEZONES if timezone.startswith(REGION_PREFIXES[region])]


def timezone_groups(region: str) -> list[tuple[str, str, list[str]]]:
    offsets = defaultdict(list)
    for timezone in region_timezones(region):
        offsets[utc_offset(timezone)].append(timezone)
    groups = []
    for offset, zones in sorted(offsets.items()):
        for index in range(0, len(zones), 25):
            chunk = zones[index : index + 25]
            locations = f"{location_label(chunk[0])} - {location_label(chunk[-1])}"
            groups.append(
                (f"{offset}:{index // 25}", f"({offset_label(offset)}) {locations}", chunk)
            )
    return groups


async def report_error(interaction: discord.Interaction, error: Exception):
    log.error("Interaction failed", exc_info=error)
    if interaction.response.is_done():
        await interaction.followup.send(t("error.generic"), ephemeral=True)
    else:
        await interaction.response.send_message(t("error.generic"), ephemeral=True)


def media_file(profile: dict) -> discord.File | None:
    if profile.get("media"):
        return discord.File(io.BytesIO(profile["media"]), filename=profile["media_name"])
    return None


async def dashboard(bot, guild_id: int, user_id: int, operator_id: int | None = None):
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
            announcement_time=profile["announcement_time"].strftime("%H:%M"),
            status=t("state.active" if profile["enabled"] else "state.paused"),
            reminders=reminders or t("state.none"),
            media=t("state.media" if profile["media_name"] else "state.none"),
            skip=profile["skip_date"] or t("state.none"),
            server=t(
                "state.active"
                if settings and settings["enabled"] and settings["channel_id"]
                else "state.server_disabled"
            ),
        )
    )
    return content, Dashboard(bot, guild_id, user_id, operator_id or user_id, profile)


class BirthdayModal(discord.ui.Modal):
    def __init__(self, bot, guild_id: int, user_id: int, operator_id: int, profile=None):
        super().__init__(title=t("setup.title"), timeout=600)
        self.bot, self.guild_id, self.user_id, self.operator_id = (
            bot,
            guild_id,
            user_id,
            operator_id,
        )
        self.max_media_mb = getattr(bot, "max_media_mb", DEFAULT_MAX_MEDIA_MB)
        self.max_media_bytes = self.max_media_mb * BYTES_PER_MB
        self.timezone = profile["timezone"] if profile else "UTC"
        self.announcement_time = profile["announcement_time"] if profile else time(12)
        self.birthday = discord.ui.TextInput(
            placeholder=t("setup.date_placeholder"),
            min_length=3,
            max_length=5,
            default=f"{profile['day']:02d}/{profile['month']:02d}" if profile else None,
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
            ("setup.reminders", self.reminders),
        ]:
            self.add_item(discord.ui.Label(text=t(text), component=component))
        self.add_item(
            discord.ui.Label(
                text=t("setup.media", max_media_mb=self.max_media_mb),
                description=t("setup.media_hint"),
                component=self.upload,
            )
        )

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.operator_id or interaction.guild_id != self.guild_id:
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
                    attachment.filename,
                    attachment.size,
                    attachment.content_type,
                    self.max_media_bytes,
                )
                data = await attachment.read()
                validate_media(data, extension, self.max_media_bytes)
                filename = f"birthday-media{extension}"
            except ValueError as error:
                await interaction.followup.send(
                    t(str(error), max_media_mb=self.max_media_mb), ephemeral=True
                )
                return
        await self.bot.db.save_profile(
            self.guild_id,
            self.user_id,
            month,
            day,
            self.timezone,
            list(self.reminders.values),
            data,
            filename,
            self.announcement_time,
        )
        content, view = await dashboard(self.bot, self.guild_id, self.user_id, self.operator_id)
        await interaction.followup.send(content, view=view, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await report_error(interaction, error)


class AnnouncementTimeModal(discord.ui.Modal):
    def __init__(
        self,
        bot,
        guild_id: int,
        user_id: int,
        operator_id: int,
        timezone: str,
        current: time,
    ):
        super().__init__(title=t("time.title"), timeout=600)
        self.bot, self.guild_id, self.user_id, self.operator_id = (
            bot,
            guild_id,
            user_id,
            operator_id,
        )
        self.timezone = timezone
        self.value = discord.ui.TextInput(
            label=t("time.label"),
            placeholder=t("time.placeholder"),
            default=current.strftime("%H:%M"),
            min_length=5,
            max_length=5,
        )
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id != self.operator_id or interaction.guild_id != self.guild_id:
            await interaction.response.send_message(t("error.owner"), ephemeral=True)
            return
        try:
            announcement_time = time.fromisoformat(self.value.value)
        except ValueError:
            await interaction.response.send_message(t("error.time"), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await self.bot.db.set_schedule(
            self.guild_id, self.user_id, self.timezone, announcement_time
        )
        content, view = await dashboard(self.bot, self.guild_id, self.user_id, self.operator_id)
        await interaction.followup.send(content, view=view, ephemeral=True)


class OwnedView(discord.ui.View):
    def __init__(self, bot, guild_id: int, user_id: int, operator_id: int):
        super().__init__(timeout=600)
        self.bot, self.guild_id, self.user_id, self.operator_id = (
            bot,
            guild_id,
            user_id,
            operator_id,
        )

    async def interaction_check(self, interaction: discord.Interaction):
        allowed = interaction.user.id == self.operator_id and interaction.guild_id == self.guild_id
        if not allowed:
            await interaction.response.send_message(t("error.owner"), ephemeral=True)
        return allowed

    async def on_error(self, interaction, error, item):
        await report_error(interaction, error)


class WizardSelect(discord.ui.Select):
    def __init__(self, step: str, **kwargs):
        super().__init__(**kwargs)
        self.step = step

    async def callback(self, interaction: discord.Interaction):
        await self.view.choose(interaction, self.step, self.values[0])


class TimezoneWizard(OwnedView):
    def __init__(self, bot, guild_id: int, user_id: int, operator_id: int, current_time: time):
        super().__init__(bot, guild_id, user_id, operator_id)
        self.current_time = current_time
        self.region = None
        self.group = None
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        self.add_item(
            WizardSelect(
                "region",
                placeholder=t("setup.region_placeholder"),
                options=[
                    discord.SelectOption(
                        label=t(f"region.{region}"),
                        value=region,
                        default=region == self.region,
                    )
                    for region in REGION_PREFIXES
                ],
            )
        )
        if self.region is None:
            return
        groups = timezone_groups(self.region)
        self.add_item(
            WizardSelect(
                "subregion",
                placeholder=t("setup.subregion_placeholder"),
                options=[self.subregion_option(key, label) for key, label, zones in groups],
            )
        )
        selected_group = next((group for group in groups if group[0] == self.group), None)
        if selected_group is None:
            return
        self.add_item(
            WizardSelect(
                "timezone",
                placeholder=t("setup.timezone_placeholder"),
                options=[
                    discord.SelectOption(
                        label=f"({offset_label(utc_offset(timezone))}) {location_label(timezone)}"[
                            :100
                        ],
                        value=timezone,
                        description=timezone,
                    )
                    for timezone in selected_group[2]
                ],
            )
        )

    def subregion_option(self, key: str, label: str) -> discord.SelectOption:
        return discord.SelectOption(label=label[:100], value=key, default=key == self.group)

    async def choose(self, interaction: discord.Interaction, step: str, value: str):
        if step == "timezone":
            await interaction.response.send_modal(
                AnnouncementTimeModal(
                    self.bot,
                    self.guild_id,
                    self.user_id,
                    self.operator_id,
                    value,
                    self.current_time,
                )
            )
            return
        if step == "region":
            self.region, self.group = value, None
        else:
            self.group = value
        self.rebuild()
        await interaction.response.edit_message(content=t("setup.timezone_prompt"), view=self)


class Dashboard(OwnedView):
    def __init__(self, bot, guild_id: int, user_id: int, operator_id: int, profile: dict):
        super().__init__(bot, guild_id, user_id, operator_id)
        self.toggle.label = t("action.pause" if profile["enabled"] else "action.resume")
        self.remove_media.disabled = not bool(profile["media_name"])
        self.restore.disabled = profile["skip_date"] is None

    async def refresh(self, interaction):
        content, view = await dashboard(self.bot, self.guild_id, self.user_id, self.operator_id)
        await interaction.edit_original_response(content=content, view=view)

    @discord.ui.button(label=t("action.edit"), style=discord.ButtonStyle.primary)
    async def edit(self, interaction, button):
        profile = await self.bot.db.get_profile(self.guild_id, self.user_id)
        await interaction.response.send_modal(
            BirthdayModal(self.bot, self.guild_id, self.user_id, self.operator_id, profile)
        )

    @discord.ui.button(label=t("action.schedule"))
    async def schedule(self, interaction, button):
        profile = await self.bot.db.get_profile(self.guild_id, self.user_id)
        await interaction.response.edit_message(
            content=t("setup.timezone_prompt"),
            view=TimezoneWizard(
                self.bot,
                self.guild_id,
                self.user_id,
                self.operator_id,
                profile["announcement_time"],
            ),
        )

    @discord.ui.button(label=t("action.preview"))
    async def preview(self, interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        profile = await self.bot.db.get_profile(self.guild_id, self.user_id, media=True)
        if profile is None:
            await interaction.followup.send(t("error.missing"), ephemeral=True)
            return
        if profile["media"] and len(profile["media"]) > interaction.filesize_limit:
            await interaction.followup.send(t("error.media_limit"), ephemeral=True)
            return
        embed = discord.Embed(
            title=t("preview.title"),
            description=t("post.birthday", mention=f"<@{self.user_id}>"),
        )
        embed.set_footer(text=t("preview.footer"))
        file = media_file(profile)
        await interaction.followup.send(
            embed=embed,
            files=[file] if file else [],
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(label=t("action.pause"), row=1)
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
                profile["month"],
                profile["day"],
                profile["timezone"],
                datetime.now(UTC),
                profile["announcement_time"],
            )
            await self.bot.db.skip(self.guild_id, self.user_id, birthday)
        await self.refresh(interaction)

    @discord.ui.button(label=t("action.unskip"), row=1)
    async def restore(self, interaction, button):
        await interaction.response.defer()
        await self.bot.db.skip(self.guild_id, self.user_id, None)
        await self.refresh(interaction)

    @discord.ui.button(label=t("action.remove_media"), row=2)
    async def remove_media(self, interaction, button):
        await interaction.response.defer()
        await self.bot.db.remove_media(self.guild_id, self.user_id)
        await self.refresh(interaction)

    @discord.ui.button(label=t("action.remove"), style=discord.ButtonStyle.danger, row=2)
    async def remove(self, interaction, button):
        await interaction.response.edit_message(
            content=t("confirm.remove"),
            view=ConfirmRemoval(self.bot, self.guild_id, self.user_id, self.operator_id),
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
                profile["month"],
                profile["day"],
                profile["timezone"],
                [],
                self.birthday.year,
                profile["announcement_time"],
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
    @app_commands.describe(user=t("command.user_option"))
    async def birthday(interaction: discord.Interaction, user: discord.Member | None = None):
        target = user or interaction.user
        if target.id != interaction.user.id and not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(t("error.permissions"), ephemeral=True)
            return
        profile = await bot.db.get_profile(interaction.guild_id, target.id)
        if profile is None:
            await interaction.response.send_modal(
                BirthdayModal(bot, interaction.guild_id, target.id, interaction.user.id)
            )
        else:
            await interaction.response.defer(ephemeral=True)
            content, view = await dashboard(
                bot, interaction.guild_id, target.id, interaction.user.id
            )
            await interaction.followup.send(content, view=view, ephemeral=True)

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
