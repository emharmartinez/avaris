# Changelog

## Unreleased

### Removed
- **Phase 2, odds removal (ADR-014):** The Odds API client, `CreditGuard`, snapshot slot planner, odds backfill, `avaris odds` CLI group, odds and guard settings, and de-vig (`betting/`). Migration 4 drops `odds_events`, `odds_snapshots` and `api_usage`

### Added
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
