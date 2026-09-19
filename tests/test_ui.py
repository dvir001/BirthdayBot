import re
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

from birthdaybot.bot import BirthdayBot
from birthdaybot.ui import (
    REGION_PREFIXES,
    TIMEZONES,
    BirthdayModal,
    NoticeButton,
    TimezoneWizard,
    notice_view,
    region_timezones,
    timezone_groups,
)


async def test_modal_uses_native_labels_and_upload():
    modal = BirthdayModal(None, 1, 2, "Asia/Jerusalem")
    payload = modal.to_dict()
    assert len(payload["components"]) == 3
    assert all(component["type"] == 18 for component in payload["components"])
    assert payload["components"][-1]["component"]["type"] == 19
    assert payload["components"][1]["component"]["min_values"] == 0


def test_timezone_wizard_covers_canonical_zones_within_discord_limits():
    covered = set()
    for region in REGION_PREFIXES:
        groups = timezone_groups(region)
        assert len(groups) <= 25
        assert all(len(zones) <= 25 for key, label, zones in groups)
        covered.update(region_timezones(region))
    assert covered == set(TIMEZONES)

    wizard = TimezoneWizard(None, 1, 2)
    assert len(wizard.children[0].options) == len(REGION_PREFIXES)


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


async def test_expired_notice_cannot_pause_new_settings():
    db = SimpleNamespace(
        get_profile=AsyncMock(return_value={"month": 1, "day": 1, "timezone": "UTC"}),
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
