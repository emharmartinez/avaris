# Plan: Preseason rest adjustment from ESPN injury notes

- **Date:** 2026-10-13 ·
- **Task:** For preseason games only, shift the model's margin, total and win probability by the value of players ESPN lists as out or resting, with the shift fitted on past preseason box scores.
- **Status:** Ready for implementation
- **Complexity**: L
- **Estimate Points**: 8

---

## 1. Goals

- Preseason predictions should reflect players who sit out. On 2026-10-13, NYK @ TOR had Brunson, Towns and Anunoby resting. The model gave NYK 62.1%; the market had TOR at 1.23.
- The change applies **only to preseason games**. Regular season, play-in, Cup and playoff features, models, predictions and metrics stay exactly as they are.
- The model is not retrained and gets no new inputs. The adjustment is a rule applied after the model, with three coefficients fitted on history.

**Success criteria:**

- On 2020-21 to 2024-25 preseason games, the adjustment (fitted on 2015-16 to 2019-20 with actual absences) is reported against the raw model for log loss, margin MAE and total MAE. Each output is switched on only if it beats raw there.
- For a preseason game, `/api/predictions/today` returns the adjusted `p_home_win`, `margin` and `total`, a `rest` block with the raw values, the ESPN out list per side and the lost value per side. The card, game page and Edge tab show the adjusted numbers labelled "Rest-adjusted (ESPN)", with the raw ones beside them.
- For every non-preseason game, the prediction rows, features rows and `feature_hash` are byte-identical with and without this change, and no ESPN request is made on a day with no preseason game due.

---

## 2. Context

- **NBA has no injury report for preseason.**
  - Every `ak-static.cms.nba.com` slot for 2026-10-12 and 2026-10-13 returns 403. Regular-season slots such as 2026-04-10 return 200.
  - The injury ingest skips preseason days on purpose (`src/avaris/ingest/injuries.py:308`). ADR-004 says preseason games are predicted at full strength (`ADR.md:151-155`).
- **ESPN has the information, but in the note.** ESPN's `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries` returns every team's list in one call. Brunson, Towns and Anunoby were status `Day-To-Day`; that they would rest was only in `shortComment` ("won't play Tuesday against Toronto for rest purposes"). The endpoint has no history: it only shows the current list.
- **Preseason never feeds features.**
  - Result events (and so `PlayerTracker.add_game`) are skipped for preseason (`src/avaris/features/build.py:146-152`).
  - Preseason availability is forced to NaN (`build.py:223-227`).
  - `_played` reads every `player_games` row with no `season_type` filter (`build.py:97-114`). So preseason box scores must **not** go into `player_games`.
