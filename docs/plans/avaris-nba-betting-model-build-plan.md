# Plan: Avaris — personal NBA betting model (moneyline, spread, total)

## Context
Build a personal ML system that predicts NBA moneyline, spread and over/under, compares its probabilities with sportsbook lines, and shows edges in an installable desktop PWA. `~/avaris` is greenfield (only `.claude/` config, no git).

User decisions:
- Build in `~/avaris`.
- Paid odds data is fine **with tracked spend and a hard stop**.
- v1 = the full app, including injuries/lineups.
- Desktop UI = **Next.js + shadcn/ui PWA + FastAPI**.
- **Personal, single-user, local-only:** no accounts, auth, hosting, multi-tenancy or billing code.

The goal is to make money against the market. Betting lines are very efficient, so all evaluation is against the de-vigged **closing line**, not raw accuracy.

## Stack
| Layer | Choice |
|---|---|
| Python env | Python 3.12 + **uv**; ruff, pyright, pytest |
| Stats data | **stats.nba.com via a thin httpx client** (ADR-009; replaces `nba_api`): `leaguegamelog` per season and season type covers every team-game and player-game line; `commonteamroster` for rosters; `scheduleleaguev2` per season supplies tip-off time, `season_type`, venue and today's slate |
| Odds data | **The Odds API** (httpx + tenacity): h2h/spreads/totals; historical from Jun 2020 (10-minute snapshots), 5-minute snapshots from Sep 2022. Events carry `commence_time` (UTC), used as the tip-off fallback for 2020-21+ |
| Injuries | Official NBA pregame injury reports via `nba-injury-report` (2021-22+; AGPL, fine for personal use). **Verify in Phase 2** that the package exists and 2021-22 PDFs are still served before building on it |
| Storage | **DuckDB** file + raw JSON/Parquet response cache; pandas |
| Models | scikit-learn (Elo/logistic/ridge baselines, isotonic calibration, time-series CV), **LightGBM**, Optuna, scipy |
| Artifacts | joblib + JSON metadata (features, train window, metrics) |
| CLI / config | Typer; pydantic-settings + `config.toml`; Odds API key in `.env.local` (gitignored) |
| Testing | Python: pytest, pytest-cov, hypothesis (property tests), respx (httpx mocks), time-machine (frozen clock), pytest-xdist (optional). Web: Vitest + React Testing Library (+ user-event, jest-dom), jsdom (component tests only), msw (API mocks), **Playwright** for UI E2E |
| API | **FastAPI** + uvicorn on `localhost:8000`; also serves the statically exported PWA |
| Desktop UI | **Next.js (App Router, `output: 'export'`) + TypeScript + Tailwind v4 + shadcn/ui**, TanStack Query, shadcn charts (Recharts). PWA via `app/manifest.ts` + a service worker caching the app shell. Installed from Windows Chrome ("Install app"), so it opens in its own window. Localhost counts as a secure context, so the PWA works without HTTPS. |

## Key design
- **Targets:**
  - `home_win`: classifier giving the moneyline probability.
  - `margin`: regressor. P(cover) = Φ((μ + spread)/σ), with a ±0.5 adjustment for whole-number lines that can push.
  - `total`: regressor giving P(over) the same way.
  - σ is fitted from out-of-fold residuals.
- **Model ladder:**
  1. Elo baseline: margin of victory, home advantage, carryover between seasons.
  2. Logistic/ridge regression.
  3. LightGBM tuned with Optuna.
  Each target keeps a rung only if it beats the one below on walk-forward log loss or MAE. Classifiers are calibrated with isotonic regression.
- **Decision timestamp (`decision_ts`):** every pick is made "as of" one instant per game, and odds, injury report and features are all frozen at it.
  - Default `decision_ts` = latest injury report at or before **tip-off − 60 min** (reports post at 1:30 pm and 5:30 pm ET; the 5:30 pm report covers 7 pm tips). If no report exists for the game (all of 2020-21, or a missing day), `decision_ts` = tip-off − 60 min. The odds snapshot used for the pick is the last one at or before `decision_ts`; the closing line is the last snapshot within **45 min before tip-off**.
  - Backtests and live use the same rule. The leakage test checks at timestamp granularity, not date granularity: deleting rows with `ts > decision_ts` leaves that game's features unchanged.
  - Live `daily` therefore runs in two passes: a morning pass (stats refresh, retrain if stale, provisional picks on the opening line) and an evening pass at `decision_ts` that finalizes picks. Only finalized picks are bets.
