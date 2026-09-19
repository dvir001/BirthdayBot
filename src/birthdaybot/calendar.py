from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

REMINDERS = ("day", "week", "month")


@dataclass(frozen=True)
class Event:
    kind: str
    birthday: date
    due_at: datetime


def birthday_in_year(month: int, day: int, year: int) -> date:
    date(2000, month, day)
    return date(year, month, min(day, monthrange(year, month)[1]))


def previous_month(value: date) -> date:
    year = value.year - (value.month == 1)
    month = value.month - 1 or 12
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def events_for_year(
    month: int, day: int, timezone: str, reminders: list[str], year: int
) -> list[Event]:
    zone = ZoneInfo(timezone)
    birthday = birthday_in_year(month, day, year)
    noon = datetime.combine(birthday, time(12), zone).astimezone(UTC)
    events = [
        Event("birthday", birthday, noon),
        Event("notice", birthday, noon - timedelta(hours=3)),
    ]
    for reminder in reminders:
        if reminder == "month":
            reminder_date = previous_month(birthday)
        elif reminder in ("day", "week"):
            reminder_date = birthday - timedelta(days=1 if reminder == "day" else 7)
        else:
            raise ValueError(f"Unknown reminder: {reminder}")
        due_at = datetime.combine(reminder_date, time(12), zone).astimezone(UTC)
        events.append(Event(reminder, birthday, due_at))
    return events


def upcoming_birthday(month: int, day: int, timezone: str, now: datetime) -> date:
    year = now.astimezone(ZoneInfo(timezone)).year
    for candidate in (year, year + 1):
        event = events_for_year(month, day, timezone, [], candidate)[0]
        if event.due_at > now:
            return event.birthday
    raise ValueError("No upcoming birthday")


def due_events(profile: dict, now: datetime) -> list[Event]:
    year = now.astimezone(ZoneInfo(profile["timezone"])).year
    events = []
    for candidate in (year, year + 1):
        for event in events_for_year(
            profile["month"], profile["day"], profile["timezone"], profile["reminders"], candidate
        ):
            if (
                event.birthday != profile.get("skip_date")
                and profile["updated_at"] <= event.due_at
                and event.due_at <= now < event.due_at + timedelta(minutes=10)
            ):
                events.append(event)
    return sorted(events, key=lambda event: event.due_at)
