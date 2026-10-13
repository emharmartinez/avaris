# Avaris

Personal, single-user, local-only NBA analytics model. It predicts each game's home win probability, margin and total (with 80% intervals), explains each prediction, and tracks team ratings and injury impact. It is evaluated with proper scoring rules against Elo and naive baselines. A desktop PWA shows it all.

- **Plan:** `docs/plans/avaris-nba-analytics-model-build-plan.md`
- **Status:** `STATUS.md` · **Decisions:** `ADR.md` · **Changes:** `CHANGELOG.md`

## Setup

```
uv sync
uv run avaris db init
cd web && npm ci && npm run build   # the PWA, served by `avaris serve`
```

Configuration lives in `config.toml`. Any value can be overridden with an env var, e.g. `AVARIS_STATS__REFETCH_DAYS=3`.

## Stats ingest

```
uv run avaris ingest stats                     # 2012-13 to the current season
uv run avaris ingest stats --from 2025-26      # one season onward
uv run avaris ingest status --check            # per-season counts and data checks
```

- Pulls the schedule, team and player game logs and rosters from stats.nba.com at about 1 request/sec.
- Responses are cached in `data/cache/`. Finished seasons are fetched once; the current season is refetched each run, with game logs from `refetch_days` before the latest stored game.
- A full first run is about 500 requests (roughly 10-15 minutes). Reruns only touch the current season.

## Injury reports

```
uv run avaris ingest injuries                  # 2021-22 to the current season
uv run avaris ingest status --check            # includes injury report coverage
```

- Fetches the official NBA injury report PDFs each game's `decision_ts` resolves to (the latest report at or before tip-off - 60 min), plus the 1:30 pm ET report, at about 2 requests/sec. A missing report steps back one slot at a time.
- PDFs are cached in `data/cache/final/injuries/`; old missing slots are remembered in `injury_report_files`.

## Features and models

```
uv run avaris features build                   # rebuild features and team_ratings
uv run avaris tune                             # Optuna on 2015-16 to 2019-20 (resumable)
uv run avaris backtest --refit weekly          # walk-forward rung comparison
uv run avaris train --through 2026-10-20       # refit kept rungs, register artifacts
uv run avaris train --promote RUN_ID           # manual promote (after a rung or param change)
```

## Evaluation

```
uv run avaris evaluate                                             # 2020-21 to 2024-25, actual availability
uv run avaris evaluate --from 2021-22 --availability report        # decision injury report at test time
```

- Weekly walk-forward of the kept rungs against Elo and two naive baselines (home rate, season-to-date net rating), with 95% bootstrap CIs, paired differences to Elo, reliability diagrams, ECE, PIT histograms, interval coverage and per-family drivers (ADR-017).
- **Important!** The 2025-26 holdout was scored once (`docs/reports/holdout_used.json`); `evaluate`, `backtest` and `tune` refuse any window that reaches it.
- Results: `docs/reports/phase-4-evaluation.md`.

- Features are computed as of each game's `decision_ts` by one chronological event loop (ADR-015): Elo, exponentially weighted ORtg, DRtg, pace and net rating, rest, back-to-backs, travel and time-zone shift, altitude, home court and availability (strength lost, from who played or from the injury report).
- Model ladder per target: Elo (league-average total for `total`), logistic/ridge, LightGBM. The kept rung and frozen hyperparameters live in `config.toml` under `[models.*]`.
- Win probabilities use the model's own probabilities (isotonic calibration is a per-target option, off for `home_win`, ADR-016); margin and total use N(μ, σ) with σ fitted per `season_type` bucket from out-of-fold residuals.
- Artifacts go to `artifacts/models/<target>/<run_id>/` (`model.joblib`, `meta.json`); `artifacts/models/registry.json` points to production. Reports and Optuna's SQLite store are in `artifacts/`.

## Daily pipeline and API

```
uv run avaris daily                            # refresh, retrain if stale, predict, score
uv run avaris daily --offline                  # same on stored data, no stats or injury fetch
uv run avaris score                            # per-game scores of final predictions
uv run avaris serve                            # API on 127.0.0.1:8000; runs `daily` on startup
uv run avaris serve --no-daily
```

