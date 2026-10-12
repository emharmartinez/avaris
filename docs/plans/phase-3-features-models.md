# Plan: Phase 3 — Features + models

- **Date:** 2026-10-12 ·
- **Task:** point-in-time features, `team_ratings`, the model ladder with tuning, `avaris train` and the registry
- **Status:** Ready for implementation
- **Complexity**: `XL`
- **Estimate Points**: `13`

---

## 1. Goals

- Build every feature family strictly as of each game's `decision_ts`, tune and select the model ladder on 2015-16 to 2019-20, and produce registered production artifacts with `avaris train`.

**Success criteria:** the Phase 3 done-when in `avaris-nba-analytics-model-build-plan.md`.

---

## 2. Context

- `features/decision_time.py`: `decision_ts(tip, report_times)` exists; reports must be restricted to the game's own window (else a previous day's report wins).
- `ingest/status.py:124`: the injury check already uses the window `[tip - 12 h, tip - 60 min]`.
- `ingest/teams.py`: `Venues.lookup(venue, home_team_id)` gives coordinates, tz and altitude.
- Real DB: 18,112 non-preseason finals with box logs, 1,155 preseason finals (scores only), injury reports for 2021-22 on.
- `rosters` is an end-of-season snapshot for finished seasons, so it is not point-in-time.

**Key files:**

| File | Why it matters |
| :--- | :------------- |
| `src/avaris/db.py` | migration 5 adds `features` and `team_ratings` |
| `src/avaris/features/` | all feature code |
| `src/avaris/models/`, `backtest/`, `pipeline/train.py` | ladder, walk-forward, training, registry |

---

## 3. Decisions

| Decision | Choice | Why |
| :------- | :----- | :-- |
| When a result is known | `result_ts = tip_off_utc + 3 h`; a game feeds features only if `result_ts <= decision_ts` | gives every row a timestamp for the leakage test |
| Decision report window | latest `ok` report in `[tip - 12 h, tip - 60 min]`, else `tip - 60 min` | same window as the injury check; no previous-day reports |
| Feature engine | one chronological event loop: result events update state, decision events snapshot it (results at the same instant apply first) | as-of semantics by construction; also fills `team_ratings` |
| Preseason | no result events at all; schedule history (rest, travel) skips preseason too | preseason test: deleting preseason games changes no other game |
| Availability modes | `features` stores `lost_actual_*` (who played in the game) and `lost_report_*` (decision report); the model sees neutral `lost_home`/`lost_away`, filled by an `availability_mode` | one feature hash for training (actual) and live (report) |
| What is post-hoc in `lost_actual` | only who played (`minutes > 0`); rates and expected minutes are as of `decision_ts` | the leakage test keeps the target game's own `player_games` rows and then checks every column |
| Team player set | players whose latest appearance this season was for the team, minus 10+ straight misses unless on the decision report | point-in-time; no end-of-season roster leakage |
| Report-listed players not in the set | added with this season's rate, else last season's | covers stars hurt since preseason |
| Travel | 0 km and 0 tz shift after a gap of more than 7 days; unknown venue gives null | bubble and season openers have no travel fatigue |
| Home court | `home_court` 1 or 0 (neutral), plus a `no_fans` flag for 2020-21; Elo home advantage scaled by a config factor in 2020-21 | the models learn the no-fans effect; no hand-set guess in features |
| Elo | K 20, home advantage 100, MOV multiplier, 0.75 carryover to 1505 applied at a team's first event of a new season (a preseason decision included); updates on regular, play-in and playoffs, not preseason or the Cup final; not tuned | standard baseline; plan says Elo skips the Cup final |
| Cup final | feeds team form and availability; σ bucket regular | it is a real game but outside the standings |
| Elo rung for `total` | as-of EW league average total | Elo has no total |
| Calibration and σ in walk-forward | refit once per test season from season-wise forward-chained OOF (last 3 seasons); the base model refits weekly | keeps weekly walk-forward cheap |
| Optuna trials | raw (uncalibrated) metric on regular-season rows, one refit per season, SQLite storage | plan compute budget; headline metric is regular season |
| Rung selection | regular-season log loss and MAE, weekly refits | headline metric |
| Decision window constant | `REPORT_WINDOW = 12 h` lives in `decision_time.py`; `status.py` imports it | one rule, one definition |
| Promotion | feature hash matches, more rows, OOF metric within tolerance, same rung and params as production; else candidate. The first artifact of a target is promoted | plan rules plus "rung or param change needs `--promote`" |

