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
| Stats data | **nba_api**: one `LeagueGameLog` call per season covers every team-game and player-game line; `CommonTeamRoster` for rosters |
| Odds data | **The Odds API** (httpx + tenacity): h2h/spreads/totals; historical from Jun 2020, 5-minute snapshots from Sep 2022 |
| Injuries | Official NBA pregame injury reports via `nba-injury-report` (2021-22+; AGPL, fine for personal use) |
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
- **Features** are computed strictly as of tip-off:
  - Elo.
  - Exponentially weighted ORtg, DRtg, pace and net rating, plus last-N windows.
  - Rest, back-to-back, 3 games in 4 nights, travel km and time-zone shift (arena CSV), altitude.
  - Home court, adjusted for the 2020-21 no-fans season.
  - Games played this season.
  - **Availability:** decay-weighted per-minute Game Score × expected minutes. Strength lost = full-strength sum minus available sum.
    - Training and backtests use who actually played. Live predictions use the injury report: Out and Doubtful count as absent; Questionable counts as 50%.
    - **No phantom absences:** a traded player leaves team A's set as soon as he appears for team B. Season rosters, plus a rule that 10+ straight misses with no injury-report entry means "off roster", cover waivers, two-way and G-League moves.
- **Market is not a feature.** The betting layer blends model and market: p = w·model + (1−w)·market, with w fitted on validation.
- **Betting layer:**
  - De-vig with multiplicative and Shin methods; consensus = median across books; track the best available price.
  - Bet when edge ≥ a threshold, sized at flat stake or ¼ Kelly with a per-bet cap.
- **Walk-forward evaluation:** train on seasons before S, test on S, retraining weekly inside the season. Models train from 2012-13; betting simulation runs 2020-21+. **2025-26 is a holdout, used once.**
- **Odds stop-gap (`CreditGuard`):**
  - Each run first calls `/v4/sports` (0 credits) to read `x-requests-remaining` and `x-requests-used`.
  - The cost is computed before every call: `10 × markets × regions` for historical, `markets × regions` for live, 1 for historical events.
  - A call is **refused** if it would exceed `max_credits_per_run`, `monthly_credit_budget` or `max_monthly_usd` (= used × `usd_per_credit`), or go below `min_remaining_reserve`.
  - Every call is written to the `api_usage` ledger. If the estimate and `x-requests-last` disagree, the run stops.
  - Every response is cached, so repeats are free. `--estimate` spends 0 credits. A real backfill needs `--confirm`.
- **Odds cost:**
  - Historical data needs a paid plan. The backfill is about 27–35k credits per season (30 credits per snapshot, 1 opening + 3–5 closing snapshots per game day), or ≈ 160–210k for 2020-21 to 2025-26.
  - Buy **one month of the 5M plan ($119)**, do the test run and the backfill in that month, then **downgrade to free**. Daily use is ≈ 270 credits/month, which fits the free 500.
- **DuckDB allows one writer process.** The FastAPI server owns the read-write connection. CLI jobs run in-process when the server is down, or through `POST /api/jobs/{daily,settle}` when it's up. The UI only reads DuckDB and never calls external APIs.

## Testing approach
- **TDD by default:** write a failing test first, make it pass, then refactor. This applies to all deterministic code:
  - `CreditGuard`, ledger, cache, de-vig, edge, staking, Elo, features, availability rules, distributions, API routes.
  - Web: data hooks, formatters, and components with logic (Vitest + React Testing Library).
- **Vitest environments (jsdom is slow, so use it only where a DOM is needed):**
  - Default environment is `node`. Two Vitest `projects`: `*.test.ts` runs in `node`, `*.test.tsx` runs in `jsdom`.
  - `node`: formatters, API client, query keys, data transforms, odds/edge display math, msw handlers (`msw/node`).
  - `jsdom`: component rendering, user interaction, and hooks tested with `renderHook`.
  - Keep logic out of components (plain `.ts` modules) so most tests stay in `node`.
- **Test-after is allowed only** for exploratory model tuning and report styling. Tests must still exist before the phase is done.
- **No live network in tests.** Use recorded stats, odds and injury responses from the cache, plus a small fixture DuckDB built by `tests/fixtures/`.
- **E2E tests:**
  1. **Pipeline E2E** (pytest, `@pytest.mark.e2e`): fixture responses → `avaris daily` → `avaris settle`. Asserts on picks, bets, CLV, P&L and `api_usage` rows.
  2. **UI E2E** (Playwright, `web/e2e/`): starts `avaris serve` on the fixture DB, then checks that every page renders real data, Bet Log can add and settle a bet, Usage shows spend vs. cap, and the manifest and service worker load.

## Layout (`/home/emhar/avaris`)
```
pyproject.toml  uv.lock  config.toml  .env.local  .gitignore
src/avaris/  config.py db.py cli.py
  ingest/    nba_stats.py odds_api.py injuries.py teams.py
  features/  elo.py team_form.py schedule.py availability.py build.py
  models/    baselines.py gbm.py calibration.py distributions.py registry.py
  betting/   devig.py edge.py staking.py
  backtest/  walkforward.py metrics.py report.py
  pipeline/  daily.py settle.py
  api/       main.py routes/{picks,performance,backtests,injuries,usage,bets,jobs}.py
web/         Next.js PWA (app/: today, performance, backtests, injuries, usage, bet-log; components/ui from shadcn; e2e/ Playwright)
data/ (gitignored)   artifacts/ (models, reports)
tests/       unit/ integration/ e2e/ fixtures/
```
DuckDB tables: `games`, `team_games`, `player_games`, `rosters`, `injury_reports`, `odds_snapshots` (game, book, market, side, line, price, snapshot_ts, kind open/close/live), `features`, `predictions`, `picks`, `bets`, `api_usage`.

