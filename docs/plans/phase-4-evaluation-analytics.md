# Plan: Phase 4 — Evaluation + analytics

- **Date:** 2026-10-12 ·
- **Task:** scored walk-forward 2020-21 to 2024-25 vs Elo and two naive baselines, injury-report re-run, drivers and injury impact, report with charts, holdout run, first production model
- **Status:** In progress
- **Complexity**: `L`
- **Estimate Points**: `8`

---

## 1. Goals

- Measure the frozen Phase 3 models honestly on seasons never used for tuning, explain each prediction (drivers, injury impact), and ship the first production model.

**Success criteria:** the Phase 4 done-when in `avaris-nba-analytics-model-build-plan.md`.

---

## 2. Context

- `backtest/walkforward.py`: `walk_forward(...)` trains on every game before a weekly block; calibration and σ refit once per test season from OOF predictions.
- `models/ladder.py`: kept rungs are `home_win` linear (logistic), `margin` lgbm, `total` linear (ridge); params frozen in `config.toml`.
- `features/build.py`: `model_frame(features, availability)` fills `home_lost`/`away_lost` from `lost_actual_*` or `lost_report_*`; `FeatureSet.availability` has per-player rows.
- `features/team_form.py`: `TeamForm` has EW ratings carried across seasons, not season-to-date ones.
- Issue #7: measure the availability era shift from 2021-22 reports.

---

## 3. Decisions

| Decision | Choice | Why |
| :------- | :----- | :-- |
| Models compared | kept rung per target, Elo rung, `naive_home`, `naive_net`, all weekly refits with the frozen config | the plan's bar; other rungs were settled in Phase 3 |
| `naive_home` | mean of the target over the last 1,230 training games: home win rate, mean home margin, mean total | "home team always at the season's home win rate", as-of by construction |
| `naive_net` | one-feature fit on the training window: logistic (`home_win`) or OLS (`margin`) on the season-to-date net rating difference; `total`: OLS on the season-to-date expected total; missing before a team's first game, filled with 0 difference or the league total | "season-to-date net rating difference" mapped to each output with the fewest choices |
| Season-to-date ratings | `TeamForm` also tracks this season's ORtg, DRtg and pace sums; `features` gets `{home,away}_{ortg,drtg,pace}_std` (migration 6); not in `MODEL_FEATURES`, so the feature hash and frozen models are unchanged | no retune; covered by the leakage test |
| Report re-run | `availability="report"` applies to the test block only; training, OOF calibration and σ stay on `actual` | mirrors live use (production trains on `actual`, predicts from the report) |
| Bootstrap | 1,000 replicates over games, percentile 95% CI; one index draw per replicate shared by all models, so model − Elo is a paired CI; ECE recomputed per replicate | paired CIs make "does not beat Elo" a plain statement |
| Calibration metrics | ECE with 10 equal-width bins, reliability diagram, PIT histogram (10 bins) under N(μ, σ) | plan metrics |
| Charts | hand-written SVG, no new dependency | avoids matplotlib and a dependency review |
| Drivers | contributions on the link scale: log-odds for `home_win`, the prediction for `margin`/`total`; LightGBM `pred_contrib`, linear `coef × scaled value` with imputer indicators folded into their feature; Elo rung: one `elo` contribution, base 0. `base + Σ contributions = raw output` checked on every evaluation prediction | plan rule; isotonic is off for `home_win`, so log-odds map straight to `p` |
| Families | `elo`, `form`, `rest_travel`, `availability`, `home_court`, `game_type` (`is_preseason`, `is_postseason`), `league` (`league_total`, `league_pace`) | plan families plus two that fit nowhere else |
| Injury impact | per team and game: full strength, lost (actual or report), lost share, and the players behind it sorted by value lost; player names from `player_games` | derived from the availability feature, no new data |
| Issue #7 | measure `lost_actual` vs `lost_report` per season and the report-run cost; do not change the availability rule in Phase 4 | picking a rule from 2021-25 results would tune on scored seasons; a rule change also needs a feature bump |
| Holdout | `avaris evaluate --holdout` scores 2025-26 once (both availability modes) and writes `artifacts/reports/holdout_used.json`; a second run is refused | ADR-002 |
| Holdout timing | after code review and every other deliverable; predictions copied to `docs/reports/` so metrics can be recomputed without re-predicting | a model bug found after the holdout cannot be re-run |
| Final refit | `avaris train --through 2026-09-01` (season rollover), all of 2025-26 including playoffs, after checking 2025-26 is complete | first production model |

