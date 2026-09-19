from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

from birthdaybot.calendar import Event
from birthdaybot.scheduler import Scheduler


@pytest.fixture
def delivery(monkeypatch):
    profile = {
        "guild_id": 1,
        "user_id": 2,
        "month": 5,
        "day": 1,
        "timezone": "UTC",
        "reminders": [],
        "enabled": True,
        "skip_date": None,
        "video": b"video",
        "video_name": "birthday.mp4",
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    channel = SimpleNamespace(send=AsyncMock())
    guild = SimpleNamespace(
        id=1,
        name="Test",
        unavailable=False,
        me=object(),
        fetch_member=AsyncMock(),
        get_channel=Mock(return_value=channel),
    )
    member = SimpleNamespace(guild=guild, id=2, mention="<@2>", send=AsyncMock())
    guild.fetch_member.return_value = member
    db = SimpleNamespace(
        membership=AsyncMock(),
        get_profile=AsyncMock(return_value=profile.copy()),
        claim=AsyncMock(return_value=True),
        finish=AsyncMock(),
    )
    bot = SimpleNamespace(
        db=db, get_guild=Mock(return_value=guild), is_ready=Mock(return_value=True)
    )
    event = Event("birthday", date(2027, 5, 1), datetime(2027, 5, 1, 12, tzinfo=UTC))
    monkeypatch.setattr("birthdaybot.scheduler.channel_usable", lambda *_: True)
    monkeypatch.setattr("birthdaybot.scheduler.due_events", lambda *_: [event])
    return Scheduler(bot), profile, event, {"channel_id": 3}, guild, member, channel


async def test_birthday_attaches_video_and_mentions_only_member(delivery):
    scheduler, profile, event, settings, guild, member, channel = delivery
    await scheduler.deliver(profile, event, settings)
    scheduler.bot.db.claim.assert_awaited_once_with(profile, event, settings["channel_id"])
    kwargs = channel.send.call_args.kwargs
    assert kwargs["files"][0].filename == "birthday.mp4"
    assert kwargs["allowed_mentions"].users == [member]
    assert not kwargs["allowed_mentions"].everyone
    scheduler.bot.db.finish.assert_awaited_once_with(profile, event, "sent")


async def test_departed_member_is_never_announced(delivery):
    scheduler, profile, event, settings, guild, member, channel = delivery
    guild.fetch_member.side_effect = discord.NotFound(
        SimpleNamespace(status=404, reason="Not Found"), "missing"
    )
    await scheduler.deliver(profile, event, settings)
    channel.send.assert_not_awaited()
    scheduler.bot.db.claim.assert_not_awaited()
    scheduler.bot.db.membership.assert_awaited_once_with(1, 2, False)


async def test_failed_membership_lookup_does_not_mark_departure(delivery):
    scheduler, profile, event, settings, guild, member, channel = delivery
    guild.fetch_member.side_effect = discord.Forbidden(
        SimpleNamespace(status=403, reason="Forbidden"), "forbidden"
    )
    with pytest.raises(discord.Forbidden):
        await scheduler.deliver(profile, event, settings)
    scheduler.bot.db.membership.assert_not_awaited()
    channel.send.assert_not_awaited()


async def test_duplicate_claim_does_not_send(delivery):
    scheduler, profile, event, settings, guild, member, channel = delivery
    scheduler.bot.db.claim.return_value = False
    await scheduler.deliver(profile, event, settings)
    channel.send.assert_not_awaited()


async def test_edited_settings_do_not_send_stale_event(delivery):
    scheduler, profile, event, settings, guild, member, channel = delivery
    scheduler.bot.db.get_profile.return_value["updated_at"] = datetime(2027, 1, 1, tzinfo=UTC)
    await scheduler.deliver(profile, event, settings)
    scheduler.bot.db.claim.assert_not_awaited()


async def test_blocked_dm_records_failure(delivery, monkeypatch):
    scheduler, profile, event, settings, guild, member, channel = delivery
    notice = Event("notice", event.birthday, event.due_at)
    monkeypatch.setattr("birthdaybot.scheduler.due_events", lambda *_: [notice])
    member.send.side_effect = discord.Forbidden(
        SimpleNamespace(status=403, reason="Forbidden"), "blocked"
    )
    with pytest.raises(discord.Forbidden):
        await scheduler.deliver(profile, notice, settings)
    scheduler.bot.db.finish.assert_awaited_once_with(profile, notice, "failed")
    monkeypatch.setattr("birthdaybot.scheduler.due_events", lambda *_: [event])
    await scheduler.deliver(profile, event, settings)
    channel.send.assert_awaited_once()


async def test_disconnected_client_does_not_audit(delivery):
    scheduler = delivery[0]
    scheduler.bot.is_ready.return_value = False
    await scheduler.tick()
    scheduler.bot.db.membership.assert_not_awaited()
