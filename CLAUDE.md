# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

- **In progress:** see `STATUS.md` for the current phase. The source of truth is `docs/plans/avaris-nba-analytics-model-build-plan.md`: it holds the stack, design, layout and six phases, each with a "Done when". Read it before starting a phase.
- Avaris is a personal, single-user, local-only NBA analytics model: win probability, margin and total (with 80% intervals), plus drivers, team ratings and injury impact. It is not a betting model (ADR-014); the Edge tab only compares odds the user types in (ADR-020). Do not add accounts, auth, hosting, multi-tenancy or billing code.

## Commands

**Python** (uv, from repo root)

```
uv run ruff check
uv run pyright
uv run pytest                                  # all tests
uv run pytest tests/unit/test_devig.py::test_x # single test
uv run pytest -m e2e                           # pipeline E2E only
uv run avaris ...                              # Typer CLI (ingest, features, tune, backtest, evaluate, train, daily, score, serve)
```

**Web** (from `web/`; always pass `--cache "$TMPDIR/npm-cache"` to npm because of the sandbox)

```
npm run lint && npm run typecheck && npm run test && npm run build
npm run test:e2e                               # builds, then Playwright against tests/fixtures/web_server.py (frozen clock, synthetic league)
npx vitest run path/to/file.test.tsx           # single unit test
```

All gates must be green at the end of every phase.

## Architecture

- **Data flow:**
  1. Ingest: stats.nba.com stats (thin httpx client, ADR-009) and NBA injury reports go into a raw response cache and DuckDB. For preseason games only, ESPN's injury list feeds a rest adjustment applied after the model (ADR-022).
  2. Point-in-time features.
  3. Models for `home_win` (calibrated probability) and `margin` and `total` (N(μ, σ) with an 80% interval).
  4. Analytics: drivers (feature contributions), team ratings, injury impact.
  5. Predictions are served by the FastAPI server and shown in the PWA.
- **Evaluation uses proper scoring rules** (log loss, Brier, MAE, RMSE, calibration, interval coverage) against Elo and two naive baselines. Walk-forward only. The **2025-26 season is a holdout used once**; never tune on it.
- **Features must be as of `decision_ts`** (one instant per game, default the latest injury report at or before tip-off minus 60 min). Injuries and features are frozen at it, in backtests and live. The leakage test must hold at timestamp granularity: deleting rows with `ts > decision_ts` cannot change that game's features.
- **Every game is predicted, preseason included;** headline metrics use the regular season, preseason, play-in and playoffs are reported separately. Preseason results never feed features (Elo, form, availability). `season_type` and `neutral_site` live on `games`. `game_date` is the ET date of tip-off; timestamps are stored in UTC.
- **No scheduler.** `avaris daily` is idempotent and catches up whenever it runs; `avaris serve` runs it on startup and the UI has a Refresh button.
- **Tuning uses 2015-16 to 2019-20 only.** Hyperparameters and the kept rung are frozen for 2020-21+.
- **No odds or market data in the pipeline.** The Odds API was dropped (ADR-014); do not add odds ingestion, odds tables, bets, staking or spend tracking back. The one exception is the Edge tab (ADR-020): odds the user types in, compared with the model in the browser, never fetched or stored.
- **Traditional model (ADR-024)** is a separate rule-based model (`src/avaris/traditional/`, no fitting) in its own tab. Its live lines come from stats.nba.com `scoreboardv3`, fetched by the API process, cached in memory for 30 s and never written to DuckDB. It never feeds the ML pipeline or the evaluation ladder.
- **Single DuckDB writer.**
  - The FastAPI process owns the read-write connection.
  - CLI jobs run in-process only when the server is down. Otherwise they go through `POST /api/jobs/{daily,score,train}`.
  - The UI never calls external APIs.
- **Web** is Next.js App Router + shadcn/ui with `output: 'export'`. FastAPI serves the static `web/out`; there is no Node server at runtime. So: no server actions, no route handlers, all data is fetched client-side with TanStack Query, and dynamic segments need `generateStaticParams` (prefer query params). In dev, `next dev` calls FastAPI via `NEXT_PUBLIC_API_BASE`.

## Testing

- **TDD by default** for all deterministic code. Write the failing test first. Test-after is allowed only for exploratory model tuning and report styling.
- **No live network in tests.** Use recorded responses and the fixture DuckDB built by `tests/fixtures/`.
- **Vitest uses `node` by default.** Only `*.test.tsx` (component rendering, interaction, `renderHook`) runs in `jsdom`, because jsdom is slow. Put logic in plain `.ts` modules so it can be tested in `node`.
- **IMPORTANT**: Do not ignore E2E tests

## Environment constraints

- stats.nba.com works from the sandbox with `allowed_domains: ["stats.nba.com"]`; it hangs unless the full browser header set in `ingest/stats_client.py` is sent. Keep it throttled to about 1 request/sec. If it gets blocked, stats ingest becomes user-run.
- The NBA injury report CDN works from the sandbox with `allowed_domains: ["ak-static.cms.nba.com"]`, so `avaris ingest injuries` can run there.
- uv cannot write `~/.cache/uv` in the sandbox: prefix uv commands with `UV_CACHE_DIR=$TMPDIR/uv-cache`.
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

- Fill out change logs CHANGELOG.md, README, ADR(Architecture Decision Records).md and STATUS.md proactively
- Report to the user for every completed phase. This is your checkpoint.

## Subagents

- Gauge if the task will be long running. If it is, try using subagents to not pollute the main session too much. Most of the subagents available can gather specific context that the task need

## Sandbox

**VERY IMPORTANT**: If you hit a sandbox blocker, try running outside of it first. If a classifier blocks you, only then you escalate to the user. Be autonomous as much as possible!

## GitHub

- Always ensure `git status` clean once done with task. Do not leave it dirty.
- Commit often but ask the user first before pushing
- Track deferred work as GitHub issues: whenever new tech debt is deferred for later, or a bug or issue surfaces that is out of scope for the current work, create a GitHub issue for it — deferred work must never live only in chat, commit messages, or code comments.
- Prefer using worktree if needed. Use the `EnterWorktreeTool`
- Main can be bypassed. Only bypass when the user says so

## User Input

- State in your report what the user need to do, what commands to run that is blocking you(Again always try outside of sandbox first), etc
