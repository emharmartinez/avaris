# Plan: Avaris — personal NBA analytics model (win probability, margin, total)

## Context
Build a personal ML system that predicts every NBA game's win probability, point margin and total points, explains each prediction, and shows team strength and injury impact in an installable desktop PWA.

User decisions:
- Build in `~/avaris`.
- **2026-10-12 pivot:** Avaris is a sports analytics model, not a betting model. **The Odds API is dropped**: no odds data, no market comparison, no bets, no spend tracking.
- v1 = the full app, including injuries/lineups.
- Desktop UI = **Next.js + shadcn/ui PWA + FastAPI**.
- **Personal, single-user, local-only:** no accounts, auth, hosting, multi-tenancy or billing code.

The goal is accurate, well-calibrated predictions with honest uncertainty. All evaluation uses proper scoring rules (log loss, Brier, MAE, RMSE, calibration and interval coverage), walk-forward, against an Elo baseline and naive baselines.

**Decisions taken in this revision (the user can reopen any of them):**
1. **Targets stay:** `home_win`, `margin` and `total`, each with a predictive distribution. Spread and total become "projected margin and total with an interval", not lines to beat.
2. **Analytics outputs in v1:** game predictions with intervals, per-game prediction drivers (LightGBM feature contributions), team ratings and trends (Elo, net rating, pace), and injury impact per team. All four reuse what the features already compute.
3. **Not in v1:** season simulation (projected wins, play-in and playoff odds), player-level projections, and an external market benchmark from a free historical lines dataset. All three are follow-ups.
4. **Predictions cover every game, preseason included** (revised 2026-10-12 at the user's request), plus play-in and playoffs. Headline metrics are on the regular season; preseason, play-in and playoffs are reported separately. Preseason results never feed features. See "Non-standard games".
5. **No scheduler.** Nothing has to be captured at tip-off anymore, and injury PDFs stay on the CDN, so `avaris daily` is idempotent and catches up whenever it runs. `avaris serve` runs it on startup and the UI has a Refresh button.

## Stack
| Layer | Choice |
|---|---|
| Python env | Python 3.12 + **uv**; ruff, pyright, pytest |
| Stats data | **stats.nba.com via a thin httpx client** (ADR-009; replaces `nba_api`): `leaguegamelog` per season and season type covers every team-game and player-game line; `commonteamroster` for rosters; `scheduleleaguev2` per season supplies tip-off time (back to 2012-13), `season_type`, venue and today's slate |
| Injuries | Official NBA pregame injury report PDFs (2021-22+), fetched by Avaris and parsed with `nba-injury-report` (AGPL, fine for personal use; ADR-012). Hourly reports until 2025-12-21, every 15 minutes from 2025-12-22 |
| Storage | **DuckDB** file + raw JSON/PDF response cache; pandas |
| Models | scikit-learn (Elo/logistic/ridge baselines, isotonic calibration, time-series CV), **LightGBM** (also gives per-prediction feature contributions), Optuna, scipy |
| Artifacts | joblib + JSON metadata (features, train window, metrics) |
| CLI / config | Typer; pydantic-settings + `config.toml`. No API keys or secrets |
| Testing | Python: pytest, pytest-cov, hypothesis (property tests), respx (httpx mocks), time-machine (frozen clock), pytest-xdist (optional). Web: Vitest + React Testing Library (+ user-event, jest-dom), jsdom (component tests only), msw (API mocks), **Playwright** for UI E2E |
| API | **FastAPI** + uvicorn on `localhost:8000`; also serves the statically exported PWA |
| Desktop UI | **Next.js (App Router, `output: 'export'`) + TypeScript + Tailwind v4 + shadcn/ui**, TanStack Query, shadcn charts (Recharts). PWA via `app/manifest.ts` + a service worker caching the app shell. Installed from Windows Chrome ("Install app"), so it opens in its own window. Localhost counts as a secure context, so the PWA works without HTTPS. |

## Key design
- **Targets:**
  - `home_win`: classifier giving the home win probability.
  - `margin`: regressor giving a normal predictive distribution N(μ, σ) of home margin. P(home wins by more than X) = Φ((μ − X)/σ).
  - `total`: regressor giving N(μ, σ) of total points, with P(total > X) the same way.
  - σ is fitted from out-of-fold residuals. Each prediction shows μ and an 80% interval.
- **Model ladder:**
  1. Elo baseline: margin of victory, home advantage, carryover between seasons.
  2. Logistic/ridge regression.
  3. LightGBM tuned with Optuna.
  Each target keeps a rung only if it beats the one below on walk-forward log loss or MAE. Isotonic calibration of classifiers is a per-target option chosen on the tuning window (off for `home_win`, ADR-016).
- **Decision timestamp (`decision_ts`):** every final prediction is made "as of" one instant per game, and the injury report and features are frozen at it.
  - Default `decision_ts` = latest injury report at or before **tip-off − 60 min** (the 5:30 pm ET report covers 7 pm tips). If no report exists for the game (all of 2020-21 and earlier, every preseason game, or a missing day), `decision_ts` = tip-off − 60 min. The NBA publishes no injury report on preseason days (the CDN returns 403).
  - Backtests and live use the same rule. The leakage test checks at timestamp granularity, not date granularity: deleting rows with `ts > decision_ts` leaves that game's features unchanged.
  - Live `daily` writes a **provisional** prediction for a game before its `decision_ts` (latest report so far) and a **final** one once `decision_ts` has passed. Only final predictions are scored.
- **Time and game identity:** all timestamps stored in UTC; `game_date` is the **ET** calendar date of tip-off (10:30 pm ET tips are the same day). `games` carries `tip_off_utc`, `game_date_et`, `season_type` (preseason, regular, cup_final, play_in, playoffs) and `neutral_site`.
- **Non-standard games:**
  - **Preseason** is stored in `games` (with scores, about 1,150 finished games since 2012-13; no box logs) and is predicted and scored like any other game:
    - Its results never update Elo, form or availability features (no box logs, rotations are not representative). A preseason game's features are each team's state as of `decision_ts`, which is mostly the end of the previous season.
    - Availability: with no injury report and no minutes, a preseason game is predicted at full strength (availability features missing).
    - Training rows include preseason with `season_type` as a feature. σ is fitted per `season_type` bucket (preseason, regular, postseason) so preseason intervals are not borrowed from the regular season.
    - Unknown venues (common in preseason, which the venue check skips per ADR-010): `travel_km` and `tz_shift` missing; `home_court` follows `neutral_site`.
    - A game without `tip_off_utc` (one in 2015-16) is not predicted.
  - Training uses all predicted game types with `season_type` as a feature; Elo updates on regular season, play-in and playoffs only. Headline metrics cover the regular season; preseason, play-in and playoffs are reported separately (different home court and rest effects, small sample).
  - Neutral-site games (2019-20 bubble, Paris/Mexico City/London, NBA Cup final): `home_court = 0`, `travel_km` and `tz_shift` computed to the actual venue. The bubble sits inside the tuning window, so this must be in before Phase 3 tuning.
- **Features** are computed strictly as of `decision_ts`:
  - Elo.
  - Exponentially weighted ORtg, DRtg, pace and net rating, plus last-N windows.
  - Rest, back-to-back, 3 games in 4 nights, travel km and time-zone shift (arena CSV), altitude.
  - Home court, adjusted for the 2020-21 no-fans season.
  - Games played this season.
  - **Availability:** decay-weighted per-minute Game Score × expected minutes. Strength lost = full-strength sum minus available sum.
    - Training and backtests use who actually played. Live predictions use the injury report at `decision_ts`: Out and Doubtful count as absent; Questionable counts as 50%. The Phase 4 injury-report re-run measures the gap between the two.
    - Players with no games this season (rookies, new signings) fall back to last season's rate, else 0.
    - **No phantom absences:** a traded player leaves team A's set as soon as he appears for team B. Season rosters, plus a rule that 10+ straight misses with no injury-report entry means "off roster", cover waivers, two-way and G-League moves.
- **Analytics outputs** (all stored with the prediction or derived from features, no new data source):
  - **Drivers:** the top feature contributions per prediction (LightGBM `pred_contrib`, or coefficient × value for linear rungs), grouped into families (form, rest/travel, availability, home court, Elo).
  - **Team ratings:** Elo, EW ORtg/DRtg/net rating and pace per team over time, as of each game.
  - **Injury impact:** strength lost per team and the players behind it, from the availability feature.
- **Walk-forward evaluation:** train on seasons before S, test on S, retraining weekly inside the season. Models train from 2012-13; the scored evaluation runs 2020-21 to 2024-25. **2025-26 is a holdout, used once.**
- **Metrics:**
  - `home_win`: log loss, Brier, accuracy, reliability diagram, expected calibration error.
  - `margin` and `total`: MAE, RMSE, 80% interval coverage (target 78-82%), PIT histogram.
  - Every metric is shown against Elo and two naive baselines (home team always at the season's home win rate; season-to-date net rating difference), with a bootstrap confidence interval over games.
- **Tuning splits (no tuning on scored seasons):**
  - Optuna tuning and rung selection use walk-forward over **2015-16 to 2019-20** only. Hyperparameters and the kept rung are then **frozen** for 2020-21+.
  - **Compute budget:** Optuna trials run with **one refit per season** (5 fits per trial per target). Only the final rung comparison and the 2020-21+ evaluation use weekly refits. Trial count and `n_jobs` live in `config.toml`; every trial is logged to Optuna's SQLite storage so tuning is resumable.
- **Production training:**
  - `avaris train --through DATE` refits the kept rung per target on every game that tipped off before `DATE`, with the frozen hyperparameters. Calibration and σ come from out-of-fold predictions.
  - Each run writes `artifacts/models/<target>/<run_id>/` with `model.joblib` and `meta.json`: train window, feature list + feature hash, hyperparameters, seed, git SHA, package versions and OOF metrics.
  - `artifacts/models/registry.json` points to the production artifact per target. A new artifact is promoted automatically only if its feature hash matches the current feature builder, it has more training rows than the previous artifact, and its OOF metrics are within `promote_tolerance` of the previous artifact's. Otherwise it stays a candidate, and `daily` warns. `avaris train --promote RUN_ID` is the manual override (needed after any hyperparameter or rung change, which first requires a new walk-forward run).
  - `daily` refuses to predict with an artifact whose feature hash does not match the current feature builder.
  - **Cadence:** weekly, matching the backtest. `avaris daily` runs `train` first when the production artifact is older than `retrain_every_days` (default 7).
  - **Reproducibility:** fixed `seed` in `config.toml`, recorded in `meta.json`.
- **DuckDB allows one writer process.** The FastAPI server owns the read-write connection. CLI jobs run in-process when the server is down, or through `POST /api/jobs/{daily,score,train}` when it's up. The UI only reads DuckDB and never calls external APIs.
  - **Jobs:** `POST /api/jobs/*` returns a `job_id` immediately and runs the job in a background thread. `GET /api/jobs/{job_id}` reports status, progress and log tail. A single process-wide lock allows one job at a time; a second request gets `409`. Jobs are recorded in a `jobs` table.
- **Stats cache freshness:** cached stats responses are immutable for finished seasons. For the in-progress season, `ingest stats` refetches the last `refetch_days` (default 7) of game logs on every run so stat corrections land.

## Testing approach
- **TDD by default:** write a failing test first, make it pass, then refactor. This applies to all deterministic code:
  - Cache, Elo, features, availability rules, distributions, interval math, drivers grouping, metrics, API routes.
  - `decision_ts` resolution, provisional vs. final status, ET game-date mapping, `season_type` and neutral-site tagging, preseason never feeding features.
  - Training plumbing: `--through` cutoff, registry promotion and refusal rules, feature-hash check, retrain staleness trigger.
  - Jobs: job lock (`409`), job status, `daily` idempotence and catch-up (frozen clock via `time-machine`).
  - Web: data hooks, formatters, and components with logic (Vitest + React Testing Library).
- **Vitest environments (jsdom is slow, so use it only where a DOM is needed):**
  - Default environment is `node`. Two Vitest `projects`: `*.test.ts` runs in `node`, `*.test.tsx` runs in `jsdom`.
  - `node`: formatters, API client, query keys, data transforms, probability and interval display math, msw handlers (`msw/node`).
  - `jsdom`: component rendering, user interaction, and hooks tested with `renderHook`.
  - Keep logic out of components (plain `.ts` modules) so most tests stay in `node`.
- **Test-after is allowed only** for exploratory model tuning and report styling. Tests must still exist before the phase is done.
- **No live network in tests.** Use recorded stats and injury responses from the cache, plus a small fixture DuckDB built by `tests/fixtures/`.
- **E2E tests:**
  1. **Pipeline E2E** (pytest, `@pytest.mark.e2e`): fixture responses → `avaris train` → `avaris daily` → `avaris score`. Asserts on provisional and final predictions, drivers and per-game scores.
  2. **UI E2E** (Playwright, `web/e2e/`): starts `avaris serve` on the fixture DB, then checks that every page renders real data, Today shows each game's win probability, projected margin and total with intervals, a game's detail view shows its drivers and injuries, Refresh starts a `daily` job, and the manifest and service worker load.

## Layout (`/home/emhar/avaris`)
```
pyproject.toml  uv.lock  config.toml  .gitignore
src/avaris/  config.py db.py cli.py
  ingest/    nba_stats.py nba_schedule.py injuries.py teams.py status.py
  features/  elo.py team_form.py schedule.py availability.py decision_time.py build.py
  models/    baselines.py gbm.py calibration.py distributions.py registry.py
  analytics/ drivers.py ratings.py injury_impact.py
  backtest/  walkforward.py metrics.py report.py
  pipeline/  train.py daily.py score.py jobs.py
  api/       main.py routes/{predictions,games,teams,performance,backtests,injuries,jobs}.py
web/         Next.js PWA (app/: today, game, teams, performance, backtests, injuries; components/ui from shadcn; e2e/ Playwright)
data/ (gitignored)   artifacts/ (models, reports)
tests/       unit/ integration/ e2e/ fixtures/
```
DuckDB tables: `games` (incl. `tip_off_utc`, `game_date_et`, `season_type`, `neutral_site`, `venue`), `team_games`, `player_games`, `rosters`, `injury_report_files`, `injury_reports` (incl. `report_ts`), `features` (keyed by game + `decision_ts`), `team_ratings` (team + as-of game), `predictions` (game, `decision_ts`, model run, `status` provisional/final, `p_home_win`, `margin_mu`, `margin_sigma`, `total_mu`, `total_sigma`, drivers JSON), `prediction_scores` (per final prediction after the game: log loss, Brier, margin and total errors, interval hits), `jobs`.

## Phases (each sized for one session)

### Phase 1 — Foundation + stats data (done, PR #2)
- `git init` and `.gitignore` (data/, artifacts/, .env.local, .venv, node_modules, web/.next, web/out).
- uv project, ruff, pyright, config, Typer CLI, DuckDB schema.
- Test deps: `uv add --dev pytest pytest-cov hypothesis respx time-machine` (add `pytest-xdist` later if walk-forward tests get slow). Register the `e2e` pytest marker.
- Ingest team and player game logs for 2012-13 to now, plus rosters (throttled to about 1 request/sec, resumable, cached, with the `refetch_days` window for the current season).
- Schedule ingest: tip-off time, `season_type` and venue per game; `game_date_et` derived from `tip_off_utc`. Preseason games are stored with `season_type = preseason`.
- Team ID mapping and arena CSV, plus a neutral-site venue list (bubble, international games, NBA Cup final).
- **Done when:** the gates pass, `avaris ingest stats` has filled `games`, `team_games`, `player_games` and `rosters`, row counts match about 1,230 games per regular season, every game has a `season_type`, every game from 2020-21 on has a tip-off time, and the 2019-20 bubble games are tagged neutral.

### Phase 2 — Injuries + odds removal (done, PR #5)
- **Already built** on branch `phase-2-odds-injuries`: injury report ingest mapped to player IDs, with `report_ts` so `decision_ts` can pick the right report; `decision_ts` resolution; the injury coverage check. Its done-when passes on real data (2021-22 to 2025-26).
- **Remove the odds and betting code built before the pivot:**
  - Delete `ingest/odds_api.py`, `ingest/odds_slots.py`, `ingest/odds_backfill.py`, `ingest/odds_status.py`, `betting/`, and their tests (`test_odds_*`, `test_credit_guard.py`, `test_devig.py`, `tests/odds_payloads.py`, `tests/integration/test_odds_backfill.py`, `tests/e2e/test_cli_odds.py`).
  - Remove the `avaris odds` CLI group, `OddsSettings` and `GuardSettings` from `config.py`, the `[odds]` block from `config.toml`, and the odds cases in `test_config.py`, `test_db.py` and `test_teams.py`.
  - Migration 4 drops `odds_events`, `odds_snapshots` and `api_usage` (migration 3 is already applied to the real DB, so it is not edited).
  - Keep `teams.team_ids_by_name()`: the injury ingest uses it. Rename its odds-named test.
- **Docs:**
  - Rename this file to `docs/plans/avaris-nba-analytics-model-build-plan.md` and update every reference.
  - ADR-014 records the pivot. Mark ADR-005, 006, 008, 011 and 013 superseded; amend ADR-003 (no odds frozen at `decision_ts`) and ADR-004 (predictions cover play-in and playoffs).
  - Rewrite the betting and odds parts of `CLAUDE.md` and `README.md`; update `STATUS.md` and `CHANGELOG.md`.
- Close issue #3 (Odds API fixtures) once the odds code is gone.
- **Done when:**
  - The injury done-when still passes: `avaris ingest status --check` shows every regular-season game from 2021-22 on with a report between tip-off − 12 h and tip-off − 60, and unmatched player rows below 5%.
  - `grep -ri "odds\|devig\|CreditGuard" src tests` finds only migrations 2, 3 and 4 in `db.py` and the migration 4 test in `test_db.py`, and the real DB has no odds tables after migration 4.
  - The gates pass.

### Phase 3 — Features + models (done, PR #8; see `docs/plans/phase-3-features-models.md`)
- `decision_ts` resolution per game, and all feature families as of `decision_ts`, including neutral-site handling and the availability rules for trades and roster moves.
- `team_ratings` table, filled from the same as-of feature code.
- Model ladder, LightGBM + Optuna (one refit per season during trials, SQLite storage), calibration, σ fitting.
- Tune and select rungs on 2015-16 to 2019-20, then freeze hyperparameters in `config.toml`.
- `avaris train`, artifacts with `meta.json`, and the registry with its promotion rules.
- **Done when:**
  - The leakage test passes at timestamp granularity: deleting all rows with `ts > decision_ts` leaves that game's features unchanged. This covers same-day injury reports.
  - The trade test passes.
  - The neutral-site test passes: bubble games have `home_court = 0` and zero travel.
  - The preseason test passes: a preseason game gets features, and deleting every preseason result leaves all other games' features unchanged.
  - The train cutoff test passes: `avaris train --through D` uses no game on or after D.
  - Walk-forward results on 2015-16 to 2019-20 show LightGBM (or the rung that's kept) beating Elo on log loss and MAE.
  - Registry tests pass: promotion, candidate hold, manual `--promote` and feature-hash refusal.

### Phase 4 — Evaluation + analytics (done, PR #10; see `docs/plans/phase-4-evaluation-analytics.md` and `docs/reports/phase-4-evaluation.md`)
- Walk-forward evaluation for 2020-21 to 2024-25 with weekly refits and the frozen hyperparameters: all metrics above, against Elo and the naive baselines, with preseason, play-in and playoffs reported separately from the regular season.
- Re-run on 2021-22+ using the `decision_ts` injury report instead of actual availability, to measure the cost of late scratches. This re-run is the number that matters for live use.
- Drivers (`analytics/drivers.py`) and injury impact (`analytics/injury_impact.py`) per prediction, checked on the evaluation run: for each game, contributions plus the base value sum to the model output.
- Markdown + chart report (reliability diagrams, PIT histograms, metrics per season); then run once on the 2025-26 holdout.
- **Final refit for live use:** after the holdout run, `avaris train --through` the end of 2025-26 (playoffs included) and promote it as the first production model. Hyperparameters are not retuned.
- **Done when:** the report shows every metric with bootstrap confidence intervals against Elo and both naive baselines, calibration and interval coverage, for both the actual-availability and injury-report runs, plus the holdout. It states plainly where the model does not beat Elo. A production artifact trained through 2025-26 is in the registry.

### Phase 5 — Daily pipeline + API (in progress; see `docs/plans/phase-5-daily-pipeline-api.md`)
- `avaris daily`: refresh stats, schedule, rosters and injuries → retrain if the production model is stale → for every game today and any earlier game still missing a final prediction, write a provisional prediction before `decision_ts` or a final one after it. Idempotent: reruns change nothing unless new data arrived.
- `avaris score`: results → per-game scores in `prediction_scores` for final predictions.
- `avaris serve` runs `daily` once on startup; after that, `daily` runs from the UI Refresh button or the CLI.
- FastAPI read endpoints for predictions (today and by date), a game's detail (prediction, drivers, injuries, team ratings), teams, performance, backtests and injuries; `POST /api/jobs/{daily,score,train}` with `job_id`, status endpoint and the single-job lock. The single-writer connection model described above.
- **Done when:** API tests pass (FastAPI TestClient), the pipeline E2E test passes (train → daily before and after `decision_ts` → score on fixtures with a frozen clock), and on a game day `avaris daily` then `GET /api/predictions/today` returns that day's games with `p_home_win`, margin and total μ with 80% intervals, top drivers and `status`.

### Phase 6 — Desktop PWA
- Next.js App Router + TS + Tailwind v4, `output: 'export'` so it builds to static files in `web/out` (no Node server at runtime).
  - Static export rules: client-side data fetching (TanStack Query against `/api`), no server actions or route handlers, no dynamic segments without `generateStaticParams` (use query params for detail views, e.g. `/game?id=...`).
  - In dev, `next dev` (port 3000) calls FastAPI at `localhost:8000` via `NEXT_PUBLIC_API_BASE`, with CORS allowed for `localhost:3000` (dev only). In prod the base is empty (same origin).
- shadcn/ui (`npx shadcn init`): Card, Table, Badge, Tabs, Dialog, Sidebar, Chart.
- PWA: `app/manifest.ts`, icons, and a service worker caching the app shell.
- Pages:
  - **Today:** every game (preseason flagged) with win probability, projected margin and total with 80% intervals, injury impact, provisional vs. final badge and time to `decision_ts`; a Refresh button.
  - **Game:** prediction, distribution charts, top drivers, both teams' injury reports and rating trends.
  - **Teams:** Elo and net rating table, with rating and pace trends per team.
  - **Performance:** live scores vs. the backtest (log loss, Brier, MAE, calibration, interval coverage), season to date.
  - **Backtests.**
  - **Injuries.**
- FastAPI serves `web/out`. `avaris serve` starts everything.
- Test deps: `npm i -D vitest @vitejs/plugin-react vite-tsconfig-paths jsdom @testing-library/react @testing-library/user-event @testing-library/jest-dom msw @playwright/test`.
- Vitest with the `node`/`jsdom` project split above (TDD); Playwright E2E for every page and the Refresh flow.
- npm commands use `--cache "$TMPDIR/npm-cache"` (sandbox). Installing Playwright's Chromium system deps may need sudo, so that step is user-run (`! npx playwright install --with-deps chromium`).
- **Done when:** lint, typecheck, unit tests, Playwright E2E and build pass; every page renders with real data in Chrome; and it installs as an app and opens in its own window (checked in the browser).

## Verification (whole build)
- Python: `uv run ruff check && uv run pyright && uv run pytest`. Web: `npm run lint && npm run typecheck && npm run test && npm run build`, plus `npm run test:e2e` once Phase 6 starts. All green at the end of every phase.
- Every phase is built test-first; a phase is not done if its new code lacks tests.
- End to end on a game day:
  1. `avaris serve` (runs `daily` on startup; retrains first if the production model is over a week old).
  2. Open the installed PWA → Today shows provisional predictions; after a Refresh past `decision_ts`, final ones.
  3. After the games, `score` runs → Performance updates.
- **Live tracking:** over the first 4 weeks of 2026-27, live log loss and MAE are compared with the backtest's bootstrap interval. Performance flags drift if they fall outside it.

## Risks and mitigation

| Risk / question | Impact | Mitigation |
| :-------------- | :----- | :--------- |
| With no market benchmark, nothing shows how good the model is in absolute terms | A model that beats Elo can still be mediocre | Elo, two naive baselines and calibration are the bar; the report states plainly where the model does not beat Elo; an external historical-lines benchmark is a follow-up |
| Backtest predictions use information not available before tip-off (post-hoc availability, late injury news) | Backtest metrics are inflated; live results disappoint | Single `decision_ts` per game freezes injuries and features; timestamp-granular leakage test; injury-report re-run is the headline number |
| Odds code removal breaks the injury ingest or leaves dead tables | Phase 2 regressions | Removal is its own commit with the injury done-when re-run; migration 4 drops the tables; grep check in the done-when |
| Preseason, play-in, playoffs, neutral-site and bubble games distort features or metrics | Bad tuning (bubble is inside the tuning window) and misleading headline numbers | `season_type` and `neutral_site` on `games`; preseason never feeds features; headline metrics on the regular season; neutral-site and preseason tests |
| Preseason predictions ignore who actually plays (starters rest, no injury report) | Preseason predictions are overconfident | σ fitted per `season_type` bucket; preseason metrics and interval coverage reported on their own; Today flags preseason games |
| Tip-off times and ET game dates missing or wrong | Wrong `decision_ts`, late games on the wrong day | Schedule ingest with `tip_off_utc`; `game_date_et` derived; Phase 1 done-when requires a tip-off for every game from 2020-21 |
| No scheduler, so `daily` may not run before a game | Today shows a provisional or stale prediction | `daily` runs on `serve` startup and from Refresh; it catches up because injury PDFs stay on the CDN; Today shows the status and time to `decision_ts` |
| Optuna over weekly refits is too slow | Phase 3 does not finish in a session | One refit per season during trials, weekly only for the final comparison; resumable SQLite storage |
| Two jobs write DuckDB at once, or a long `train` blocks the API | Corruption or a hung UI | Background thread, process-wide job lock with `409`, `jobs` table and status endpoint |
| Cached stats for the in-progress season never pick up corrections | Stale features | `refetch_days` window on every `ingest stats` run |
| Normal margin and total distributions are too thin-tailed for blowouts | Intervals under-cover | 80% interval coverage and PIT histograms in the report; switch to a Student-t or empirical residual quantiles if coverage misses 78-82% |
| stats.nba.com throttles or blocks the sandbox proxy | Ingest stalls | Throttle to about 1 request/sec, resumable cache, user-run from the home network |

## Notes
- stats.nba.com throttles heavy use; run backfills from your home network.
- The `avaris serve` process must be running for the PWA to show data. Offline, the window shows only the cached app shell.
- Follow-ups, not v1: season simulation (projected wins, play-in and playoff odds), player-level projections, a market benchmark from a free historical closing-lines dataset, minutes redistribution when a star is out, and an OS-level schedule for `avaris daily`.
- Follow-up, not in v1: the fitted σ values and quarter stats could replace the hand-set parameters in the `nba-projected-total` skill.
