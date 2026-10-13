# Plan: Phase 5 — Daily pipeline + API

- **Date:** 2026-10-12 ·
- **Task:** `avaris daily` (refresh, retrain when stale, provisional and final predictions with drivers and injury impact), `avaris score`, FastAPI read endpoints, background jobs with a single-job lock, `avaris serve`
- **Status:** In progress
- **Complexity**: `L`
- **Estimate Points**: `8`

---

## 1. Goals

- Predict every game live with the frozen production model, store the predictions with their drivers and injury impact, score them after the games, and serve everything over a local API for the Phase 6 PWA.

**Success criteria:** the Phase 5 done-when in `avaris-nba-analytics-model-build-plan.md`.

---

## 2. Context

- `models/registry.py`: `Registry.load_production(target, hash)`; artifacts are pickles, verified by `model_sha256` since #6.
- `pipeline/train.py`: `train(data, settings, through)` trains on games dated before `through` and lets the registry promote.
- `features/build.py`: `build_features(con)` returns `features` (one row per game as of `decision_ts`) and per-player `availability`; `write_features` replaces the tables.
- `models/predictor.py`: `GamePredictor.predict(features, "report")`; `analytics/drivers.py`: `explain`, `.families()`, `top_drivers`; `analytics/injury_impact.py`: `injury_impact(availability, "report", names)`.
- `ingest/runner.py` `ingest_stats` and `ingest/injuries.py` `ingest_injuries` are idempotent and take a connection and clients.
- `cli.py` `train` opens the DB read-only, which fails while a server holds the write lock.

---

## 3. Decisions

| Decision | Choice | Why |
| :------- | :----- | :-- |
| `daily` order | refresh → features → predict with the current model → retrain if stale → predict again | catch-up finals for past games must come from a model that never saw them; a retrain `--through today` trains on them |
| Model rule | a prediction is written only if every target's run has `through <= game_date_et` | the model never trained on the game; other games are skipped (the backtest covers them) |
| Games predicted | current season (`season_for_date(today)`), dated on or before today ET, with a tip-off and no final prediction | "today plus any earlier game still missing a final"; older seasons were scored by the backtest |
| Provisional vs final | final once `now >= tip_off - 60 min`, from the reports stored at that moment; provisional before it | plan rule; a report that lands later must not change a final |
| Storage | `predictions` has one row per game: provisional rows are replaced only when a value changed, a final row is written once and never replaced | idempotent reruns; the schema keeps one current prediction |
| Staleness | retrain when any target has no production model, or the newest `through` among its production and candidate runs is `retrain_every_days` or more before today; every run warns while a held candidate blocks the retrain | `through` is the data cutoff; counting candidates stops a held run from retraining every day |
| Refresh | stats (schedule, logs, rosters) and injuries for the current season; any refresh error (network, blocked or malformed response) is a warning and `daily` continues on stored data; `--offline` skips it | local-first; the UI still works when stats.nba.com is down |
| `score` | `daily` ends with `score`; `prediction_scores` has one row per final prediction of a final game, rewritten only when the result changed | Performance updates without a separate step |
| Drivers JSON | per target: scale (`log_odds` or `points`), base, every family's contribution, top 3 families | the game view shows top drivers, the families sum to the output |
| Injury JSON | per side: full strength, lost, lost share, players behind it (report mode); null in preseason | no new data source; the API cannot rebuild features per request |
| Single writer | the server holds the read-write connection; requests and jobs use `con.cursor()`; CLI `daily`, `score` and `train` post a job to the server when the DB is locked | DuckDB allows one writer process |
| Jobs | `POST /api/jobs/{daily,score,train}` returns 202 and a `job_id`; a non-blocking process-wide lock returns 409 when busy; `jobs` table keeps status, params, log tail; jobs still `running` at startup are marked failed | plan |
| `serve` | uvicorn on `127.0.0.1:8000` (`[server]` in `config.toml`), runs `daily` once on startup unless `--no-daily` or `daily_on_startup = false`; only loopback `Host` headers; job posts from another site refused | local-only; tests and offline use skip it; DNS rebinding and cross-site requests (security review) |
| Legacy artifacts | an artifact without `model_sha256` is refused; `avaris train --promote RUN_ID` seals it | #6; the production run predates the hash |