- `daily` predicts this season's games dated today (ET) and any earlier game still missing a final prediction. A prediction is **provisional** before tip-off - 60 min and **final** after; a final row is never rewritten. Reruns change nothing unless new data arrived (ADR-018).
- A game is predicted only by a model whose training cutoff (`through`) is on or before its date. Missed games are finalized with the current model before a stale model is retrained (older than `retrain_every_days`).
- Each prediction stores drivers (family contributions per target) and injury impact (strength lost per side and the players behind it) as JSON.
- **Single writer:** `serve` holds the read-write DuckDB connection. While it runs, `avaris daily`, `score` and `train` run as server jobs (`POST /api/jobs/{daily,score,train}`, one at a time, `409` when busy).
- **Endpoints:** `GET /api/health`, `/api/predictions/today`, `/api/predictions?date=`, `/api/games/{game_id}`, `/api/teams`, `/api/teams/{team_id}`, `/api/performance`, `/api/backtests`, `/api/injuries?date=`, `/api/jobs`, `/api/jobs/{job_id}`. Timestamps are UTC with a `Z`.
- **Important!** `model.joblib` is checked against the `model_sha256` in `meta.json` before loading. An artifact written before the hash existed is sealed with `avaris train --promote RUN_ID --target <t>`.

## Desktop app (PWA)

```
cd web && npm run build      # static export to web/out
uv run avaris serve          # open http://127.0.0.1:8000 in Chrome, then "Install app"
```

- **Pages:** Today (`/?date=`), Game (`/game/?id=`), Teams (`/teams/?id=`), Performance (`/performance/?season=`), Backtests (`/backtests/?name=`), Injuries (`/injuries/?date=`). The header's Refresh button runs `daily` as a server job and shows its progress.
- `serve` serves `web/out` at `/` (`[server] web_dir`) next to the API; there is no Node server at runtime. A service worker caches the app shell, never `/api`.
- **Performance drift:** live log loss and MAE per scope are compared with the 95% range of means of the same number of games resampled from a report-mode backtest (`[server] drift_reference`, default `evaluation_2021-22_2024-25`).
- **Dev:** `uv run avaris serve --dev` (CORS for loopback origins only) and, in `web/`, `NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev`.

## Data

DuckDB at `data/avaris.duckdb` (gitignored):

| Table | Contents |
|---|---|
| `games` | One row per game: `tip_off_utc` (naive UTC), `game_date_et`, `season_type`, venue, `neutral_site`, scores |
| `team_games` | Box score per team per game, with `is_home` and `opp_team_id` |
| `player_games` | Box score per player per game (players who played) |
| `rosters` | Season rosters per team |
| `injury_reports` | Injury report rows with `report_ts` (UTC), game, team, player ID (null if unmatched), status |
| `injury_report_files` | Report slots fetched (`ok`) or known missing |
| `features` | One row per game as of `decision_ts`, with `feature_hash` (rebuilt by `avaris features build`) |
| `team_ratings` | Elo, ORtg, DRtg, net rating, pace and games played per team as of each game |
| `predictions` | One row per game: `status` (provisional or final), `decision_ts`, runs, `p_home_win`, margin and total μ and σ, drivers and injuries JSON |
| `prediction_scores` | Per final prediction after the game: log loss, Brier, errors, 80% interval hits, PIT |
| `jobs` | Background jobs: kind, status, params, log tail |

Reference data in `src/avaris/data/`: `teams.csv`, `arenas.csv` (home arenas with coordinates, time zone, altitude) and `neutral_venues.csv` (bubble, international and Cup venues).

## Development

```
uv run ruff check
uv run pyright
uv run pytest                 # unit, integration and e2e
uv run pytest -m e2e          # CLI end-to-end only
```

Web, from `web/` (npm needs `--cache "$TMPDIR/npm-cache"` in the sandbox):

```
npm run lint && npm run typecheck && npm run test && npm run build
npm run test:e2e              # Playwright against tests/fixtures/web_server.py (frozen clock)
```

- Vitest runs `*.test.ts` in `node` and `*.test.tsx` (components) in `jsdom`; msw mocks the API.
- `test:e2e` builds the export, then starts the API on the synthetic league with the clock frozen at 2021-11-27 17:00 UTC.

Tests never hit the network: they use trimmed recorded responses in `tests/fixtures/stats/`, regenerated from the cache with `uv run python tests/fixtures/make_stats_fixtures.py`, and two recorded injury PDFs in `tests/fixtures/injuries/`.
