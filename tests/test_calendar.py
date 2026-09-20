from datetime import UTC, date, datetime, time, timedelta

import pytest

from birthdaybot.calendar import birthday_in_year, due_events, events_for_year, previous_month


def test_leap_day():
    assert birthday_in_year(2, 29, 2027) == date(2027, 2, 28)
    assert birthday_in_year(2, 29, 2028) == date(2028, 2, 29)
    with pytest.raises(ValueError):
        birthday_in_year(4, 31, 2027)


def test_month_clamping():
    assert previous_month(date(2027, 3, 31)) == date(2027, 2, 28)
    assert previous_month(date(2028, 3, 31)) == date(2028, 2, 29)
    assert previous_month(date(2027, 1, 15)) == date(2026, 12, 15)


def test_dst_and_multiple_reminders():
    events = {
        event.kind: event
        for event in events_for_year(3, 15, "America/New_York", ["day", "week", "month"], 2027)
    }
    assert events["birthday"].due_at == datetime(2027, 3, 15, 16, tzinfo=UTC)
    assert events["week"].due_at == datetime(2027, 3, 8, 17, tzinfo=UTC)
    assert events["notice"].due_at == events["birthday"].due_at - timedelta(hours=3)
    assert len(events) == 5


def test_custom_announcement_time_and_noon_default():
    default = events_for_year(5, 1, "UTC", [], 2027)[0]
    custom = events_for_year(5, 1, "Asia/Jerusalem", [], 2027, time(18, 30))[0]
    assert default.due_at == datetime(2027, 5, 1, 12, tzinfo=UTC)
    assert custom.due_at == datetime(2027, 5, 1, 15, 30, tzinfo=UTC)


def test_cross_year_reminders_and_skip():
    profile = {
        "month": 1,
        "day": 1,
        "timezone": "UTC",
        "reminders": ["day"],
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
        "skip_date": None,
    }
    now = datetime(2026, 12, 31, 12, tzinfo=UTC)
    assert [event.kind for event in due_events(profile, now)] == ["day"]
    profile["skip_date"] = date(2027, 1, 1)
    assert due_events(profile, now) == []


def test_catchup_window_and_new_settings():
    now = datetime(2027, 5, 1, 12, tzinfo=UTC)
    profile = {
        "month": 5,
        "day": 1,
        "timezone": "UTC",
        "reminders": [],
        "updated_at": now - timedelta(days=1),
    }
    assert len(due_events(profile, now + timedelta(minutes=9))) == 1
    assert due_events(profile, now + timedelta(minutes=10)) == []
    profile["updated_at"] = now + timedelta(seconds=1)
    assert due_events(profile, now + timedelta(seconds=2)) == []