- **Time and game identity:** all timestamps stored in UTC; `game_date` is the **ET** calendar date of tip-off (10:30 pm ET tips are the same day). `games` carries `tip_off_utc`, `game_date_et`, `season_type` (preseason, regular, cup_final, play_in, playoffs) and `neutral_site`.
- **Non-standard games:**
  - Preseason is never ingested into odds, picks or bets. The Odds API lists preseason events, so `daily` filters them by `season_type`.
  - Training uses regular season + play-in + playoffs with `season_type` as a feature; Elo updates on all of them. Betting simulation and live betting cover **regular season only** in v1 (playoffs are a follow-up: different home court and rest effects, small sample).
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
- **Market is not a feature.** The betting layer blends model and market: p = w·model + (1−w)·market, with **one `w` per target** fitted on validation.
- **Betting layer:**
  - Spread sign convention: `spread` is the home line (negative when home is favored). Home covers when `margin + spread > 0`. Totals: over when `points > total`.
  - **Moneyline:** de-vig each book with multiplicative and Shin methods; consensus = median fair probability across books; track the best available price.
  - **Spread and total are per book, never a cross-book median.** Books post different lines (-3.5 vs -4), so each book's de-vigged price is a fair probability *at that book's line*. For each book: `market_p` = de-vigged price at line L, `model_p` = P(cover at L) from the margin or total distribution, blend at L, edge at L. The bet goes to the book with the largest edge. The "consensus" for reporting is the median *line* plus the median fair probability at that line, when at least 3 books post it.
  - **Recommended odds:** every pick carries the price to take and the worst price still worth taking.
    - `rec_book` and `rec_price`: the book and American price with the largest edge at `decision_ts` (for spreads and totals, together with `rec_line`).
    - `min_price`: the break-even American price at which edge drops to the threshold, `min_price = odds(p_blend − threshold)`. If the user's book is worse than `min_price`, the pick is a pass.
    - `fair_price`: the no-vig price implied by `p_blend`, for reference.
    - Shown in the Today page and the picks API; the Bet Log pre-fills `rec_price` and warns when the entered price is below `min_price`.
  - Bet when edge ≥ a threshold, sized at flat stake or ¼ Kelly with a per-bet cap. **Same-game correlation:** at most one bet per game per side direction (ML and spread on the same team are correlated), and a per-game stake cap.
  - **Closing-line benchmark:** the consensus close from the `us` region. Pinnacle (`eu` region) is the sharper benchmark but doubles credits; optional via config, off by default.
- **Walk-forward evaluation:** train on seasons before S, test on S, retraining weekly inside the season. Models train from 2012-13; betting simulation runs 2020-21+. **2025-26 is a holdout, used once.**
- **Tuning and fitting splits (no tuning on scored seasons):**
  - Optuna tuning and rung selection use walk-forward over **2015-16 to 2019-20** only. Hyperparameters and the kept rung are then **frozen** for 2020-21+.
  - **Compute budget:** Optuna trials run with **one refit per season** (5 fits per trial per target). Only the final rung comparison and the 2020-21+ simulation use weekly refits. Trial count and `n_jobs` live in `config.toml`; every trial is logged to Optuna's SQLite storage so tuning is resumable.
  - Blend weight `w` (per target) and edge thresholds are fitted walk-forward: before season S, fit them on out-of-sample predictions plus closing odds from 2020-21 to S−1.
  - 2020-21 has no earlier odds, so it uses `w = 0.5` and the config default threshold. It is reported separately as a warm-up season.
