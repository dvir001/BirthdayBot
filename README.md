# BirthdayBot

A Python Discord bot with server-scoped birthdays, timezone-aware scheduling,
native Discord forms, and PostgreSQL storage. Licensed under MIT.

## Commands

- `/birthday`: opens setup with a dropdown of 25 common timezones for new users;
  otherwise opens a private dashboard with configuration, edit, preview,
  pause/resume, skip, and removal. Existing users can search every IANA timezone
  with the optional `/birthday timezone:<search>` argument.
- `/birthday-admin channel`: sets the server's birthday text channel.
- `/birthday-admin enabled`: enables or disables all scheduling for the server.
  Both administrator commands require Manage Server at runtime.

Birthdays use day/month only. Announcements and selected day/week/month reminders
are scheduled at 12:00 in the member's IANA timezone. The bot checks every minute
and catches up only within ten minutes of a scheduled time. February 29 falls on
February 28 in non-leap years; a month-before reminder clamps to the last valid
day of the previous month. DST follows the installed IANA timezone database.

Three hours before the birthday post, a private message offers persistent buttons
to skip that occurrence or pause participation. Blocked DMs do not prevent the
public announcement. Skipping also suppresses remaining reminders for that
occurrence; pausing suppresses all events until resumed. Tests are private previews
and do not consume scheduled deliveries.

Optional videos are limited to 10,000,000 bytes (10 MB), stored in PostgreSQL,
and attached to birthday posts. MP4/MOV, WebM/MKV, AVI, MPEG, and Ogg video
containers are supported with extension, MIME, and header checks. This is not
transcoding or malware scanning; administrators should treat uploads as untrusted.
An empty upload during editing preserves the current video; use Remove Video to
delete it. Removing a birthday deletes its settings, media, and delivery history.

Membership is checked directly with Discord before every scheduled delivery,
including private notices. Missing members are never announced. An hourly audit
also checks paused users and disabled servers. Departed members' settings/media
are retained for one calendar year from detected departure, then deleted. Rejoining
before deletion restores the stored configuration. No message-content or privileged
member intent is needed. Scheduled delivery attempts are claimed durably before
sending: this prevents duplicate retries, but a crash or ambiguous network failure
between claim and send can lose that event. Failed attempts are logged and are not
automatically retried. Run one bot instance; PostgreSQL also serializes schedulers.

## Setup

Create an application and bot in the Discord Developer Portal. Install it in a
server using the `bot` and `applications.commands` scopes. Grant View Channel,
Send Messages, Attach Files, and Embed Links in the birthday channel. Privileged
intents are not required. Keep the bot token private.

Python 3.11+ and PostgreSQL 18 are supported. Install [uv](https://docs.astral.sh/uv/),
then run `uv sync --locked`. Set `DISCORD_TOKEN` and `DATABASE_URL` in the process
environment, or copy `.env.example` to `.env` and use:

```sh
uv run --env-file .env birthdaybot
```

For local execution, change the database hostname from `birthdaybot-db` to the
hostname of your PostgreSQL instance. No Docker installation is required on a development
machine. Set optional `DISCORD_TEST_GUILD_ID` for immediate development command
registration in one server; otherwise commands are registered globally and may
take time to propagate. Production should leave this unset. The bot creates its
initial schema on startup. Back up the database before future schema upgrades.

In Discord, configure `/birthday-admin channel`, then `/birthday-admin enabled True`.
The bot starts disabled in each server until an administrator enables it.

## Deployment

The deployment Compose file uses a published image, not a local build. On a Docker
host, place `docker-compose.yml` and a configured `.env` together, then run:

```sh
docker compose pull
docker compose up -d
docker compose logs -f birthdaybot-app
```

Use a strong `POSTGRES_PASSWORD` and the same URL-encoded password in `DATABASE_URL`.
PostgreSQL is not exposed on a host port. The named volume contains settings,
videos, and delivery history; back it up with `pg_dump` and test restoration.
Do not run `docker compose down -v` unless you intend to erase all stored data.
Database major-version upgrades require a PostgreSQL migration, not just an image
tag change.

GitHub Actions tests pushes and pull requests, runs CodeQL, and publishes
`ghcr.io/dvir001/birthdaybot` for `linux/amd64` and `linux/arm64` after successful
checks on pushes to `main` and `v*` tags. Main publishes `latest` and SHA tags;
version tags publish SemVer tags. Set the GHCR package visibility to public after
its first publication, or authenticate the deployment host to pull private images.
Pin `BIRTHDAYBOT_IMAGE` to a release tag or digest for controlled upgrades.

No Discord secrets are needed in CI. Publishing uses GitHub's automatic token
with package-write permission. Enable GitHub Actions, dependency graph,
Dependabot alerts/security updates, secret scanning/push protection, and branch
protection for the CI check in repository settings as available for your account.
The repository includes Dependabot configuration for uv, Actions, Docker, and
Compose. Committing workflows alone does not enable repository-level settings.

## Development

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv build
```

Database integration tests run when `TEST_DATABASE_URL` points to a dedicated,
disposable PostgreSQL database. They are skipped otherwise. CI supplies this
database as a service. Never point integration tests at production.

User-facing text is centralized in `static/locales/en-US.json`. See `AGENTS.md`
for project conventions. Real `.env` files are ignored; `.env.example`, the
lockfile, and agent instructions are intentionally tracked.