# Changelog

## Unreleased

### Changed
- Traditional live lines come from ESPN's scoreboard, with stats.nba.com's as the fallback (ADR-024, #30). stats.nba.com ran 4 to 5 minutes behind live games
- Odds open in decimal on the Edge and Traditional tabs; both have a Decimal/American toggle (Traditional's is new)
- The Today view hides games that have finished and shows only those not started or in progress ("All of today's games have finished." once the slate is done). Other dates still list their finals with scores
- Preseason win probability is read off the margin model, P(margin > 0) under N(μ, σ), and follows the ESPN rest-adjusted margin (ADR-023, #20). On 2015-16 to 2018-19 preseason games log loss drops from 0.667 to 0.648. The win-only rest coefficient (`k_win`) is retired. Preseason win drivers are the margin drivers, in points; the API returns `driver_scale` per target

### Added
- Traditional tab: a total line on each card (starts at the pregame total, editable) with the chance of going over and under it, pregame and live; finals grade the total against it (ADR-024). The line stays in the browser
- Traditional tab (`/traditional/?date=`, `GET /api/traditional`, ADR-024): a rule-based model with no machine learning (Elo blended with season-to-date efficiency ratings, home court, back-to-back) giving a fair moneyline, spread and total with 80% intervals for every game. Live games update from stats.nba.com's scoreboard (score, period, clock) and the tab polls while they are on; finals are graded against the pregame line
- `avaris preseason-win-check`: the preseason `home_win` classifier against the margin-derived probability on the tuning window (log loss, Brier, accuracy, ECE with paired bootstrap CIs, reliability)
- Preseason rest adjustment (ADR-022): preseason win probability, margin and total are shifted by the value of the players ESPN lists out or resting, with coefficients fitted on past preseason box scores (`avaris ingest preseason-logs`, `avaris rest-fit`). `daily` fetches the ESPN list only when a preseason game is due (`avaris ingest espn` by hand). The card, game page and Edge tab label it "Rest-adjusted (ESPN)" and show the raw model values. Regular season, play-in and playoffs are unchanged
- `avaris serve` stops itself once the app has been closed for `[server] idle_shutdown_min` (default 5; `--idle-min`, `0` = never), never while a job runs (ADR-021)
- Stop server button in the app header (`POST /api/server/stop`), with an inline confirm
- Edge tab (`/edge/`, ADR-020): pick a predicted game, type moneyline, spread and total odds (American or decimal) and see model probability, no-vig implied probability, edge, EV per 100 and fair price. Whole-number lines show the push chance. Odds stay in the browser

### Fixed
- The launcher's `-Stop` no longer kills an unrelated process through a stale `data/serve.pid`
- The app could hang after a rebuild: pages had no `Cache-Control`, so Chrome reused an old page whose scripts the rebuild deleted. Pages are now `no-cache`, hashed `_next/static/` assets `immutable`, and the service worker revalidates pages

### Added
- `scripts/avaris-launch.ps1`: Windows launcher that starts `avaris serve` in WSL when needed, then opens the installed PWA; `-Install` adds a Start menu shortcut, `-Stop` stops the server
- The PWA says "Server not running" instead of a fetch error when the API is unreachable

### Changed
- The PWA is dark only: shadcn dark theme on `<html>`, `color-scheme: dark`, dark manifest splash and title bar, and a reversed gray chart ramp so every series stays visible on dark cards

### Security
- `model.joblib` is verified against `model_sha256` in `meta.json` before loading; unhashed artifacts are sealed by a manual promote (#6)

### Removed
- **Phase 2, odds removal (ADR-014):** The Odds API client, `CreditGuard`, snapshot slot planner, odds backfill, `avaris odds` CLI group, odds and guard settings, and de-vig (`betting/`). Migration 4 drops `odds_events`, `odds_snapshots` and `api_usage`

### Added
- **Phase 6, desktop PWA (ADR-019)**
  - `web/`: Next.js 16 static export with shadcn/ui, TanStack Query and Recharts: Today (provisional or final, countdown to final, win probability, margin and total with 80% intervals, injury impact, top drivers), Game (distribution charts, all drivers, injury reports, rating trends, score), Teams, Performance (season to date, drift flag), Backtests (markdown without raw HTML, SVG charts), Injuries; a Refresh button that runs `daily` and shows its progress
  - PWA: manifest, icons, service worker caching the app shell (never `/api`)
  - `avaris serve` serves `web/out` at `/`; unknown `/api/*` paths are JSON 404s; `serve --dev` allows CORS from loopback origins only (#13)
  - `/api/performance` gains `drift` (live metrics vs the reference backtest's resampled n-game range); `/api/health` gains `now` and `today`
  - Tests: Vitest (node for logic, jsdom for components, msw), Playwright E2E for every page and the Refresh flow on a frozen-clock fixture server; CI web job (lint, typecheck, Vitest, build)
- **Phase 5, daily pipeline + API**
  - `avaris daily [--offline]`: source refresh, features, provisional and final predictions with drivers and injury impact, catch-up of missed games, retrain when stale, scoring; idempotent (ADR-018)
  - `avaris score`: `prediction_scores` per final prediction (log loss, Brier, errors, 80% interval hits, PIT)
  - `avaris serve`: FastAPI on `127.0.0.1:8000` with read endpoints (predictions, game detail, teams, performance, backtests, injuries) and `POST /api/jobs/{daily,score,train}` with a single-job lock; runs `daily` on startup
  - CLI `daily`, `score` and `train` run as server jobs while `serve` holds the database
  - Migration 7: `predictions`, `prediction_scores`, `jobs`; `[server]` settings
  - Dependencies: FastAPI, uvicorn
- **Phase 4, evaluation + analytics**
  - `avaris evaluate [--from] [--to] [--availability actual|report] [--holdout]`: weekly walk-forward of the kept rungs against Elo, `naive_home` and `naive_net`, with paired bootstrap CIs, ECE, reliability diagrams, PIT histograms (SVG), metrics per season and scope, and drivers per family (ADR-017)
  - Holdout guard: `evaluate --holdout` scores a finished holdout season once in both availability modes and records `docs/reports/holdout_used.json`; `backtest`, `tune` and `evaluate` refuse windows reaching it
  - `analytics/drivers.py` (LightGBM `pred_contrib`, coefficient x scaled value, Elo) and `analytics/injury_impact.py` (strength lost and the players behind it)
  - Migration 6: season-to-date ORtg, DRtg and pace in `features` (naive-baseline inputs, not model features)
  - Reports in `docs/reports/phase-4-evaluation.md` and `docs/reports/phase-4/`; first production model trained through 2025-26
- **Phase 3, features + models**
  - Migration 5: `features` (game + `decision_ts`, with `feature_hash`) and `team_ratings`
  - Per-game `decision_ts` resolution with a `[tip - 12 h, tip - 60 min]` report window, shared with the injury check
  - Point-in-time feature event loop (ADR-015): Elo, EW team form, league averages, rest and travel, home court, availability from who played and from the decision report; preseason never feeds features
  - Model ladder (Elo, logistic/ridge, LightGBM), optional isotonic calibration, σ per `season_type` bucket, walk-forward with season or weekly refits, Optuna tuning with SQLite storage
  - `avaris features build`, `avaris tune`, `avaris backtest`, `avaris train [--through] [--promote]`; artifacts with `meta.json` and a registry with promotion rules and feature-hash refusal
  - Frozen hyperparameters and kept rungs in `config.toml`; walk-forward report in `docs/reports/`
  - Synthetic league fixture for feature, model and CLI tests
  - Dependencies: scikit-learn, LightGBM, Optuna, SciPy
- **Phase 2, injuries**
  - Schema: `injury_report_files`, `injury_reports` (plus odds tables, dropped again by migration 4)
  - `avaris ingest injuries`: official NBA injury report PDFs at each game's decision slot (hourly and 15-minute URL formats), `report_ts` from the PDF header, players matched to IDs; coverage check in `avaris ingest status`
  - `decision_ts` resolution (`features/decision_time.py`): latest report at or before tip-off - 60, else tip-off - 60
- **Phase 1, foundation + stats data**
  - uv project (Python 3.12) with ruff, pyright, pytest (`e2e` marker), `config.toml` with env overrides
  - DuckDB schema with versioned migrations: `games`, `team_games`, `player_games`, `rosters`
  - stats.nba.com client: browser headers, ~1 req/s throttle, retries, gzip raw cache
  - `avaris ingest stats`: schedule (tip-off UTC, ET game date, `season_type`, venue, neutral site), team and player game logs, rosters for 2012-13 to the current season
  - `avaris ingest status [--check]`: per-season counts and Phase 1 data checks
  - `teams.csv`, `arenas.csv` and `neutral_venues.csv` reference data
  - Unit, integration and CLI e2e tests on trimmed recorded responses

### Changed
- **Plan (decision 4):** preseason games are predicted and scored, reported separately, and never feed features; σ per `season_type` bucket (ADR-004)
- **Pivot to an analytics model (ADR-014):** plan renamed to `docs/plans/avaris-nba-analytics-model-build-plan.md` and rewritten (predictive distributions, drivers, team ratings, injury impact, proper scoring rules, no scheduler, `score` replaces `settle`); ADR-005, 006, 008, 011 and 013 superseded; ADR-001 to 004, `CLAUDE.md` and `README.md` updated
- **Plan / CLAUDE.md:** stats come from a thin httpx client instead of `nba_api` (ADR-009); neutral-site rule (ADR-010); sandbox notes for stats.nba.com and `UV_CACHE_DIR`
- **Plan:** closed gaps in `docs/plans/avaris-nba-analytics-model-build-plan.md` and added a Risks and mitigation table
  - One `decision_ts` per game freezes odds, injuries and features; leakage test at timestamp granularity
  - `tip_off_utc`, `game_date_et` (ET), `season_type` and `neutral_site` on `games`; preseason dropped; betting regular season only; bubble and neutral-site handling
  - Spread and total edges per book at the book's line; `w` per target; same-game correlation cap
  - APScheduler inside `avaris serve` for morning, decision and closing snapshots; free-tier budget math and guard defaults
  - Jobs table, job lock and status endpoint; `refetch_days` for in-progress season stats
  - Optuna trials with one refit per season; Phase 2 smoke tests for injury PDFs and Odds API pricing; 4-week paper-trading gate
  - Recommended odds per pick (`rec_book`, `rec_price`, `rec_line`, `min_price`, `fair_price`) in the picks table, API, Today page and Bet Log pre-fill
- **CLAUDE.md:** `decision_ts`, regular-season-only, per-book spread/total and live closing-line rules
- **Plan:** added production training to `docs/plans/avaris-nba-analytics-model-build-plan.md`
  - `avaris train --through DATE`, artifact `meta.json`, and `registry.json` with promotion rules and a feature-hash check
  - Weekly retrain triggered by `avaris daily`, plus `POST /api/jobs/train`
  - Tuning and rung selection on 2015-16 to 2019-20 only; hyperparameters frozen for 2020-21+
  - Walk-forward fitting of blend `w` and edge thresholds, with 2020-21 as a warm-up season
  - Final refit through 2025-26 after the holdout run, as the first production model