- **Production training:**
  - `avaris train --through DATE` refits the kept rung per target on every game that tipped off before `DATE`, with the frozen hyperparameters. Calibration and σ come from out-of-fold predictions.
  - Each run writes `artifacts/models/<target>/<run_id>/` with `model.joblib` and `meta.json`: train window, feature list + feature hash, hyperparameters, seed, git SHA, package versions and OOF metrics.
  - `artifacts/models/registry.json` points to the production artifact per target. A new artifact is promoted automatically only if its feature hash matches the current feature builder, it has more training rows than the previous artifact, and its OOF metrics are within `promote_tolerance` of the previous artifact's. Otherwise it stays a candidate, and `daily` warns. `avaris train --promote RUN_ID` is the manual override (needed after any hyperparameter or rung change, which first requires a new walk-forward run).
  - `daily` refuses to predict with an artifact whose feature hash does not match the current feature builder.
  - **Cadence:** weekly, matching the backtest. `avaris daily` runs `train` first when the production artifact is older than `retrain_every_days` (default 7).
  - **Reproducibility:** fixed `seed` in `config.toml`, recorded in `meta.json`.
- **Odds stop-gap (`CreditGuard`):**
  - Each run first calls `/v4/sports` (0 credits) to read `x-requests-remaining` and `x-requests-used`.
  - The cost is computed before every call: `10 × markets × regions` for historical, `markets × regions` for live, 1 for historical events.
  - A call is **refused** if it would exceed `max_credits_per_run`, `monthly_credit_budget` or `max_monthly_usd` (= used × `usd_per_credit`), or go below `min_remaining_reserve`.
  - Every call is written to the `api_usage` ledger. If the estimate and `x-requests-last` disagree, the run stops.
  - Every response is cached, so repeats are free. `--estimate` spends 0 credits. A real backfill needs `--confirm`.
- **Odds cost:**
  - Historical data needs a paid plan. The backfill is about 30–36k credits per season (30 credits per snapshot; per game day 1 opening + 2 decision + 3 closing snapshots ≈ 6–7 snapshots over ≈ 170 game days), or ≈ 180–215k for 2020-21 to 2025-26.
  - Buy **one month of the 5M plan** (≈ $119; confirm current pricing before buying), do the test run and the backfill in that month, then **downgrade to free**.
  - **Free-tier monthly budget:** a live call for 3 markets × 1 region costs 3 credits. Live snapshots are limited to **2 decision slots** (early, after the 5:30 pm ET report, for tips before 9:30 pm; late, for 9:30 pm and after) and **3 closing slots** (early ≈ 7–7:30 pm, mid ≈ 8–9 pm, late ≈ 10–10:30 pm, each within 45 min of its tips). **No opening snapshot on the free tier**; provisional morning picks reuse the previous evening's late snapshot and are never bets. Per game day: 5 calls = 15 credits. At ≈ 28 game days that is **≈ 420 of the 500 free credits**. `CreditGuard` live defaults: `max_credits_per_run = 6`, `monthly_credit_budget = 450`, `min_remaining_reserve = 30`. Backfills pass an explicit per-run cap with `--confirm`. **Refusal priority:** when the monthly budget is nearly spent, the guard drops calls in the order opening → closing → decision, so picks survive longest. When a closing snapshot is refused, `settle` marks CLV as unavailable for that game rather than failing.
- **Closing-line capture has a runtime.** Historical odds are paid-only, so after the downgrade the closing line exists only if a live snapshot was taken just before tip-off. `avaris serve` runs an in-process **APScheduler**: the morning pass (stats, no odds), the two decision slots and the three closing slots. The scheduler is the only automated caller of the Odds API and goes through `CreditGuard` like everything else. The server must be running on game days; a `GET /api/jobs/schedule` endpoint and the Usage page show the next runs and any missed ones. `avaris daily --at decision|close` is the manual fallback.
- **DuckDB allows one writer process.** The FastAPI server owns the read-write connection. CLI jobs run in-process when the server is down, or through `POST /api/jobs/{daily,settle,train}` when it's up. The UI only reads DuckDB and never calls external APIs.
  - **Jobs:** `POST /api/jobs/*` returns a `job_id` immediately and runs the job in a background thread. `GET /api/jobs/{job_id}` reports status, progress and log tail. A single process-wide lock allows one job at a time; a second request gets `409`. Jobs are recorded in a `jobs` table.
- **Stats cache freshness:** cached stats responses are immutable for finished seasons. For the in-progress season, `ingest stats` refetches the last `refetch_days` (default 7) of game logs on every run so stat corrections land.

