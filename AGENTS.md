# AGENTS.md

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

## 5. i18n Rules

- Every user-visible string must have a key in `static/locales/en-US.json`.
- Use `birthdaybot.i18n.t(key, **values)` for Discord messages, labels, and command descriptions.
- Keep README and other documentation free of emojis.

## 6. BirthdayBot Conventions

- Python 3.11+; production uses Python 3.14, discord.py 2.7+, and PostgreSQL 18.
- Use `uv sync --locked` for installation. Commit `uv.lock` when dependencies change.
- Keep Discord UI in `ui.py`, calendar calculations in `calendar.py`, persistence in
	`db.py`/`schema.sql`, and scheduled delivery in `scheduler.py`.
- Use native application commands and modals; do not add a web frontend.
- Scope every birthday operation by both guild ID and user ID. Check ownership on
	component interactions and Manage Server permission at runtime for admin commands.
- Store day/month and IANA timezone, not a birth year. Schedule using aware UTC
	datetimes derived from local noon; preserve documented calendar and catch-up rules.
- Recheck membership before sending. Never mistake a transient Discord failure for
	a departure. Retain departed-member data for one year; user deletion is immediate.
- Claim deliveries before sending and preserve the documented at-most-once tradeoff.
- Keep videos in PostgreSQL with a strict 10,000,000-byte limit. Never trust filenames.
- Add explicit migration steps before changing an existing database schema; startup
	currently initializes version one's tables with idempotent DDL.
- Keep secrets out of logs, source, and images. Commit `.env.example`, never `.env`.
- Do not install or run Docker on the local development machine. Containers are for
	deployment hosts and CI only.

## 7. Verification

- Run `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest`.
- Run `uv build` after packaging or locale changes.
- Database tests use a unique temporary schema and require `TEST_DATABASE_URL` for
	a disposable PostgreSQL database. CI runs these tests; disclose local skips.
- Mock Discord HTTP boundaries in unit tests. Live smoke tests require a test server
	and a token supplied outside source control; never request secrets in chat.
- Deployment consumes the GHCR image. Preserve amd64/arm64 publication and least-
	privilege, commit-pinned GitHub Actions.