---

## 4. Assumptions

| Assumption | Basis | Impact if false |
| :--------- | :---- | :-------------- |
| A full feature rebuild per `daily` is fast enough | about 20 s on the real DB | add incremental features |
| Postponed games get a new date from the schedule ingest | NBA keeps the game ID | a postponed game can keep a final made at the old time |
| DuckDB cursors on one connection are safe across threads | DuckDB docs: one cursor per thread | serialize reads behind a lock |

---

## 5. Allowed Changes

**Files to create:**

| File | Contents |
| :--- | :------- |
| `src/avaris/pipeline/{daily,score,jobs}.py` | daily pipeline, scoring, job manager |
| `src/avaris/api/main.py`, `src/avaris/api/routes/*.py` | app factory and read/job endpoints |
| tests for each | unit, integration, e2e (frozen clock) |

**Files to modify:**

| File | Change |
| :--- | :----- |
| `src/avaris/db.py` | migration 7: `predictions`, `prediction_scores`, `jobs` |
| `src/avaris/config.py`, `config.toml` | `[server]` settings |
| `src/avaris/cli.py` | `daily`, `score`, `serve`; `train` on a read-write connection; job routing when locked |
| `pyproject.toml`, `uv.lock` | `fastapi`, `uvicorn` |
| docs | STATUS, CHANGELOG, ADR-018, README, build plan |

**Schema changes:**

| Object | Change | Rollback |
| :----- | :----- | :------- |
| `predictions`, `prediction_scores`, `jobs` | new tables (migration 7) | drop them |

---

## 6. Implementation Plan

1. #6: `model_sha256` in `meta.json`, verified before `joblib.load` (done).
2. Migration 7 (TDD).
3. `pipeline/daily.py`: due games, status, model rule, prediction rows with drivers and injuries, idempotent writes, staleness, refresh (TDD).
4. `pipeline/score.py` (TDD); CLI `daily` and `score`.
5. `pipeline/jobs.py` (TDD: 409, status, failure, interrupted jobs).
6. API routes with TestClient (TDD); `avaris serve`; CLI routing when locked.
7. Pipeline E2E: train → daily before and after `decision_ts` → score, frozen clock.
8. Code review and security audit; fixes.
9. Real run: seal the production run, `daily` on the real DB, `GET /api/predictions/today`.
10. Docs.

**Testing approach:** TDD for everything.

---

## 7. Scope

**In scope:** the Phase 5 bullets of the build plan, issue #6.
**Out of scope:** the PWA, CORS and static file serving (Phase 6), live-vs-backtest drift flags (Phase 6 Performance page), changing features or hyperparameters.

---

## 8. Acceptance Criteria

- [ ] API tests pass (TestClient)
- [ ] Pipeline E2E passes: train → daily before and after `decision_ts` → score, frozen clock
- [ ] On a game day, `avaris daily` then `GET /api/predictions/today` returns that day's games with `p_home_win`, margin and total μ with 80% intervals, top drivers and `status`

---

## 9. Definition of Done

- [ ] Gates green: ruff, pyright, pytest (e2e included)
- [ ] Docs updated; `git status` clean

## 10. Risks and Open Questions

| Risk / question | Impact | Mitigation |
| :-------------- | :----- | :--------- |
| A report for the decision slot lands after a final was written | final made without it | final rows are never replaced; the stored `report_ts` shows what was used |
| stats.nba.com blocks the sandbox during the real run | no fresh data | `daily --offline` on stored data; ingest becomes user-run |
