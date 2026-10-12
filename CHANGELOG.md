# Changelog

## Unreleased

### Changed
- **Plan:** closed gaps in `docs/plans/plan-for-this-first-snug-fox.md` and added a Risks and mitigation table
  - One `decision_ts` per game freezes odds, injuries and features; leakage test at timestamp granularity
  - `tip_off_utc`, `game_date_et` (ET), `season_type` and `neutral_site` on `games`; preseason dropped; betting regular season only; bubble and neutral-site handling
  - Spread and total edges per book at the book's line; `w` per target; same-game correlation cap
  - APScheduler inside `avaris serve` for morning, decision and closing snapshots; free-tier budget math and guard defaults
  - Jobs table, job lock and status endpoint; `refetch_days` for in-progress season stats
  - Optuna trials with one refit per season; Phase 2 smoke tests for injury PDFs and Odds API pricing; 4-week paper-trading gate
  - Recommended odds per pick (`rec_book`, `rec_price`, `rec_line`, `min_price`, `fair_price`) in the picks table, API, Today page and Bet Log pre-fill
- **CLAUDE.md:** `decision_ts`, regular-season-only, per-book spread/total and live closing-line rules
- **Plan:** added production training to `docs/plans/plan-for-this-first-snug-fox.md`
  - `avaris train --through DATE`, artifact `meta.json`, and `registry.json` with promotion rules and a feature-hash check
  - Weekly retrain triggered by `avaris daily`, plus `POST /api/jobs/train`
  - Tuning and rung selection on 2015-16 to 2019-20 only; hyperparameters frozen for 2020-21+
  - Walk-forward fitting of blend `w` and edge thresholds, with 2020-21 as a warm-up season
  - Final refit through 2025-26 after the holdout run, as the first production model
