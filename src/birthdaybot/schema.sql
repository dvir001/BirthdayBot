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
    announcement_time TIME NOT NULL DEFAULT '12:00',
    reminders TEXT[] NOT NULL DEFAULT '{}'
        CHECK (reminders <@ ARRAY['day', 'week', 'month']::TEXT[]),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    skip_date DATE,
    left_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    media BYTEA,
    media_name TEXT,
    PRIMARY KEY (guild_id, user_id),
    CHECK (day <= EXTRACT(DAY FROM
        (make_date(2000, month, 1) + INTERVAL '1 month - 1 day')))
);

ALTER TABLE birthdays
    ADD COLUMN IF NOT EXISTS announcement_time TIME NOT NULL DEFAULT '12:00';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'birthdays'
            AND column_name = 'video'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'birthdays'
            AND column_name = 'media'
    ) THEN
        ALTER TABLE birthdays RENAME COLUMN video TO media;
        ALTER TABLE birthdays RENAME COLUMN video_name TO media_name;
    END IF;
END $$;

ALTER TABLE birthdays DROP CONSTRAINT IF EXISTS birthdays_media_check;
ALTER TABLE birthdays DROP CONSTRAINT IF EXISTS birthdays_video_check;

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