## Testing approach
- **TDD by default:** write a failing test first, make it pass, then refactor. This applies to all deterministic code:
  - `CreditGuard`, ledger, cache, de-vig, edge, staking, Elo, features, availability rules, distributions, API routes.
  - `decision_ts` resolution, ET game-date mapping, `season_type` and neutral-site tagging, preseason filter, per-book spread/total edge, same-game correlation cap, recommended odds (`rec_price`, `min_price`, `fair_price`, American/decimal conversion round-trip).
  - Training plumbing: `--through` cutoff, registry promotion and refusal rules, feature-hash check, retrain staleness trigger, walk-forward `w`/threshold fitting.
  - Scheduler and jobs: slot merging, guard refusal → CLV unavailable, job lock (`409`), job status, missed-run reporting (APScheduler run with a fake clock via `time-machine`).
  - Web: data hooks, formatters, and components with logic (Vitest + React Testing Library).
- **Vitest environments (jsdom is slow, so use it only where a DOM is needed):**
  - Default environment is `node`. Two Vitest `projects`: `*.test.ts` runs in `node`, `*.test.tsx` runs in `jsdom`.
  - `node`: formatters, API client, query keys, data transforms, odds/edge display math, msw handlers (`msw/node`).
  - `jsdom`: component rendering, user interaction, and hooks tested with `renderHook`.
  - Keep logic out of components (plain `.ts` modules) so most tests stay in `node`.
- **Test-after is allowed only** for exploratory model tuning and report styling. Tests must still exist before the phase is done.
- **No live network in tests.** Use recorded stats, odds and injury responses from the cache, plus a small fixture DuckDB built by `tests/fixtures/`.
- **E2E tests:**
  1. **Pipeline E2E** (pytest, `@pytest.mark.e2e`): fixture responses → `avaris train` → `avaris daily` → `avaris settle`. Asserts on picks, bets, CLV, P&L and `api_usage` rows.
  2. **UI E2E** (Playwright, `web/e2e/`): starts `avaris serve` on the fixture DB, then checks that every page renders real data, Today shows recommended odds per pick, Bet Log can add and settle a bet (pre-filled from a pick, with the below-minimum-price warning), Usage shows spend vs. cap, and the manifest and service worker load.

## Layout (`/home/emhar/avaris`)
```
pyproject.toml  uv.lock  config.toml  .env.local  .gitignore
src/avaris/  config.py db.py cli.py
  ingest/    nba_stats.py nba_schedule.py odds_api.py injuries.py teams.py
  features/  elo.py team_form.py schedule.py availability.py decision_time.py build.py
  models/    baselines.py gbm.py calibration.py distributions.py registry.py
  betting/   devig.py edge.py staking.py
  backtest/  walkforward.py metrics.py report.py
  pipeline/  train.py daily.py settle.py scheduler.py jobs.py
  api/       main.py routes/{picks,performance,backtests,injuries,usage,bets,jobs}.py
web/         Next.js PWA (app/: today, performance, backtests, injuries, usage, bet-log; components/ui from shadcn; e2e/ Playwright)
data/ (gitignored)   artifacts/ (models, reports)
tests/       unit/ integration/ e2e/ fixtures/
```
DuckDB tables: `games` (incl. `tip_off_utc`, `game_date_et`, `season_type`, `neutral_site`, `venue`), `team_games`, `player_games`, `rosters`, `injury_reports` (incl. `report_ts`), `odds_snapshots` (game, book, market, side, line, price, snapshot_ts, kind open/decision/close/live), `features` (keyed by game + `decision_ts`), `predictions`, `picks` (incl. `decision_ts`, `status` provisional/final, `rec_book`, `rec_price`, `rec_line`, `min_price`, `fair_price`), `bets`, `api_usage`, `jobs`.

## Phases (each sized for one session)

