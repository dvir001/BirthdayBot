import re
from datetime import date, time
from types import SimpleNamespace
from unittest.mock import AsyncMock

from birthdaybot.bot import BirthdayBot
from birthdaybot.ui import (
    REGION_PREFIXES,
    TIMEZONES,
    AnnouncementTimeModal,
    BirthdayModal,
    Dashboard,
    NoticeButton,
    TimezoneWizard,
    notice_view,
    region_timezones,
    timezone_groups,
)


async def test_modal_uses_native_labels_and_upload():
    modal = BirthdayModal(SimpleNamespace(max_media_bytes=5_000_000), 1, 2, 2)
    payload = modal.to_dict()
    assert len(payload["components"]) == 3
    assert all(component["type"] == 18 for component in payload["components"])
    assert payload["components"][-1]["component"]["type"] == 19
    assert payload["components"][-1]["label"] == "Birthday media (max 5,000,000 bytes)"
    assert payload["components"][1]["component"]["min_values"] == 0
    assert modal.timezone == "UTC"
    assert modal.announcement_time == time(12)


def test_timezone_wizard_covers_canonical_zones_within_discord_limits():
    covered = set()
    for region in REGION_PREFIXES:
        groups = timezone_groups(region)
        assert len(groups) <= 25
        assert all(len(zones) <= 25 for key, label, zones in groups)
        covered.update(region_timezones(region))
    assert covered == set(TIMEZONES)

    wizard = TimezoneWizard(None, 1, 2, 2, time(12))
    assert len(wizard.children[0].options) == len(REGION_PREFIXES)


def test_dashboard_has_combined_schedule_control():
    profile = {
        "enabled": True,
        "media_name": None,
        "skip_date": None,
    }
    controls = Dashboard(None, 1, 2, 2, profile).children
    labels = {item.label for item in controls}
    assert {"Edit birthday", "Edit schedule"} <= labels
    assert "Timezone" not in labels
    assert "Post time" not in labels
    assert [item.label for item in controls[:2]] == ["Edit birthday", "Edit schedule"]
    assert controls[0].row == controls[1].row
    pause = next(
        index for index, item in enumerate(controls) if item.label == "Pause participation"
    )
    assert controls[pause + 1].label == "Skip next birthday"
    assert controls[pause].row == controls[pause + 1].row == 1


def test_announcement_time_modal_defaults_to_saved_time():
    modal = AnnouncementTimeModal(None, 1, 2, 2, "Asia/Jerusalem", time(18, 30))
    assert modal.timezone == "Asia/Jerusalem"
    assert modal.value.default == "18:30"


async def test_schedule_modal_saves_timezone_and_time_together(monkeypatch):
    db = SimpleNamespace(set_schedule=AsyncMock())
    bot = SimpleNamespace(db=db)
    modal = AnnouncementTimeModal(bot, 1, 2, 3, "America/Phoenix", time(12))
    modal.value._value = "18:30"
    interaction = SimpleNamespace(
        guild_id=1,
        user=SimpleNamespace(id=3),
        response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    refreshed = AsyncMock(return_value=("dashboard", None))
    monkeypatch.setattr("birthdaybot.ui.dashboard", refreshed)

    await modal.on_submit(interaction)

    db.set_schedule.assert_awaited_once_with(1, 2, "America/Phoenix", time(18, 30))
    refreshed.assert_awaited_once_with(bot, 1, 2, 3)


async def test_notice_is_persistent_and_restores():
    view = notice_view({"guild_id": 1, "user_id": 2}, date(2027, 1, 1))
    assert view.is_persistent()
    item = view.children[0]
    assert len(item.custom_id) <= 100
    match = re.fullmatch(NoticeButton.__discord_ui_compiled_template__, item.custom_id)
    restored = await NoticeButton.from_custom_id(None, item, match)
    assert restored.guild_id == 1
    assert restored.user_id == 2
    assert restored.birthday == date(2027, 1, 1)


async def test_notice_rejects_other_users():
    interaction = SimpleNamespace(user=SimpleNamespace(id=3), response=AsyncMock())
    button = NoticeButton("skip", 1, 2, date(2027, 1, 1))
    await button.callback(interaction)
    interaction.response.send_message.assert_awaited_once()


async def test_commands_register_without_login():
    bot = BirthdayBot("postgresql://localhost/test")
    assert {command.name for command in bot.tree.get_commands()} == {"birthday", "birthday-admin"}
    assert not bot.intents.members
    assert not bot.intents.message_content
    assert len(bot.tree.get_command("birthday-admin").commands) == 2
    await bot.close()


async def test_admin_can_open_default_setup_for_another_member():
    bot = BirthdayBot("postgresql://localhost/test")
    bot.db = SimpleNamespace(get_profile=AsyncMock(return_value=None), close=AsyncMock())
    response = SimpleNamespace(send_modal=AsyncMock(), send_message=AsyncMock())
    admin = SimpleNamespace(id=2, guild_permissions=SimpleNamespace(manage_guild=True))
    target = SimpleNamespace(id=3)
    interaction = SimpleNamespace(guild_id=1, user=admin, response=response)

    await bot.tree.get_command("birthday").callback(interaction, target)

    modal = response.send_modal.await_args.args[0]
    assert (modal.user_id, modal.operator_id) == (3, 2)
    assert (modal.timezone, modal.announcement_time) == ("UTC", time(12))
    await bot.close()


async def test_non_admin_cannot_manage_another_member():
    bot = BirthdayBot("postgresql://localhost/test")
    bot.db = SimpleNamespace(get_profile=AsyncMock(), close=AsyncMock())
    response = SimpleNamespace(send_modal=AsyncMock(), send_message=AsyncMock())
    user = SimpleNamespace(id=2, guild_permissions=SimpleNamespace(manage_guild=False))
    interaction = SimpleNamespace(guild_id=1, user=user, response=response)

    await bot.tree.get_command("birthday").callback(interaction, SimpleNamespace(id=3))

    response.send_message.assert_awaited_once()
    bot.db.get_profile.assert_not_awaited()
    await bot.close()


async def test_expired_notice_cannot_pause_new_settings():
    db = SimpleNamespace(
        get_profile=AsyncMock(
            return_value={
                "month": 1,
                "day": 1,
                "timezone": "UTC",
                "announcement_time": time(12),
            }
        ),
        set_enabled=AsyncMock(),
        skip=AsyncMock(),
    )
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=2),
        client=SimpleNamespace(db=db),
        response=AsyncMock(),
        followup=AsyncMock(),
    )
    await NoticeButton("pause", 1, 2, date(2001, 1, 1)).callback(interaction)
    db.set_enabled.assert_not_awaited()
    db.skip.assert_not_awaited()
