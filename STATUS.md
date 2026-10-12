# Status

- **Phase:** Phase 5 in progress (daily pipeline + API) on branch `phase-5-daily-pipeline-api`. Phase 4 merged (PR #10), Phase 3 merged (PR #8), Phase 2 merged (PR #5), Phase 1 merged (PR #2)
- **Pivot (2026-10-12):** Avaris is now an analytics model, not a betting model; The Odds API is dropped (ADR-014)
- **Plan:** `docs/plans/avaris-nba-analytics-model-build-plan.md`; phase detail in `docs/plans/phase-3-features-models.md`, `docs/plans/phase-4-evaluation-analytics.md` and `docs/plans/phase-5-daily-pipeline-api.md`
- **Next:** finish Phase 5, then Phase 6 (desktop PWA)
- **Important!** The 2026-27 season starts in late October 2026. Live predictions need Phases 1-5 done, including the final refit through 2025-26.

## Phase 4 results (2026-10-12)

- **Report:** `docs/reports/phase-4-evaluation.md` (full reports in `docs/reports/phase-4/`)
- **Regular season, model vs Elo:** better on log loss, Brier, MAE and RMSE for every target, CI excluding 0, in 2020-25 (actual), 2021-25 (injury report) and the 2025-26 holdout (both modes)

| Run | `home_win` log loss (Elo) | `margin` MAE (Elo) | `total` MAE (Elo) |
|---|---|---|---|
| 2020-25, actual | 0.6164 (0.6389) | 10.67 (10.99) | 14.63 (15.70) |
| 2021-25, report | 0.6131 (0.6375) | 10.79 (10.94) | 14.60 (15.71) |
| 2025-26 holdout, report | 0.5820 (0.6083) | 11.08 (11.51) | 15.02 (15.96) |

- **Where the model does not beat Elo:** postseason `margin` with the injury report (2021-25 MAE +0.54, CI excludes 0); holdout postseason `home_win` accuracy (0.60 vs 0.68); postseason `home_win` log loss is better but not significantly; play-in and preseason mixed
- **Cost of late scratches (report vs actual):** none on win probability; `margin` MAE +0.10 to +0.16 regular season, about +1 postseason
- **Era shift (#7):** `lost_actual` 11-18 per team-game through 2019-20, 31-36 from 2021-22; the report captures 82-85%; rule unchanged (ADR-015)
- **Production model:** run `20261012T224157Z-b5c3`, trained through 2026-06-13, promoted for all targets
- **Holdout:** scored once (`docs/reports/holdout_used.json`)

## Phase 3 results (2026-10-12)

- **Features (ADR-015):** one event loop builds all features as of `decision_ts` for 20,499 games (40,998 `team_ratings` rows) in about 20 s. Leakage (incl. the 3 h result boundary), trade, neutral-site, preseason and per-date report tests pass
- **Tuning:** Optuna, 60 trials per target and rung, walk-forward 2015-16 to 2019-20 with one refit per season; params frozen in `config.toml` (feature version 2)
- **Weekly walk-forward, 2015-16 to 2019-20, regular season (5,979 games):** report in `docs/reports/phase-3-walkforward-2015-16-to-2019-20.md`

| Target | Elo | Kept rung | Kept |
|---|---|---|---|
| `home_win` log loss | 0.6167 | linear, no isotonic (ADR-016) | 0.6099 |
| `margin` MAE | 9.92 | LightGBM | 9.76 |
| `total` MAE (Elo rung = league average) | 15.79 | linear | 14.59 |

- **80% interval coverage (regular season):** margin 0.80, total 0.81
- **Where the model does not beat Elo:** postseason `home_win` log loss (0.6233 vs 0.6196, 413 games)
- **Isotonic calibration hurt** `home_win` log loss by 0.003-0.008, so it is off (ADR-016)
- **Smoke:** `avaris train --through 2020-10-12` on the real DB trains and registers all three targets in about 30 s
- **Gates:** ruff clean, pyright 0 errors, pytest all passed (e2e included)
- **Follow-ups:** #6 (verify artifact hash before loading), #7 (availability era shift from 2021-22 reports)

## Phase 2 results (2026-10-12)

- **Injury reports: done-when passes.** `avaris ingest injuries` fetched 4,680 reports for 2021-22 to 2025-26 (7 slots missing on the CDN). `avaris ingest status --check`: every regular-season game has a report between tip-off - 12 h and tip-off - 60; unmatched player rows 0.01-0.8% per season (players with no stats rows in any season)
- **Odds removal: done.** Odds client, `CreditGuard`, slot planner, backfill, status and de-vig deleted with their tests and the `avaris odds` CLI group. Migration 4 dropped `odds_events`, `odds_snapshots` and `api_usage` from the real DB (they were empty); `avaris ingest status --check` still passes after it
- **Gates:** ruff clean, pyright 0 errors, pytest 130 passed (e2e included)
- **Data quirks found:** a wrapped injury reason ("(Nasal Fracture, Face Mask)") parses as a player row (merged back); games can be absent from a report when neither team lists a player

## Phase 2 smoke tests (2026-10-12)

1. **Injury reports: pass**
   - `nba-injury-report` 0.1.0 is on PyPI (AGPL, Python >= 3.12, pymupdf). Its parser reads reports from 2021-22, 2023-24, 2024-25 and 2025-26 cleanly, e.g. `Injury-Report_2022-01-15_05PM.pdf`: 123 rows, all with a team and a known status.
   - **URL formats:** hourly `Injury-Report_YYYY-MM-DD_HHPM.pdf` (the file is the HH:30 ET report) until about 2025-12-20, then every 15 minutes as `..._HH_MMPM.pdf`. The package's own fetcher only knows the hourly format, so Avaris fetches the PDFs itself and uses the package only to parse.
   - A missing report returns 403. Rows for teams that have not submitted have no player ("NOT YET SUBMITTED").

## Phase 1 results (2026-10-12)

- **Smoke tests:** stats.nba.com works from the sandbox with the full browser header set (minimal headers hang). `scheduleleaguev2` carries tip-off times for finished seasons back to 2012-13.
- **Ingest:** 520 requests for 2012-13 to 2026-27; reruns touch only the current season (39 requests).
- **`avaris ingest status --check`:** all checks pass
  - Regular-season games: 1,230 per season, except 2012-13 (1,229, cancelled BOS-IND), 2019-20 (1,059) and 2020-21 (1,080)
  - Every game has a `season_type`; every game from 2020-21 on has a tip-off (one 2015-16 preseason game has none)
  - 172 bubble games tagged neutral, 0 untagged; every non-preseason venue is in the arena CSVs
  - Every final game has 2 team-log rows; rosters for 30 teams per season
- **Data quirks found:** the cancelled 2013 BOS-IND game is listed in the team log with no result (dropped); `isNeutral` is only set from 2024-25 (ADR-010)