## Phases (each sized for one session)

### Phase 1 — Foundation + stats data
- `git init` and `.gitignore` (data/, artifacts/, .env.local, .venv, node_modules, web/.next, web/out).
- uv project, ruff, pyright, config, Typer CLI, DuckDB schema.
- Test deps: `uv add --dev pytest pytest-cov hypothesis respx time-machine` (add `pytest-xdist` later if walk-forward tests get slow). Register the `e2e` pytest marker.
- Smoke test one stats.nba.com call. If the sandbox proxy blocks it, every ingest command becomes user-run via `! uv run avaris ...`.
- Ingest team and player game logs for 2012-13 to now, plus rosters (throttled to about 1 request/sec, resumable, cached).
- Team ID mapping and arena CSV.
- **Done when:** the gates pass, `avaris ingest stats` has filled `games`, `team_games`, `player_games` and `rosters`, and row counts match about 1,230 games per regular season.

### Phase 2 — Odds + injuries
- Odds API client with `CreditGuard`, ledger, cache and `--estimate`.
- Map Odds API team names to NBA IDs.
- Open/close snapshot scheduler (one closing snapshot per tip-time slot), and de-vig functions.
- Injury report ingest, mapped to player IDs.
- The user buys the plan and runs a 1-week test (`! uv run avaris odds backfill --from … --to … --confirm`). The ledger must reconcile with the headers before the user runs the full backfill.
- **Done when:**
  - Guard tests pass: the refusal cases, priming, and ledger rows.
  - `--estimate` spends 0 credits.
  - `odds_snapshots` covers 2020-21+ with matched game IDs (< 1% unmatched).
  - Injury reports cover 2021-22+.

### Phase 3 — Features + models
- All feature families, including the availability rules for trades and roster moves.
- Model ladder, LightGBM + Optuna, calibration, σ fitting, registry.
- **Done when:**
  - The leakage test passes: deleting all rows after date D leaves features for games on D unchanged.
  - The trade test passes.
  - Walk-forward results on validation seasons show LightGBM (or the rung that's kept) beating Elo on log loss and MAE.

### Phase 4 — Betting layer + backtest
- Consensus de-vig, model/market blend, edge thresholds, flat and ¼-Kelly staking.
- Walk-forward betting simulation for 2020-21 to 2024-25.
- Re-run on 2021-22+ using injury reports instead of actual availability, to measure the cost of late scratches.
- Markdown + chart report; then run once on the 2025-26 holdout.
- **Done when:** the report shows log loss vs. Elo and vs. the de-vigged close, ROI with a bootstrap confidence interval, CLV % and calibration plots. It states plainly if there's no edge.

### Phase 5 — Daily pipeline + API
- `avaris daily`: refresh stats, rosters and injuries → live odds (guarded) → features → predict → log picks.
- `avaris settle`: closing line + results → CLV and P&L.
- FastAPI read endpoints for picks, games, performance, backtests, injuries and usage; `POST` for the manual bet log and job triggers. The single-writer connection model described above.
- **Done when:** API tests pass (FastAPI TestClient), the pipeline E2E test passes, and on a game day `avaris daily` then `GET /api/picks/today` returns that day's games with model probability, market probability, edge and stake.

### Phase 6 — Desktop PWA
- Next.js App Router + TS + Tailwind v4, `output: 'export'` so it builds to static files in `web/out` (no Node server at runtime).
  - Static export rules: client-side data fetching (TanStack Query against `/api`), no server actions or route handlers, no dynamic segments without `generateStaticParams` (use query params for detail views).
  - In dev, `next dev` (port 3000) calls FastAPI at `localhost:8000` via `NEXT_PUBLIC_API_BASE`, with CORS allowed for `localhost:3000` (dev only). In prod the base is empty (same origin).
- shadcn/ui (`npx shadcn init`): Card, Table, Badge, Tabs, Dialog, Form, Sidebar, Chart.
- PWA: `app/manifest.ts`, icons, and a service worker caching the app shell.
- Pages:
  - **Today:** picks per game for ML, spread and total; model vs. market, edge, stake, injuries.
  - **Performance:** ROI, CLV, calibration.
  - **Backtests.**
  - **Injuries.**
  - **Usage:** credits used vs. budget.
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
  1. `avaris daily`
  2. `avaris serve`
  3. Open the installed PWA → Today shows the slate with edges.
  4. After the games, `avaris settle` → Performance updates with CLV.
- Cost: the `api_usage` ledger total matches the Odds API dashboard, and the Usage page shows the month's spend under the cap.

## Notes
- stats.nba.com throttles heavy use; run backfills from your home network.
- The sandbox blocks reading `.env.local`, so Odds API commands are always user-run.
- The `avaris serve` process must be running for the PWA to show data. Offline, the window shows only the cached app shell.
- Follow-up, not in v1: the fitted σ values and quarter stats could replace the hand-set parameters in the `nba-projected-total` skill.
