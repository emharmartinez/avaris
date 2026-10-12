# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

- **Greenfield.** No code exists yet. The source of truth is `docs/plans/plan-for-this-first-snug-fox.md`: it holds the stack, design, layout and six phases, each with a "Done when". Read it before starting a phase.
- Avaris is a personal, single-user, local-only NBA betting model for moneyline, spread and total. Do not add accounts, auth, hosting, multi-tenancy or billing code.

## Commands

**Python** (uv, from repo root)

```
uv run ruff check
uv run pyright
uv run pytest                                  # all tests
uv run pytest tests/unit/test_devig.py::test_x # single test
uv run pytest -m e2e                           # pipeline E2E only
uv run avaris ...                              # Typer CLI (ingest, odds, daily, settle, serve)
```

**Web** (from `web/`; always pass `--cache "$TMPDIR/npm-cache"` to npm because of the sandbox)

```
npm run lint && npm run typecheck && npm run test && npm run build
npm run test:e2e                               # Playwright, against `avaris serve` on the fixture DB
npx vitest run path/to/file.test.tsx           # single unit test
```

All gates must be green at the end of every phase.

## Architecture

- **Data flow:**
  1. Ingest: `nba_api` stats, The Odds API odds and NBA injury reports go into a raw response cache and DuckDB.
  2. Point-in-time features.
  3. Models for `home_win`, `margin` and `total`.
  4. Betting layer: de-vig, model/market blend, edge, staking.
  5. Picks and bets are served by the FastAPI server and shown in the PWA.
- **Evaluation is against the de-vigged closing line**, not raw accuracy. Walk-forward only. The **2025-26 season is a holdout used once**; never tune on it.
- **Features must be as of tip-off.** The leakage test must hold: deleting rows after date D cannot change features for games on D.
- **Market odds are never a model feature.** They enter only through the betting-layer blend `p = w·model + (1−w)·market`.
- **Single DuckDB writer.**
  - The FastAPI process owns the read-write connection.
  - CLI jobs run in-process only when the server is down. Otherwise they go through `POST /api/jobs/{daily,settle}`.
  - The UI never calls external APIs.
- **Odds spend is guarded by `CreditGuard`.**
  - Every Odds API call is cost-estimated first and refused if it would break the per-run, monthly-credit, monthly-USD or reserve limits.
  - Every call is logged to the `api_usage` ledger.
  - Never bypass the guard or remove `--estimate` / `--confirm`.
- **Web** is Next.js App Router + shadcn/ui with `output: 'export'`. FastAPI serves the static `web/out`; there is no Node server at runtime. So: no server actions, no route handlers, all data is fetched client-side with TanStack Query, and dynamic segments need `generateStaticParams` (prefer query params). In dev, `next dev` calls FastAPI via `NEXT_PUBLIC_API_BASE`.

## Testing

- **TDD by default** for all deterministic code. Write the failing test first. Test-after is allowed only for exploratory model tuning and report styling.
- **No live network in tests.** Use recorded responses and the fixture DuckDB built by `tests/fixtures/`.
- **Vitest uses `node` by default.** Only `*.test.tsx` (component rendering, interaction, `renderHook`) runs in `jsdom`, because jsdom is slow. Put logic in plain `.ts` modules so it can be tested in `node`.
- **IMPORTANT**: Do not ignore E2E tests

## Environment constraints

- The sandbox blocks reading `.env.local` (Odds API key). Odds API commands and paid backfills are **user-run**: suggest `! uv run avaris odds ... --confirm`.
- If the sandbox proxy blocks stats.nba.com, stats ingest is user-run too. Keep it throttled to about 1 request/sec.
- Installing Playwright's Chromium deps may need sudo: `! npx playwright install --with-deps chromium`.

## Task Tracking

- Always use `TaskCreate` tool to track your work.

## Next.js

- **Important! ALWAYS read docs before coding:** before any Next.js work, find and read the relevant doc in `node_modules/next/dist/docs/`. Your training data is outdated — the docs are the source of truth.

## Planning

> This applies when you are in plan mode or if the user ask you to plan

- Use the template in `.claude/templates/plan.md`
- Give your `recommendation` when using `AskUserQuestion` tool.

## Project Status

- Fill out change logs CHANGELOG.md, README and STATUS.md proactively

## Subagents

- Gauge if the task will be long running. If it is, try using subagents to not pollute the main session too much. Most of the subagents available can gather specific context that the task need

## Sandbox

**VERY IMPORTANT**: If you hit a sandbox blocker, try running outside of it first. If a classifier blocks you, only then you escalate to the user. Be autonomous as much as possible!
