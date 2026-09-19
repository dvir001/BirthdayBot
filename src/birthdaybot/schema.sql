CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT,
    enabled BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS birthdays (
    guild_id BIGINT NOT NULL REFERENCES guild_settings ON DELETE CASCADE,
    user_id BIGINT NOT NULL,
    month SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
    day SMALLINT NOT NULL CHECK (day BETWEEN 1 AND 31),
    timezone TEXT NOT NULL,
    reminders TEXT[] NOT NULL DEFAULT '{}'
        CHECK (reminders <@ ARRAY['day', 'week', 'month']::TEXT[]),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    skip_date DATE,
    left_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    video BYTEA CHECK (octet_length(video) <= 10000000),
    video_name TEXT,
    PRIMARY KEY (guild_id, user_id),
    CHECK (day <= EXTRACT(DAY FROM
        (make_date(2000, month, 1) + INTERVAL '1 month - 1 day')))
);

CREATE TABLE IF NOT EXISTS deliveries (
    guild_id BIGINT NOT NULL REFERENCES guild_settings ON DELETE CASCADE,
    user_id BIGINT NOT NULL,
    birthday DATE NOT NULL,
    kind TEXT NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'attempted',
    PRIMARY KEY (guild_id, user_id, birthday, kind)
);

CREATE INDEX IF NOT EXISTS birthdays_left_at ON birthdays (left_at)
    WHERE left_at IS NOT NULL;