### Phase 1 — Foundation + stats data
- `git init` and `.gitignore` (data/, artifacts/, .env.local, .venv, node_modules, web/.next, web/out).
- uv project, ruff, pyright, config, Typer CLI, DuckDB schema.
- Test deps: `uv add --dev pytest pytest-cov hypothesis respx time-machine` (add `pytest-xdist` later if walk-forward tests get slow). Register the `e2e` pytest marker.
- Smoke test one stats.nba.com call, and one schedule call for a finished historical date to confirm it still carries tip-off times (not just "Final"). If the sandbox proxy blocks it, every ingest command becomes user-run via `! uv run avaris ...`.
- Ingest team and player game logs for 2012-13 to now, plus rosters (throttled to about 1 request/sec, resumable, cached, with the `refetch_days` window for the current season).
- Schedule ingest: tip-off time, `season_type` and venue per game; `game_date_et` derived from `tip_off_utc`. Preseason games are stored with `season_type = preseason` and excluded downstream.
- Team ID mapping and arena CSV, plus a neutral-site venue list (bubble, international games, NBA Cup final).
- **Done when:** the gates pass, `avaris ingest stats` has filled `games`, `team_games`, `player_games` and `rosters`, row counts match about 1,230 games per regular season, every game has a `season_type`, every game from 2020-21 on has a tip-off time (earlier seasons best-effort; only date-level features need them), and the 2019-20 bubble games are tagged neutral.

### Phase 2 — Odds + injuries
- **Smoke tests first:** fetch one 2021-22 injury report PDF and confirm `nba-injury-report` parses it; confirm the Odds API plan tiers and pricing. If either fails, stop and revisit the stack before building.
- Odds API client with `CreditGuard`, ledger, cache and `--estimate`. Odds events are matched to `games` by team IDs plus `commence_time` within 2 hours of `tip_off_utc`; preseason events are dropped.
- Map Odds API team names to NBA IDs.
- Snapshot selection for the backfill: per game, 1 opening, 1 at `decision_ts`, 1 closing (last snapshot within 45 min before tip-off). Slots are shared across games on the same day (the same 2 decision + 3 closing slots as live, plus 1 opening), so the per-day cost stays at about 6–7 snapshots.
- De-vig functions (multiplicative, Shin) and the per-book fair probability at a line.
- Injury report ingest, mapped to player IDs, with `report_ts` so `decision_ts` can pick the right report.
- The user buys the plan and runs a 1-week test (`! uv run avaris odds backfill --from … --to … --confirm`). The ledger must reconcile with the headers before the user runs the full backfill.
- **Done when:**
  - Smoke tests pass and are recorded in `STATUS.md`.
  - Guard tests pass: the refusal cases, priming, and ledger rows.
  - `--estimate` spends 0 credits.
  - `odds_snapshots` covers 2020-21+ with matched game IDs (< 1% unmatched) and each regular-season game has an open, decision and close snapshot.
  - Injury reports cover 2021-22+ with `report_ts`.

