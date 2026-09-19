from datetime import date
from importlib.resources import files

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

PROFILE_COLUMNS = """
    guild_id, user_id, month, day, timezone, reminders, enabled, skip_date,
    left_at, updated_at, video_name
"""


class Database:
    def __init__(self, url: str):
        self.pool = AsyncConnectionPool(
            url,
            min_size=1,
            max_size=5,
            open=False,
            kwargs={"autocommit": True, "row_factory": dict_row},
        )

    async def open(self):
        await self.pool.open(wait=True)
        async with self.pool.connection() as connection, connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock(481975001)")
            await connection.execute(files("birthdaybot").joinpath("schema.sql").read_text())

    async def close(self):
        await self.pool.close()

    async def execute(self, query: str, params: tuple = ()):
        async with self.pool.connection() as connection:
            return await connection.execute(query, params)

    async def get_profile(self, guild_id: int, user_id: int, *, media: bool = False):
        columns = "*" if media else PROFILE_COLUMNS
        cursor = await self.execute(
            f"SELECT {columns} FROM birthdays WHERE guild_id = %s AND user_id = %s",
            (guild_id, user_id),
        )
        return await cursor.fetchone()

    async def save_profile(
        self,
        guild_id: int,
        user_id: int,
        month: int,
        day: int,
        timezone: str,
        reminders: list[str],
        video: bytes | None,
        video_name: str | None,
    ):
        async with self.pool.connection() as connection, connection.transaction():
            await connection.execute(
                "INSERT INTO guild_settings (guild_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (guild_id,),
            )
            await connection.execute(
                """INSERT INTO birthdays
                    (guild_id, user_id, month, day, timezone, reminders, video, video_name)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (guild_id, user_id) DO UPDATE SET
                    month = EXCLUDED.month, day = EXCLUDED.day, timezone = EXCLUDED.timezone,
                    reminders = EXCLUDED.reminders,
                    video = COALESCE(EXCLUDED.video, birthdays.video),
                    video_name = COALESCE(EXCLUDED.video_name, birthdays.video_name),
                    left_at = NULL, updated_at = now()""",
                (guild_id, user_id, month, day, timezone, reminders, video, video_name),
            )

    async def set_enabled(self, guild_id: int, user_id: int, enabled: bool):
        await self.execute(
            """UPDATE birthdays SET enabled = %s, updated_at = now()
               WHERE guild_id = %s AND user_id = %s""",
            (enabled, guild_id, user_id),
        )

    async def set_timezone(self, guild_id: int, user_id: int, timezone: str):
        await self.execute(
            """UPDATE birthdays SET timezone = %s, updated_at = now()
               WHERE guild_id = %s AND user_id = %s""",
            (timezone, guild_id, user_id),
        )

    async def skip(self, guild_id: int, user_id: int, birthday: date | None):
        await self.execute(
            "UPDATE birthdays SET skip_date = %s WHERE guild_id = %s AND user_id = %s",
            (birthday, guild_id, user_id),
        )

    async def remove_video(self, guild_id: int, user_id: int):
        await self.execute(
            """UPDATE birthdays SET video = NULL, video_name = NULL, updated_at = now()
               WHERE guild_id = %s AND user_id = %s""",
            (guild_id, user_id),
        )

    async def remove(self, guild_id: int, user_id: int):
        async with self.pool.connection() as connection, connection.transaction():
            for table in ("birthdays", "deliveries"):
                await connection.execute(
                    f"DELETE FROM {table} WHERE guild_id = %s AND user_id = %s", (guild_id, user_id)
                )

    async def settings(self, guild_id: int):
        cursor = await self.execute("SELECT * FROM guild_settings WHERE guild_id = %s", (guild_id,))
        return await cursor.fetchone()

    async def configure(self, guild_id: int, *, channel_id=None, enabled=None):
        async with self.pool.connection() as connection, connection.transaction():
            await connection.execute(
                "INSERT INTO guild_settings (guild_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (guild_id,),
            )
            if channel_id is not None:
                await connection.execute(
                    "UPDATE guild_settings SET channel_id = %s WHERE guild_id = %s",
                    (channel_id, guild_id),
                )
            if enabled is not None:
                await connection.execute(
                    "UPDATE guild_settings SET enabled = %s WHERE guild_id = %s",
                    (enabled, guild_id),
                )

    async def profiles(self):
        cursor = await self.execute(f"SELECT {PROFILE_COLUMNS} FROM birthdays")
        return await cursor.fetchall()

    async def membership(self, guild_id: int, user_id: int, present: bool):
        await self.execute(
            """UPDATE birthdays SET left_at = CASE WHEN %s THEN NULL
               ELSE COALESCE(left_at, now()) END WHERE guild_id = %s AND user_id = %s""",
            (present, guild_id, user_id),
        )

    async def cleanup(self):
        async with self.pool.connection() as connection, connection.transaction():
            await connection.execute(
                """DELETE FROM deliveries USING birthdays WHERE
                   deliveries.guild_id = birthdays.guild_id
                   AND deliveries.user_id = birthdays.user_id
                   AND birthdays.left_at <= now() - INTERVAL '1 year'"""
            )
            await connection.execute(
                "DELETE FROM birthdays WHERE left_at <= now() - INTERVAL '1 year'"
            )
            await connection.execute(
                "DELETE FROM deliveries WHERE attempted_at < now() - INTERVAL '2 years'"
            )

    async def claim(self, profile: dict, event, channel_id: int) -> bool:
        cursor = await self.execute(
            """INSERT INTO deliveries (guild_id, user_id, birthday, kind)
               SELECT b.guild_id, b.user_id, %s, %s FROM birthdays b
               JOIN guild_settings g USING (guild_id)
               WHERE b.guild_id = %s AND b.user_id = %s AND b.enabled AND g.enabled
                 AND g.channel_id = %s AND b.left_at IS NULL
                 AND b.skip_date IS DISTINCT FROM %s AND b.updated_at = %s
               ON CONFLICT DO NOTHING RETURNING kind""",
            (
                event.birthday,
                event.kind,
                profile["guild_id"],
                profile["user_id"],
                channel_id,
                event.birthday,
                profile["updated_at"],
            ),
        )
        return await cursor.fetchone() is not None

    async def finish(self, profile: dict, event, status: str):
        await self.execute(
            """UPDATE deliveries SET status = %s
               WHERE guild_id = %s AND user_id = %s AND birthday = %s AND kind = %s""",
            (status, profile["guild_id"], profile["user_id"], event.birthday, event.kind),
        )