- **Player value already exists.** It is `rate × minutes` (`build.py:236-262`). `PlayerTracker.rate()` returns last season's rate in the offseason (`src/avaris/features/availability.py:43-50`). `PlayerTracker.members()` only returns players with `season == season`, so it is empty before a team's first regular-season game (`availability.py:52-57`).
- **Preseason box scores are available.**
  - `leaguegamelog` with `SeasonType=Pre Season`, `PlayerOrTeam=P` returned 2,194 rows for 2018-19 (verified 2026-10-13). There is one call per season.
  - `log_season_types` does not include it today (`src/avaris/ingest/endpoints.py:37-43`).
  - The DB has about 1,000 finished preseason games from 2012-13 to 2025-26 and no preseason player rows. 89 of 1,188 preseason games have a non-NBA opponent (see issue #11).
- **The win probability comes from a separate model.**
  - `p_home_win` is the `home_win` model's own output, not derived from the margin normal (`src/avaris/models/predictor.py:40`). So the win adjustment works on the log-odds scale with its own coefficient, not through `Φ(μ/σ)`.
  - σ is the preseason bucket's (`src/avaris/models/distributions.py:22-37`). The 80% interval is computed at read time from μ and σ (`src/avaris/api/routes/predictions.py:24-25`), so an adjusted μ moves the interval by itself.
- **Predictions pipeline.**
  - Rows are built in `prediction_rows` (`src/avaris/pipeline/daily.py:216-250`) and written by `write_predictions` (`daily.py:253`).
  - A provisional row is rewritten only when a `COMPARED` column changes (`daily.py:37-41`). Final rows are never replaced (ADR-018).
  - Scoring reads the stored `p_home_win`, `margin_mu` and `margin_sigma` (`src/avaris/pipeline/score.py:10,42`).
- **`feature_hash` and the refresh step.**
  - `feature_hash` is built only from `FEATURE_VERSION` and `MODEL_FEATURES` (`build.py:45-47`). A new non-model frame does not invalidate production models.
  - The daily refresh is `source_refresher`: `ingest_stats`, then `ingest_injuries` (`daily.py:83-99`). `run_daily` runs refresh, then features, predict and score (`daily.py:291-330`).
- **Supporting code to reuse.**
  - Name matching: `PlayerIndex.find(season, team_id, printed)` (`src/avaris/ingest/injuries.py:139-180`) and `normalize_name` (`injuries.py:124`). It is built from `rosters`, and 2026-27 rosters exist (637 rows).
  - Team names to ids: `team_ids_by_name` (`src/avaris/ingest/teams.py`).
  - Walk-forward predictions, preseason rows included: `walk_forward(...)` returns `game_id, season, season_type, y, pred, sigma` (`src/avaris/backtest/walkforward.py:24,59-64`). Data comes from `with_targets(build_features(con).features, con)` (`src/avaris/pipeline/jobs.py:194`).
- **Tests and fixtures.**
  - HTTP is mocked with respx, and any unmocked host fails (`tests/conftest.py:46-64`). Recorded stats JSON lives in `tests/fixtures/stats/`.
  - `synthetic_db` (`tests/conftest.py:67`). The synthetic league has two preseason rounds (`tests/fixtures/synthetic.py:235`).
  - Daily fixtures are in `tests/integration/test_daily.py`.
  - The Playwright server runs with a frozen clock at 2021-11-27 (`tests/fixtures/web_server.py:56`), and no preseason game falls on its Today date.
- **Web.**
  - Types: `web/src/lib/types.ts:53-73`.
  - Card: `web/src/components/today/game-card.tsx:76-78`.
  - Game page: `web/src/components/game/game-view.tsx:59-63`.
  - Edge tab: it reads `p.p_home_win`, `p.margin` and `p.total` (`web/src/components/edge/edge-view.tsx:169-191`).

**Key files:**

| File                                     | Why it matters                                                                  |
| :--------------------------------------- | :------------------------------------------------------------------------------ |
| `src/avaris/features/build.py`           | `_Loop.decision()` has the `PlayerTracker` state as of `decision_ts`; the rest values are computed here |
| `src/avaris/features/availability.py`    | `PlayerTracker.rate()`: last-season player value                               |
| `src/avaris/pipeline/daily.py`           | Refresh order, `prediction_rows`, `COMPARED`, `write_predictions`              |
| `src/avaris/ingest/injuries.py`          | `PlayerIndex`, `normalize_name`, the client pattern (throttle, cache, retry)    |
| `src/avaris/ingest/nba_stats.py`         | `parse_player_log`, reused for preseason logs                                  |
| `src/avaris/backtest/walkforward.py`     | Walk-forward predictions used to fit and validate k                            |
| `src/avaris/api/routes/predictions.py`   | `prediction_view` adds the `rest` block                                        |
| `web/src/components/edge/edge-view.tsx`  | Uses the adjusted values automatically; gets a label                           |

---

## 3. Decisions

| Decision                         | Choice                                                                                                                            | Why                                                                                                                         |
| :------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------- |
| Model vs rule                    | A rule after the model; the model gets no new inputs and is not retrained                                                         | User request; keeps the model and the regular season untouched                                                              |
| Scope                            | Preseason games only (`season_type = 'preseason'`), enforced at ingest, features, prediction, API and UI                           | User: "make sure this is only for preseason"                                                                                |
| Outputs adjusted                 | Margin, total and win probability                                                                                                  | User choice                                                                                                                 |
| Win-probability link             | `logit(p_adj) = logit(p) − k_win·(home_lost − away_lost)`, with its own k                                                          | `p_home_win` comes from its own model (`predictor.py:40`); `Φ(μ_adj/σ)` would mix two different links                        |
| Margin and total                 | `margin_mu − k_margin·(home_lost − away_lost)`; `total_mu − k_total·(home_lost + away_lost)`; σ unchanged                           | One coefficient each, fitted on residuals                                                                                   |
| Ship gate                        | Each k is fitted on 2015-16 to 2019-20 and switched on only if it beats raw on 2020-21 to 2024-25 (log loss, margin MAE, total MAE respectively); otherwise k = 0 and only the ESPN list is shown | User choice; tuning-window rule (CLAUDE.md); 2025-26 holdout untouched                                                      |
| Who counts as out (ESPN)         | Status `Out`, **or** the note matches won't play / won't suit up / ruled out / will rest / sit out / not play, and the entry was posted within 36 h before tip-off | User choice; tonight's rests were only in the note                                                                          |
| Display                          | Adjusted numbers are the headline for preseason games, labelled "Rest-adjusted (ESPN)", with raw values and the out list shown; the Edge tab uses adjusted with the same label | User choice                                                                                                                 |
| Where preseason box scores live  | A new `preseason_player_games` table, never `player_games`                                                                         | `_played` reads `player_games` unfiltered (`build.py:97-114`); a separate table means they cannot leak into features         |
| Where rest values live           | A new `FeatureSet.rest` frame, not columns on `features`                                                                           | The `features` table, `MODEL_FEATURES` and `feature_hash` stay byte-identical                                               |
| Point in time                    | A game uses the latest ESPN snapshot with `fetched_at ≤ decision_ts`; none means no adjustment                                     | Same rule as injury reports (ADR-003, leakage test)                                                                          |
| **Important!** Finals without a snapshot | There is no scheduler, so a preseason final is adjusted only if a refresh ran between tip − 36 h and tip − 60 min. If the app is first opened inside the last hour, the final has no adjustment, permanently (finals are never rewritten, ADR-018) | Keeps the decision-time guarantee; the `rest` block says so                                                                  |
| Gate reads 2020-21 to 2024-25    | A narrow exception to ADR-002 ("frozen for 2020-21+"): those seasons only decide on/off for each k, never its value; ADR-022 records this | Needs out-of-sample evidence; 2025-26 stays untouched                                                                       |
| Server and CLI                   | `ingest espn`, `ingest preseason-logs` and `rest-fit` open DuckDB directly like `ingest injuries` (`src/avaris/cli.py:131-133`), so they run with the server down; live, ESPN runs inside `daily` | Single-writer rule; no new job route                                                                                         |
| Testing                          | TDD for all deterministic code (CLAUDE.md); the k fit is tested on synthetic data, and the real fit is reported after the fact      | Repo policy; model tuning may be test-after                                                                                  |

---

## 4. Assumptions

| Assumption                                                                                                                         | Basis                                                                      | Impact if false                                                                                                     |
| :--------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------ |
| The ESPN endpoint stays reachable without auth and keeps the fields `injuries[].displayName`, `injuries[].injuries[].athlete.displayName`, `status`, `date`, `shortComment` | One live call on 2026-10-13                                                | The ingest fails soft (a warning, no adjustment); fix the parser                                                     |
| Players absent from a team's preseason box score (among players who appeared for that team in any game of that preseason) are the historical "out" set | Box scores list only players who played                                    | k is biased by players cut or traded mid-preseason; the validation gate catches a bad k                              |
| ESPN's live list is close enough to the actual absences used for fitting                                                           | It listed tonight's three NYK rests                                        | Live gains are smaller than the backtest; the backtest overstates the benefit (risk below)                           |
| An ESPN player name plus ESPN team resolves to an NBA `player_id` through `PlayerIndex` built on this season's `rosters`             | `PlayerIndex` already resolves names printed in NBA PDFs; 2026-27 rosters exist | Unmatched players get value 0 and are shown as unmatched in the UI                                                   |
| `walk_forward` with the production rung and parameters over 2015-16 to 2024-25 runs in reasonable time on this machine              | `avaris evaluate` already runs walk-forward over these seasons             | Slow fit; it is a one-off CLI command, not part of daily                                                             |

---

## 5. Allowed Changes

**Files to create:**

| File                                         | Contents                                                                                                                                         |
| :------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/avaris/ingest/espn.py`                  | `ESPN_INJURIES_URL`, `EspnClient` (throttle, timeout, retry, raw cache under `cache_dir/live/espn/`), `parse_espn_injuries(payload) -> DataFrame`, `is_out(status, comment, entry_ts, tip_utc, window_h) -> bool`, `ingest_espn(con, client, now_utc)` (fetches only when a preseason game is due) |
| `src/avaris/ingest/preseason_logs.py`        | `ingest_preseason_logs(con, client, seasons)`: `leaguegamelog` `Pre Season`/`P` into `preseason_player_games`                                         |
| `src/avaris/preseason/__init__.py`           | Empty                                                                                                                                            |
| `src/avaris/preseason/rest.py`               | `RestParams` (k_margin, k_total, k_win, enabled flags), `load_params(con)`, `apply_rest(row, rest, params) -> row` (no-op unless `season_type == 'preseason'`) |
| `src/avaris/preseason/fit.py`                | `fit_rest(con, settings) -> RestFit`: walk-forward preseason residuals, fit on 2015-16..2019-20, gate on 2020-21..2024-25, writes `rest_params` and a report |
| `tests/unit/test_espn.py`                    | Parser, out rule, 36 h window, team and name mapping                                                                                             |
| `tests/unit/test_rest.py`                    | `apply_rest` maths, non-preseason no-op, disabled-k pass-through                                                                                 |
| `tests/integration/test_ingest_espn.py`      | respx-mocked ingest; no request on a day with no preseason game due                                                                              |
| `tests/integration/test_preseason_logs.py`   | respx-mocked `Pre Season` log into `preseason_player_games`; `player_games` untouched                                                             |
| `tests/integration/test_rest_preseason_only.py` | Features, `feature_hash` and non-preseason prediction rows are byte-identical with and without ESPN snapshots, preseason logs and `rest_params`; leakage: snapshots after `decision_ts` change nothing |
| `tests/integration/test_rest_fit.py`         | `fit_rest` on the synthetic league recovers a planted k and switches it off when it does not beat raw                                            |
| `tests/fixtures/espn/injuries.json`          | Recorded ESPN payload (trimmed: NYK, TOR plus one regular-status entry)                                                                          |
| `tests/fixtures/stats/leaguegamelog/<preseason file>` | Recorded `Pre Season` player log for one synthetic season, made by `make_stats_fixtures.py`                                                  |
| `web/src/components/game/rest-section.tsx`   | Out list per side (name, status, note, value, unmatched flag), raw and adjusted numbers                                                          |
| `web/src/components/game/rest-section.test.tsx` | Renders the list, labels and raw values; renders nothing when `rest` is null                                                                  |

**Files to modify:**

| File                                         | Change                                                                                                                       | Anchor                                         |
| :------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------- | :--------------------------------------------- |
| `src/avaris/db.py`                           | Append migration 8 (schema below)                                                                                             | `MIGRATIONS` list end                          |
| `src/avaris/config.py`                       | `EspnSettings(enabled=True, min_interval_s=1.0, timeout_s=20, max_attempts=3, out_window_hours=36)`; `Settings.espn`           | after `InjurySettings`                         |
| `config.toml`                                | `[espn]` block                                                                                                                 | after `[injuries]`                             |
| `src/avaris/ingest/endpoints.py`             | `PRESEASON_LOG_TYPE = "Pre Season"` (not added to `log_season_types`)                                                          | constants                                      |
| `src/avaris/features/build.py`               | `FeatureSet.rest` frame; `_Loop` loads `espn_injury_snapshots` and `preseason_player_games`; in `decision()`, **only when preseason**, append per side `lost_espn`, `lost_actual` and the player list valued with `self.players.rate(pid, season)` | `FeatureSet`, `_Loop.__init__`, `_Loop.decision` |
| `src/avaris/pipeline/daily.py`               | `source_refresher` calls `ingest_espn` after `ingest_injuries` (soft-fail warning); `prediction_rows` calls `apply_rest` and writes `raw_*` and `rest`; add `rest` to `COMPARED` | `source_refresher`, `prediction_rows`, `COMPARED` |
| `src/avaris/cli.py`                          | `ingest espn`, `ingest preseason-logs`, `rest-fit` commands                                                                     | `ingest_app`, `app`                            |
| `src/avaris/api/routes/predictions.py`       | `prediction_view` adds `rest` (null unless preseason with a rest row)                                                          | `prediction_view`                              |
| `tests/conftest.py`                          | respx route for the ESPN host serving the fixture                                                                              | `stats_api` fixture block                      |
| `tests/fixtures/make_stats_fixtures.py`      | Also write a `Pre Season` player log fixture                                                                                   | fixture writer                                 |
| `tests/integration/test_daily.py`            | Preseason game gets adjusted values plus a `rest` block; regular game unchanged                                                | new tests                                      |
| `tests/integration/test_api.py`              | `rest` block shape; null for non-preseason                                                                                     | new tests                                      |
| `tests/unit/test_db.py`                      | Migration 8 applies on a fresh and on a v7 DB                                                                                  | new test                                       |
| `tests/unit/test_config.py`                  | `espn` defaults and env override                                                                                               | new test                                       |
| `web/src/lib/types.ts`                       | `Rest` type; `Prediction.rest: Rest \| null`                                                                                    | `Prediction`                                   |
| `web/src/components/today/game-card.tsx`     | "Rest-adjusted (ESPN)" label, raw win % beside it when `rest` is present                                                       | near `WinBar`                                  |
| `web/src/components/today/game-card.test.tsx` | Label and raw value shown only with `rest`                                                                                    | new tests                                      |
| `web/src/components/game/game-view.tsx`      | Render `RestSection` when `rest` is present                                                                                    | after injuries section                         |
| `web/src/components/edge/edge-view.tsx`      | Note "Preseason: rest-adjusted from ESPN list (raw x%)" when `rest` is present                                                 | header of the market cards                     |
| `web/src/components/edge/edge-view.test.tsx` | Note shown only with `rest`                                                                                                    | new test                                       |
| `web/src/test/data.ts`                       | A preseason prediction fixture with `rest`                                                                                     | fixtures                                       |
| `ADR.md`                                     | ADR-022 (ESPN as preseason-only rest source; amends ADR-004 "predicted at full strength")                                       | top of file                                    |
| `README.md`                                  | Data sources (ESPN, preseason only), tables, new commands                                                                      | `## Injury reports`, `## Data`                 |
| `CHANGELOG.md`                               | `### Added` entry                                                                                                              | `## Unreleased`                                |
| `STATUS.md`                                  | Note under current status                                                                                                       | top section                                    |
| `CLAUDE.md`                                  | Architecture data-flow line mentions ESPN for preseason rest only                                                              | `## Architecture` → Data flow item 1           |
| `docs/plans/avaris-nba-analytics-model-build-plan.md` | Data sources row; risk "Preseason predictions ignore who actually plays" points to ADR-022                             | `:27`, `:223`                                  |

**Files to delete:**

None

**Dependencies:**

None (httpx, tenacity and respx are already used)

**Schema changes (migration 8):**

| Object                    | Change                                                                                                                                                                                  | Rollback                          |
| :------------------------ | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :-------------------------------- |
| `espn_injury_snapshots`   | New: `fetched_at timestamp, team_id integer, player_name varchar, player_id integer null, status varchar, comment varchar, entry_ts timestamp null`, pk `(fetched_at, team_id, player_name)` | `drop table`                      |
| `preseason_player_games`  | New: same columns as `player_games` (`db.py:41-55`), pk `(game_id, player_id)`                                                                                                          | `drop table`                      |
| `rest_params`             | New: `fitted_at timestamp pk, k_margin double, k_total double, k_win double, use_margin boolean, use_total boolean, use_win boolean, report varchar` (JSON metrics)                     | `drop table`                      |
| `predictions`             | Add `raw_p_home_win double, raw_margin_mu double, raw_total_mu double, rest varchar` (JSON), all null for non-preseason                                                                 | `alter table … drop column` ×4    |

---

## 6. Implementation Plan

Branch `feat/preseason-rest-adjustment` from `main` after `feat/idle-shutdown` is committed (its uncommitted work must not be mixed in).

1. **Schema.** In `src/avaris/db.py` append migration 8. Test first in `tests/unit/test_db.py`.
2. **Config.** Add `EspnSettings` to `src/avaris/config.py` and the `[espn]` block to `config.toml`. Test first in `tests/unit/test_config.py`.
3. **Preseason logs.** Record the fixture with `tests/fixtures/make_stats_fixtures.py`. Write `tests/integration/test_preseason_logs.py`. Then add `PRESEASON_LOG_TYPE` to `endpoints.py`, `src/avaris/ingest/preseason_logs.py` (reusing `parse_player_log`) and the `avaris ingest preseason-logs --seasons` command in `cli.py`. It writes only to `preseason_player_games`.
4. **ESPN ingest.** Record `tests/fixtures/espn/injuries.json` and the respx route in `tests/conftest.py`. Write `tests/unit/test_espn.py` and `tests/integration/test_ingest_espn.py`. Then add `src/avaris/ingest/espn.py` and the `avaris ingest espn` command.
   - `ingest_espn` returns without a request unless a preseason game has `tip_off_utc` in (now, now + 36 h] and no final prediction.
   - Players resolve through `PlayerIndex` and teams through `team_ids_by_name`.
5. **Rest values in features.** Write the preseason-only and leakage tests in `tests/integration/test_rest_preseason_only.py`, then change `src/avaris/features/build.py`:
   - Add `FeatureSet.rest`. In `_Loop.decision()`, only when `preseason` and both teams are NBA teams, compute per side:
     - `lost_espn`: the sum of `rate × minutes` over players in the latest snapshot with `fetched_at ≤ decision_ts` who pass `is_out`.
     - `lost_actual`: the sum over that team's players for the season in `preseason_player_games` who did not appear in this game; NaN if the game has no box score yet.
     - the player list.
   - Non-preseason games add no `rest` rows. `features`, `MODEL_FEATURES` and `FEATURE_VERSION` are unchanged.
6. **Adjustment.** Write `tests/unit/test_rest.py`, then add `src/avaris/preseason/rest.py`.
   - `apply_rest` returns the row unchanged unless `season_type == 'preseason'`, a rest row exists, and at least one k is enabled.
   - Otherwise it moves the original values to `raw_*`, applies the formulas in §3, and builds the `rest` JSON: per side lost value and players (status, note, value, matched), k values, `snapshot_ts`.
7. **Daily.** Extend `tests/integration/test_daily.py`, then change `src/avaris/pipeline/daily.py`:
   - `source_refresher` calls `ingest_espn` after `ingest_injuries`; a failure is a warning.
   - `prediction_rows` calls `apply_rest` with `load_params(con)` and `fs.rest`.
   - Add `rest` to `COMPARED`.
8. **Fit.** Write `tests/integration/test_rest_fit.py`, then add `src/avaris/preseason/fit.py` and `avaris rest-fit`.
   - Walk-forward the three targets with production rungs and parameters over 2015-16 to 2024-25.
   - Keep preseason games with NBA opponents and a non-NaN `lost_actual`.
   - Fit on 2015-16 to 2019-20:
     - `k_margin`: OLS without intercept of (y − pred) on Δlost.
     - `k_total`: the same on the summed lost.
     - `k_win`: one-dimensional logistic regression with `logit(pred)` as offset.
   - Score raw vs adjusted on 2020-21 to 2024-25 and enable each k only if it is better.
   - Insert into `rest_params` and print the report.
   - Never read 2025-26.
9. **API.** Extend `tests/integration/test_api.py`, then make `prediction_view` in `src/avaris/api/routes/predictions.py` return `rest` (parsed JSON or null).
10. **Web.** Write the tests first (`rest-section.test.tsx`, `game-card.test.tsx`, `edge-view.test.tsx`, `web/src/test/data.ts`), then change `types.ts`, `rest-section.tsx`, `game-card.tsx`, `game-view.tsx` and `edge-view.tsx`. Read the relevant Next.js docs in `node_modules/next/dist/docs/` first (CLAUDE.md).
11. **Real run.** Stop the server first (single writer). These need network: `avaris ingest preseason-logs --seasons 2014-15..2024-25` with `allowed_domains: ["stats.nba.com"]`, then `avaris rest-fit`. Then `avaris ingest espn` with `allowed_domains: ["site.api.espn.com"]` and `avaris daily`. Record the fit report in ADR-022.
12. **Docs.** Update ADR-022, `README.md`, `CHANGELOG.md`, `STATUS.md`, `CLAUDE.md` and the build plan.
13. **Gates.** Run `uv run ruff check`, `uv run pyright`, `uv run pytest`, `uv run pytest -m e2e`, and in `web/`: `npm run lint && npm run typecheck && npm run test && npm run build && npm run test:e2e`.

**Testing approach:** TDD for every deterministic step (1–7, 9, 10), per CLAUDE.md. The fit logic (8) is tested on synthetic data with a planted k; the real coefficients are reported after the run, which is allowed for model tuning. The existing Playwright E2E must stay green. The synthetic Today date has no preseason game, so a preseason page check is covered by the component tests.

---

## 7. Scope

**In scope:**
- ESPN injury snapshots for days with a preseason game due.
- Historical preseason player box scores in their own table.
- Three fitted, gated coefficients.
- The preseason-only adjustment of win, margin and total.
- API `rest` block; card, game page and Edge tab labels.
- ADR-022 and docs.

**Out of scope:**
- ESPN for regular season, play-in or playoffs: NBA reports cover those (ADR-003/004).
- Any change to model features, `MODEL_FEATURES`, training or the model ladder.
- Non-NBA preseason opponents (#11): those games get no adjustment.
- Win model overconfident in preseason compared with its own margin: #20.
- The 2025-26 holdout.

---

## 8. Acceptance Criteria

- [ ] `uv run pytest tests/integration/test_rest_preseason_only.py` passes. With ESPN snapshots, preseason logs and `rest_params` present:
  - every non-preseason `features` row, `feature_hash` and `predictions` row equals the run without them;
  - ESPN snapshots with `fetched_at > decision_ts` change no game's rest values.
- [ ] On a fixture day with only regular-season games, `avaris daily` makes zero requests to the ESPN host (respx call count 0).
- [ ] `preseason_player_games` is filled by `avaris ingest preseason-logs`, and `player_games` row counts are unchanged.
- [ ] `avaris rest-fit` prints k values and raw vs adjusted metrics for 2020-21 to 2024-25. A k that does not beat raw is stored disabled.
- [ ] For a preseason game with an enabled k and listed players, `/api/predictions/today` returns adjusted `p_home_win`, `margin.mu` and `total.mu` that differ from the `rest.raw_*` values, and `rest.home.players` lists the out players. For any other game, `rest` is null.
- [ ] The game card, game page and Edge tab show "Rest-adjusted (ESPN)" with the raw value for a preseason prediction with `rest`, and nothing new otherwise (vitest).
- [ ] All Python and web gates, including both E2E suites, are green.

---

## 9. Definition of Done

- [ ] All acceptance criteria are met on branch `feat/preseason-rest-adjustment`.
- [ ] ADR-022 records the fit report (k values, validation metrics, which outputs are enabled).
- [ ] `README.md`, `CHANGELOG.md`, `STATUS.md`, `CLAUDE.md` and the build plan are updated.
- [ ] ADR-022 links #20 (win model preseason overconfidence) and #11 (non-NBA preseason opponents).
- [ ] `git status` is clean; the work is committed and the user has been asked before pushing.

## 10. Risks and Open Questions

| Risk / question                                                                  | Impact                                                    | Mitigation                                                                                                                  |
| :------------------------------------------------------------------------------- | :-------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------- |
| k is fitted on actual absences, but live input is ESPN's list, which misses late rest calls | Live gain is smaller than the backtest                    | State this in ADR-022 and the UI note; the raw number is always shown                                                       |
| No ESPN snapshot taken before `decision_ts` (the app was first opened after tip − 60 min) | The final prediction has no adjustment                    | The `rest` block says "no snapshot before decision time"; provisional predictions from earlier refreshes still carry it     |
| A note keyword refers to a different game ("won't play Saturday")                | False out                                                 | 36 h window on `entry_ts`; the raw note is shown in the UI                                                                   |
| Historical "out" includes players cut mid-preseason                              | Biased k                                                  | Validation gate; restrict the team's player set to players with ≥ 1 regular-season game for that team the previous season or that season |
| ESPN changes or blocks the endpoint                                              | No adjustment                                             | Soft-fail warning in daily; the model prediction stands                                                                      |
| Preseason is nearly over for 2026-27                                             | Live benefit mostly next October                          | Accepted by the user                                                                                                         |
| Adjusted preseason predictions are what get scored                               | Preseason live scores mix model and adjustment            | Preseason is reported separately; `raw_*` columns allow scoring raw too                                                      |