---

## 4. Assumptions

| Assumption | Basis | Impact if false |
| :--------- | :---- | :-------------- |
| 2025-26 is complete in the real DB (1,230 regular-season finals, playoffs) | Phase 1 ingest | holdout and refit wait for an ingest |
| Weekly walk-forward of 4 models × 3 targets × 5 seasons runs in under 20 min | Phase 3 runtime | run in the background |

---

## 5. Allowed Changes

**Files to create:**

| File | Contents |
| :--- | :------- |
| `src/avaris/models/baselines.py` | `NaiveHome`, `NaiveNet` |
| `src/avaris/backtest/bootstrap.py` | per-game losses, paired bootstrap |
| `src/avaris/backtest/evaluate.py` | evaluation runs, tables, report |
| `src/avaris/backtest/charts.py` | SVG reliability diagram and PIT histogram |
| `src/avaris/analytics/{drivers,injury_impact}.py` | drivers and injury impact |
| tests for each | unit, integration, e2e |
| `docs/reports/phase-4-*` | reports, charts, holdout predictions |

**Files to modify:**

| File | Change |
| :--- | :----- |
| `src/avaris/features/{team_form,build}.py` | season-to-date ratings columns |
| `src/avaris/db.py` | migration 6 |
| `src/avaris/models/ladder.py` | `make_rung` builds baselines |
| `src/avaris/backtest/{walkforward,metrics}.py` | availability mode, drivers, ECE, reliability, PIT |
| `src/avaris/cli.py` | `avaris evaluate` |
| docs | STATUS, CHANGELOG, ADR (ADR-015 note, ADR-017), README, plan |

**Dependencies:** none

**Schema changes:**

| Object | Change | Rollback |
| :----- | :----- | :------- |
| `features` | add `{home,away}_{ortg,drtg,pace}_std double` | drop the columns |

---

## 6. Implementation Plan

1. Metrics: ECE, reliability bins, PIT; bootstrap with paired differences (TDD).
2. Season-to-date ratings in `TeamForm`, features and migration 6; baselines in `models/baselines.py` (TDD, feature hash unchanged).
3. Drivers and injury impact (TDD on the synthetic DB, both rung types).
4. `walk_forward` availability mode and drivers; `evaluate.py`, charts and `avaris evaluate` with the holdout guard (TDD, e2e).
5. Real runs: actual 2020-21 to 2024-25, report 2021-22 to 2024-25.
6. Code review and fixes.
7. Holdout run once; final refit through 2026-09-01 and promote.
8. Docs and report.

**Testing approach:** TDD; report styling test-after.

---

## 7. Scope

**In scope:** the Phase 4 bullets of the build plan, issue #7 measurement.
**Out of scope:** changing features or hyperparameters, the daily pipeline, the API, storing predictions in DuckDB (Phase 5).

---

## 8. Acceptance Criteria

- [ ] Every metric with bootstrap CIs against Elo and both naive baselines, calibration and interval coverage, for actual, report and holdout runs
- [ ] The report states plainly where the model does not beat Elo
- [ ] Drivers sum to the model output on every evaluation prediction
- [ ] A production artifact trained through 2025-26 is in the registry

---

## 9. Definition of Done

- [ ] Gates green: ruff, pyright, pytest (e2e included)
- [ ] Docs updated; `git status` clean

## 10. Risks and Open Questions

| Risk / question | Impact | Mitigation |
| :-------------- | :----- | :--------- |
| A bug found after the holdout run | holdout cannot be re-run | review first; holdout predictions saved so metric fixes recompute without re-predicting |
| Season-to-date columns change model features | retune cascade | test asserts `feature_hash()` unchanged |