### Phase 3 — Features + models
- `decision_ts` resolution per game, and all feature families as of `decision_ts`, including neutral-site handling and the availability rules for trades and roster moves.
- Model ladder, LightGBM + Optuna (one refit per season during trials, SQLite storage), calibration, σ fitting.
- Tune and select rungs on 2015-16 to 2019-20, then freeze hyperparameters in `config.toml`.
- `avaris train`, artifacts with `meta.json`, and the registry with its promotion rules.
- **Done when:**
  - The leakage test passes at timestamp granularity: deleting all rows with `ts > decision_ts` leaves that game's features unchanged. This covers same-day injury reports and odds.
  - The trade test passes.
  - The neutral-site test passes: bubble games have `home_court = 0` and zero travel.
  - The train cutoff test passes: `avaris train --through D` uses no game on or after D.
  - Walk-forward results on 2015-16 to 2019-20 show LightGBM (or the rung that's kept) beating Elo on log loss and MAE.
  - Registry tests pass: promotion, candidate hold, manual `--promote` and feature-hash refusal.

### Phase 4 — Betting layer + backtest
- Moneyline consensus de-vig; per-book spread and total edge at each book's line; per-target model/market blend; edge thresholds; recommended odds (`rec_book`, `rec_price`, `rec_line`, `min_price`, `fair_price`); flat and ¼-Kelly staking with the same-game correlation cap.
- Walk-forward betting simulation for 2020-21 to 2024-25 (regular season only), picks at the `decision_ts` snapshot and CLV against the close, with `w` and thresholds fitted walk-forward (2020-21 as the warm-up season).
- Re-run on 2021-22+ using the `decision_ts` injury report instead of actual availability, to measure the cost of late scratches. This re-run is the number that matters for live use.
- Markdown + chart report; then run once on the 2025-26 holdout.
- **Final refit for live use:** after the holdout run, `avaris train --through` the end of 2025-26 (playoffs included) and promote it as the first production model. Refit `w` and thresholds on 2020-21 to 2025-26. Hyperparameters are not retuned.
- **Done when:** the report shows log loss vs. Elo and vs. the de-vigged close, ROI with a bootstrap confidence interval, CLV % and calibration plots, for both the actual-availability and injury-report runs. It states plainly if there's no edge. A production artifact trained through 2025-26 is in the registry.

### Phase 5 — Daily pipeline + API
- `avaris daily --at morning`: refresh stats, schedule, rosters and injuries → drop preseason → retrain if the production model is stale → provisional picks on the latest cached odds (no Odds API call on the free tier).
- `avaris daily --at decision`: injuries at `decision_ts` → odds snapshot (guarded) → features → predict with the production artifact → final picks for the games in that slot.
- `avaris daily --at close`: closing snapshot for the current tip-time slot.
- Phase 5 may span two sessions: 5a pipeline passes + `settle` + read endpoints, 5b scheduler + jobs subsystem.
- `avaris settle`: results → CLV against the close (or "unavailable" if the guard refused the snapshot) → P&L.
- Scheduler inside `avaris serve` (APScheduler) running the three passes and closing slots; missed-run tracking.
- FastAPI read endpoints for picks, games, performance, backtests, injuries, usage and the job schedule; `POST` for the manual bet log and job triggers (`daily`, `settle`, `train`) with `job_id`, status endpoint and the single-job lock. The single-writer connection model described above.
- **Done when:** API tests pass (FastAPI TestClient), the pipeline E2E test passes (morning → decision → close → settle on fixtures with a frozen clock), and on a game day `avaris daily` then `GET /api/picks/today` returns that day's games with model probability, market probability, edge, stake, `status` and recommended odds (`rec_book`, `rec_price`, `rec_line`, `min_price`, `fair_price`).

### Phase 6 — Desktop PWA
- Next.js App Router + TS + Tailwind v4, `output: 'export'` so it builds to static files in `web/out` (no Node server at runtime).
  - Static export rules: client-side data fetching (TanStack Query against `/api`), no server actions or route handlers, no dynamic segments without `generateStaticParams` (use query params for detail views).
  - In dev, `next dev` (port 3000) calls FastAPI at `localhost:8000` via `NEXT_PUBLIC_API_BASE`, with CORS allowed for `localhost:3000` (dev only). In prod the base is empty (same origin).
- shadcn/ui (`npx shadcn init`): Card, Table, Badge, Tabs, Dialog, Form, Sidebar, Chart.
- PWA: `app/manifest.ts`, icons, and a service worker caching the app shell.
- Pages:
  - **Today:** picks per game for ML, spread and total; model vs. market, edge, stake, injuries, provisional vs. final badge, time to `decision_ts`. **Recommended Odds** column: book, line and price to take, with the minimum acceptable price and fair price underneath; a "Bet this" button opens the Bet Log dialog pre-filled.
  - **Performance:** ROI, CLV, calibration; paper-trading vs. real bets split.
  - **Backtests.**
  - **Injuries.**
  - **Usage:** credits used vs. budget, next scheduled runs, missed runs.
  - **Bet Log:** add and settle your own bets.
- FastAPI serves `web/out`. `avaris serve` starts everything.
- Test deps: `npm i -D vitest @vitejs/plugin-react vite-tsconfig-paths jsdom @testing-library/react @testing-library/user-event @testing-library/jest-dom msw @playwright/test`.
- Vitest with the `node`/`jsdom` project split above (TDD); Playwright E2E for every page and the Bet Log flow.
- npm commands use `--cache "$TMPDIR/npm-cache"` (sandbox). Installing Playwright's Chromium system deps may need sudo, so that step is user-run (`! npx playwright install --with-deps chromium`).
- **Done when:** lint, typecheck, unit tests, Playwright E2E and build pass; every page renders with real data in Chrome; and it installs as an app and opens in its own window (checked in the browser).

## Verification (whole build)
- Python: `uv run ruff check && uv run pyright && uv run pytest`. Web: `npm run lint && npm run typecheck && npm run test && npm run build`, plus `npm run test:e2e` once Phase 6 starts. All green at the end of every phase.
- Every phase is built test-first; a phase is not done if its new code lacks tests.
- End to end on a game day:
  1. `avaris serve` (its scheduler runs the morning, decision and closing passes; retrains first if the production model is over a week old)
  2. Open the installed PWA → Today shows provisional picks in the morning and final picks after `decision_ts`.
  3. After the games, `settle` runs → Performance updates with CLV.
- Cost: the `api_usage` ledger total matches the Odds API dashboard, and the Usage page shows the month's spend under the cap.
- **Paper trading before real money:** the first 4 weeks of 2026-27 are logged as paper bets. Real stakes start only if live CLV is positive and ROI is inside the backtest's bootstrap interval over that window. Performance shows the two separately.

## Risks and mitigation

| Risk / question | Impact | Mitigation |
| :-------------- | :----- | :--------- |
| Backtest picks use information not available at bet time (post-hoc availability, late injury news) | Backtest ROI is inflated; live results disappoint | Single `decision_ts` per game freezes odds, injuries and features; timestamp-granular leakage test; injury-report re-run is the headline number |
| Closing line is not captured on the free tier because nothing ran at tip-off | Live CLV, the primary metric, is missing | APScheduler inside `avaris serve`; missed-run reporting on the Usage page; `settle` marks CLV unavailable instead of failing; manual `daily --at close` fallback |
| Free-tier credits (500/month) run out mid-month | Picks or closing snapshots stop | Fixed 2 decision + 3 closing slots per day, no live opening snapshot (≈ 420 credits over 28 game days); guard defaults `monthly_credit_budget = 450`, `min_remaining_reserve = 30`; refusal order opening → closing → decision |
| Scheduler and jobs make Phase 5 too large for one session | Phase 5 overruns | Split into 5a (pipeline passes, settle, read endpoints) and 5b (scheduler, jobs) |
| Spread/total lines differ across books, so a cross-book consensus is meaningless | Wrong market probability, false edges | Per-book edge at each book's line; consensus only for reporting with at least 3 books at the same line |
| Preseason, play-in, playoffs, neutral-site and bubble games distort features or get bet by mistake | Bad tuning (bubble is inside the tuning window) and unintended bets | `season_type` and `neutral_site` on `games`; preseason dropped at ingest; betting regular season only; neutral-site test |
| Tip-off times and ET game dates missing or wrong | Wrong closing snapshot, late games on the wrong day | Schedule ingest with `tip_off_utc`; `game_date_et` derived; Odds API `commence_time` as fallback; Phase 1 done-when requires a tip-off for every game |
| `nba-injury-report` or historical injury PDFs unavailable | No availability feature for live use; no late-scratch re-run | Phase 2 smoke test before any ingest code; fallback is scraping the PDF URLs directly |
| Odds API pricing or historical coverage changed | Backfill cost or coverage assumptions wrong | Confirm pricing and run the 1-week test with ledger reconciliation before the full backfill |
| Optuna over weekly refits is too slow | Phase 3 does not finish in a session | One refit per season during trials, weekly only for the final comparison; resumable SQLite storage |
| Two jobs write DuckDB at once, or a long `train` blocks the API | Corruption or a hung UI | Background thread, process-wide job lock with `409`, `jobs` table and status endpoint |
| Cached stats for the in-progress season never pick up corrections | Stale features | `refetch_days` window on every `ingest stats` run |
| Correlated same-game bets overstake under Kelly | Bankroll variance higher than modeled | One bet per game per side direction; per-game stake cap |
| The model has no real edge; one holdout season is thin evidence | Losing money | Report must state plainly if there is no edge; 4-week paper-trading gate before real stakes |
| stats.nba.com throttles or blocks the sandbox proxy | Ingest stalls | Throttle to about 1 request/sec, resumable cache, user-run from the home network |

## Notes
- stats.nba.com throttles heavy use; run backfills from your home network.
- The sandbox blocks reading `.env.local`, so Odds API commands are always user-run.
- The `avaris serve` process must be running for the PWA to show data, and on game days for the scheduler to take the decision and closing snapshots. Offline, the window shows only the cached app shell.
- Playoff betting, Pinnacle as the closing benchmark and minutes redistribution when a star is out are follow-ups, not v1.
- Follow-up, not in v1: the fitted σ values and quarter stats could replace the hand-set parameters in the `nba-projected-total` skill.