---

## 4. Assumptions

| Assumption | Basis | Impact if false |
| :--------- | :---- | :-------------- |
| 3 h after tip-off every game is final | regulation is about 2 h 15 min | a late OT result is ignored for one decision; no leakage |
| LightGBM wheels run on this machine | manylinux wheel with bundled OpenMP | fall back to sklearn `HistGradientBoosting` |

---

## 5. Allowed Changes

**Files to create:**

| File | Contents |
| :--- | :------- |
| `src/avaris/features/{elo,team_form,schedule,availability,build}.py` | feature families and the event loop |
| `src/avaris/models/{baselines,linear,gbm,calibration,distributions,ladder,registry}.py` | rungs, isotonic, σ per bucket, predictor, registry |
| `src/avaris/backtest/{walkforward,metrics,tuning}.py` | walk-forward, metrics, Optuna |
| `src/avaris/pipeline/train.py` | `train(through)` and artifacts |
| `tests/fixtures/synthetic.py` | deterministic synthetic league DB: two seasons, preseason games, a traded player, a neutral site, same-day reports either side of `decision_ts`, a game with no tip-off |
| `tests/unit/test_*.py`, `tests/integration/test_*.py` | per module |

**Files to modify:** `db.py` (migration 5), `features/decision_time.py` (per-game resolution), `config.py` + `config.toml` (`[models]`), `cli.py` (`features`, `tune`, `backtest`, `train`), docs.

**Dependencies:** scikit-learn, lightgbm, optuna, scipy.

**Schema changes:** migration 5 creates `features` (game + `decision_ts`) and `team_ratings` (team + as-of game). Rollback: drop both.

---

## 6. Implementation Plan

1. Deps, migration 5, synthetic league fixture.
2. Per-game `decision_ts` resolution (TDD).
3. Elo, team form, schedule, availability state (TDD per module).
4. Event loop `build_features` + `team_ratings`; leakage, trade, neutral-site and preseason tests.
5. Metrics, distributions (σ per bucket), calibration, rungs, ladder predictor.
6. Walk-forward (season and weekly refits) and Optuna tuning.
7. Registry and `train --through`, CLI; train-cutoff and registry tests.
8. Run on the real DB: features, tuning, weekly walk-forward on 2015-16 to 2019-20; freeze params and rungs in `config.toml`; report in `artifacts/reports/`.
9. Docs: ADR, STATUS, CHANGELOG, README.

**Testing approach:** TDD for all deterministic code; tuning is test-after.

---

## 7. Scope

**In scope:** Phase 3 of the build plan.
**Out of scope:** drivers, injury impact output, naive baselines, 2020-21+ evaluation (Phase 4); `daily`, `score`, API (Phase 5).

---

## 8. Acceptance Criteria

- [ ] Leakage, trade, neutral-site, preseason, train-cutoff and registry tests pass
- [ ] Weekly walk-forward on 2015-16 to 2019-20 shows the kept rung beating Elo on log loss and MAE
- [ ] Hyperparameters and kept rungs frozen in `config.toml`

## 9. Definition of Done

- [ ] ruff, pyright, pytest (e2e included) green; docs updated; committed

## 10. Risks and Open Questions

| Risk / question | Impact | Mitigation |
| :-------------- | :----- | :--------- |
| Event loop too slow in Python | slow builds | per-season state dicts; profile on real DB |
| Kept rung does not beat Elo on `total` | done-when fails for total | Elo rung for total is weak (league average); report plainly |
