import asyncio
import os
import uuid
from datetime import UTC, date, datetime, time

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from psycopg.conninfo import make_conninfo

from birthdaybot.calendar import Event
from birthdaybot.db import Database


@pytest_asyncio.fixture
async def db():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set")
    schema = "test_" + uuid.uuid4().hex
    connection = await psycopg.AsyncConnection.connect(url, autocommit=True)
    await connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    database = Database(make_conninfo(url, options=f"-c search_path={schema}"))
    try:
        await database.open()
        yield database
    finally:
        await database.close()
        await connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        await connection.close()


async def seed(db, guild_id=1):
    await db.save_profile(guild_id, 2, 5, 1, "UTC", ["day", "week"], b"video", "birthday.mp4")
    await db.configure(guild_id, channel_id=3, enabled=True)
    return await db.get_profile(guild_id, 2)


async def test_profile_isolation_media_and_pause(db):
    await seed(db)
    await seed(db, 4)
    await db.set_enabled(1, 2, False)
    await db.save_profile(1, 2, 6, 2, "Europe/London", [], None, None)
    profile = await db.get_profile(1, 2, media=True)
    assert profile["media"] == b"video"
    assert not profile["enabled"]
    assert profile["day"] == 2
    assert profile["announcement_time"] == time(12)
    await db.set_schedule(1, 2, "Asia/Jerusalem", time(18, 30))
    profile = await db.get_profile(1, 2)
    assert (profile["timezone"], profile["announcement_time"]) == (
        "Asia/Jerusalem",
        time(18, 30),
    )
    assert (await db.get_profile(4, 2))["day"] == 1
    await db.remove_media(1, 2)
    assert (await db.get_profile(1, 2, media=True))["media"] is None
    await db.remove(1, 2)
    assert await db.get_profile(1, 2) is None
    assert await db.get_profile(4, 2) is not None


async def test_atomic_claim_and_control_states(db):
    profile = await seed(db)
    event = Event("birthday", date(2027, 5, 1), datetime(2027, 5, 1, 12, tzinfo=UTC))
    assert not await db.claim(profile, event, 99)
    results = await asyncio.gather(db.claim(profile, event, 3), db.claim(profile, event, 3))
    assert sorted(results) == [False, True]
    reminder = Event("day", event.birthday, event.due_at)
    await db.skip(1, 2, event.birthday)
    assert not await db.claim(profile, reminder, 3)
    await db.skip(1, 2, None)
    await db.membership(1, 2, False)
    assert not await db.claim(profile, reminder, 3)
    await db.membership(1, 2, True)
    await db.configure(1, enabled=False)
    assert not await db.claim(profile, reminder, 3)
    await db.configure(1, enabled=True)
    await db.set_enabled(1, 2, False)
    assert not await db.claim(profile, reminder, 3)
    await db.set_enabled(1, 2, True)
    assert not await db.claim(profile, reminder, 3)
    profile = await db.get_profile(1, 2)
    await db.remove_media(1, 2)
    assert not await db.claim(profile, reminder, 3)
    profile = await db.get_profile(1, 2)
    assert await db.claim(profile, reminder, 3)


async def test_retention_and_rejoin(db):
    await seed(db)
    await seed(db, 4)
    await db.membership(1, 2, False)
    first_left = (await db.get_profile(1, 2))["left_at"]
    await db.membership(1, 2, False)
    assert (await db.get_profile(1, 2))["left_at"] == first_left
    await db.execute("UPDATE birthdays SET left_at = now() - INTERVAL '1 year 1 day'")
    await db.membership(4, 2, True)
    await db.cleanup()
    assert await db.get_profile(1, 2) is None
    assert (await db.get_profile(4, 2))["left_at"] is None
