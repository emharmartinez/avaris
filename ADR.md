# Architecture Decision Records

One entry per binding decision. Newest first. Status is `accepted`, `superseded` or `proposed`.

## ADR-021: The server stops itself when the app is closed, or from the app's Stop button

- **Date:** 2026-10-13 · **Status:** accepted
- **Decision:** `avaris serve` stops after `[server] idle_shutdown_min` (default 5, `0` = never; `serve --idle-min`) without any request. The open app polls `/api/health` every 60 s, also when minimized (`refetchIntervalInBackground`), so only a closed app goes quiet. A running job counts as activity and restarts the countdown. `POST /api/server/stop` (the header's power button, after an inline confirm) stops it at once; it is refused while a job runs (`409`), cross-site (`403`, the job guard) and when the app was not started by `serve` (`503`). Both set uvicorn's `should_exit`, so in-flight responses finish and the lifespan shutdown runs. The launcher's `-Stop` kills the pid in `data/serve.pid` only while it is still an `avaris serve`, since a self-stopped server leaves the file behind.
- **Why:** user decision: closing the app should not leave the server running.
- **Consequences:** a server started by hand from a terminal also stops when idle; pass `--idle-min 0` to keep it. Requests from another site (Origin or Sec-Fetch-Site) do not reset the countdown. Stopping takes the job lock for good, so no job can start between the decision and the exit (`409` "the server is stopping"). If Chrome freezes or discards a long-hidden app window, polling stops and the server may stop under it; the page then says the server is down and the user starts it again from the launcher. Raise `idle_shutdown_min` if that happens.

## ADR-020: An edge calculator compares odds the user types in with the model, in the browser only

- **Date:** 2026-10-13 · **Status:** accepted · narrows ADR-014
- **Decision:** the PWA gains an Edge tab (`/edge/?date=&game=`). The user picks a predicted game and types moneyline, spread and total odds (American or decimal). The page shows the model probability, the implied probability (vig removed proportionally when both prices are in, raw `1/odds` otherwise), edge in percentage points, EV per 100 staked and the model's fair price. Margin and total N(μ, σ) are read as integer scores in unit bands, so a whole-number line has a push probability (stake returned). A game cannot end tied, so the spread drops the margin = 0 band and rescales: -0.5, pk and +0.5 are the same bet and a pick'em never pushes. The odds format can be toggled without rounding what was typed. All maths runs in `web/src/lib/edge.ts`; nothing is fetched, stored or sent to the API.
- **Why:** user decision. A quick way to read the model against a price without bringing back odds ingestion.
- **Consequences:** ADR-014 still holds for the pipeline: no odds client, odds tables, market blend, staking, bet or spend tracking, and evaluation stays on proper scoring rules. The calculator is not evaluated and does not feed features or models.

## ADR-019: The PWA is a static export served by the API; drift is judged against resampled n-game means

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:**
  - `web/` is a Next.js 16 static export (`output: 'export'`, `trailingSlash: true`). `avaris serve` mounts `web/out` at `/` after the API routes; unknown `/api/*` paths are JSON 404s, unknown pages get `404.html`. Detail views use query params (`/game/?id=`), so no `generateStaticParams`. Fonts are system stacks, so builds never touch the network.
  - CORS is off by default. `avaris serve --dev` allows only loopback origins (`localhost`, `127.0.0.1`, `[::1]`, any port; anchored regex), GET and POST, header `content-type`, for `next dev` on another port; any page on another loopback port can then read the API. Job posts keep the Phase 5 cross-site guard, and the host check runs before CORS.
  - Every response carries `frame-ancestors 'none'`, `X-Frame-Options: DENY` and `nosniff`, so no page can frame the app and clickjack Refresh (headers come from FastAPI; a static export cannot set them).
  - Backtest reports render with `react-markdown` + `remark-gfm` and no raw HTML; links other than http(s) and anchors are dropped. Charts load through `<img>` (served with `default-src 'none'`).
  - A hand-written service worker caches the app shell: hashed `/_next/static` assets and icons cache-first, pages network-first (one entry per path) with a cached fallback, `/api` never cached. `npm run build` stamps the build id into its cache name, so a new build replaces the old cache. It registers in production builds only.
  - **Drift:** per scope, the live mean log loss, `margin` MAE and `total` MAE over `n` scored games are flagged when worse than the `1 - 0.05/3` quantile of 2,000 means of `n` games resampled (fixed seed) from the reference backtest's per-game errors: kept model, `availability = report`, same season types. One-sided (better than the reference is not drift) with a Bonferroni split over the three metrics: about 5% false alarms per scope at one look; looking daily over a season still raises the odds of one false flag. Reference: `[server] drift_reference` (a report name), default `evaluation_2021-22_2024-25` (not the holdout); a missing or unreadable reference drops only the drift block.
  - `/api/health` reports the app clock (`now`, `today`), so the UI's dates and countdowns follow the server.
  - Playwright runs against `tests/fixtures/web_server.py`: the app `avaris serve` builds (`create_app`), on the synthetic league, with the clock frozen at 2021-11-27 17:00 UTC and `daily` forced offline. Deviation from "E2E against `avaris serve`": the fixture league's games are in 2021.
- **Why:** one local process and no Node runtime; the browser can only reach the API from the app's own origin. A report's bootstrap CI describes a mean over ~5,000 games and would flag almost any 30-game live sample; resampling at the live `n` asks the right question.
- **Consequences:** `npm run build` must run before `serve` shows the app (the API works without it). E2E does not cover the real clock or network refresh. The drift range ignores era shifts between the reference seasons and now.

## ADR-018: Live predictions are provisional until tip-off - 60 min, final once, and never from a model that saw the game

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:**
  - `avaris daily` runs refresh → features → predict with the current production models → retrain when stale → predict again → score. It predicts this season's games dated on or before today (ET) that have no final prediction.
  - A prediction is final once `now >= tip_off - 60 min`, from the injury reports stored at that moment, and provisional before. `predictions` keeps one row per game: a provisional row is replaced only when a value changed, a final row is never replaced.
  - A game is predicted only if every target's run has `through <= game_date_et` (the model never trained on it). Missed games are therefore finalized before a retrain, which cuts off at today.
  - Retrain when a target has no production model, or its newest run (production or held candidate) has `through` `retrain_every_days` or more before today. A held candidate is a warning on every run until it is promoted or fixed; predictions keep using production.
  - A failed source refresh (network, a blocked or malformed response) is a warning; `daily` continues on stored data.
  - `avaris serve` owns the one read-write DuckDB connection; requests and jobs use cursors. Jobs run one at a time in a background thread (`409` when busy) and are recorded in `jobs`; jobs left running by a stopped server are marked failed at startup. CLI `daily`, `score` and `train` post a job when the database is locked.
  - Model artifacts are pickles: `model_sha256` in `meta.json` is verified before `joblib.load` (#6); an unhashed artifact is refused until a manual promote seals it. It catches corrupt, partial or swapped files; it is not tamper-proof, since anything that can write `model.joblib` can rewrite `meta.json`.
  - The API binds to 127.0.0.1 with no authentication (single user). It accepts only loopback `Host` headers (DNS rebinding) and refuses job posts a browser sends from another site (`Origin` or `Sec-Fetch-Site`).
- **Why:** a final prediction must be reproducible and honest: frozen at the decision time, from a model that had not seen the result. One current row per game keeps reruns idempotent. DuckDB allows one writer process.
- **Consequences:** an injury report for the decision slot that lands after a game was finalized is ignored for that game (the stored `report_ts` shows what was used). Games of finished seasons are never predicted live; the backtest covers them. A long job holds the lock; the UI shows its status.

## ADR-017: Evaluation against Elo and two naive baselines with paired bootstrap CIs; holdout scored once by the CLI

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:**
  - `avaris evaluate` runs the weekly walk-forward of each target's kept rung, the Elo rung, `naive_home` (mean of the target over the last 1,230 training games) and `naive_net` (one-feature logistic or least-squares fit on the season-to-date net rating difference; `total` on the season-to-date expected total). Season-to-date ratings are stored in `features` (migration 6) but are not model features, so the feature hash is unchanged.
  - Every metric gets a 95% percentile bootstrap CI over games (1,000 replicates). One draw of game indices per replicate is shared by all models, so the difference to Elo is a paired CI. "Does not beat Elo" means worse, or better with a paired CI that includes 0.
  - `--availability report` uses the decision-report availability for the test block only; training, OOF calibration and σ stay on who actually played, as in production.
  - Drivers are contributions on the link scale (log-odds for `home_win`): LightGBM `pred_contrib`, `coef × scaled value` for linear rungs with missing-value indicators folded into their feature. Every evaluation prediction checks `base + contributions = raw model output`.
  - The holdout is scored only by `avaris evaluate --holdout`: both availability modes, a finished season, and a marker in `docs/reports/holdout_used.json` (tracked in git) written before scoring. `backtest`, `tune` and plain `evaluate` refuse any window reaching the holdout season.
- **Why:** the plan's bar is Elo plus two naive baselines with confidence intervals; a paired CI makes "beats Elo" a statement rather than an impression. A guard in code keeps ADR-002's "used once" from depending on discipline.
- **Consequences:** ECE's bootstrap interval is biased upward and can sit above the point estimate. `naive_home`'s near-zero ECE is the trivial calibration of a constant predictor. Deleting the marker and the holdout report reopens the holdout; don't.

## ADR-016: Kept rung and calibration per target chosen on the tuning window

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** each target's rung and, for `home_win`, its calibration (`isotonic` or `none`) are chosen by the weekly walk-forward on 2015-16 to 2019-20 (regular-season log loss or MAE) and frozen in `config.toml` with the Optuna hyperparameters. Isotonic calibration is off for `home_win`.
- **Why:** isotonic regression fitted on 3 seasons of out-of-fold predictions raised walk-forward log loss by 0.003 (logistic) to 0.008 (LightGBM); logistic regression is already well calibrated. The plan said isotonic for every classifier; this keeps it as an option instead.
- **Consequences:** rung comparisons for `home_win` are raw against raw Elo. Phase 4 still checks calibration with reliability diagrams and ECE; isotonic can be turned back on per target.

## ADR-015: Point-in-time features from one event loop; availability in two modes

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:**
  - A game's result counts as known at tip-off + 3 h. `features/build.py` runs one chronological loop: result events update Elo, team form, league averages, schedule history and player rates; decision events (`decision_ts`) snapshot them. Results at the same instant apply first. The same loop fills `team_ratings`.
  - `decision_ts` uses only reports in `[tip - 12 h, tip - 60 min]` (`REPORT_WINDOW`, shared with the injury check). Reports also list later days, so entries are matched by game date.
  - Preseason games get decision events only: they never feed Elo, form, availability or rest and travel history, and are predicted at full strength (availability missing).
  - Availability is stored twice: `lost_actual_*` (set players who did not play, post-hoc by design) and `lost_report_*` (players listed Out or Doubtful count 1, Questionable 0.5, on the decision report's entries for the game's own date; 0 when there is no report). The model sees neutral `home_lost`/`away_lost`, filled by an availability mode: `actual` for training and walk-forward, `report` for live and the Phase 4 re-run.
  - A team's player set is the players whose latest appearance this season was for it, minus 10+ straight misses, plus every player listed for the team on the decision report (rated at last season's rate if he has not played this season). Availability is missing before a team's first game of the season. Rosters are not used: finished-season rosters are end-of-season snapshots.
  - Travel and time-zone shift are 0 after a gap of more than 7 days (bubble, openers); unknown venues give null. `home_court` is 0 at neutral sites; 2020-21 gets a `no_fans` flag and half the Elo home advantage. Elo skips the Cup final.
  - Feature hash = `FEATURE_VERSION` + model feature list; artifacts with another hash are refused.
- **Why:** one loop makes as-of semantics hold by construction and keeps features, ratings and availability consistent; the leakage test checks it at timestamp granularity.
- **Consequences:** changing feature semantics requires bumping `FEATURE_VERSION`, retuning and a manual promote. From 2021-22 listed long-term absentees stay in the set, so `lost_*` runs higher than in earlier seasons.
- **Era shift, measured in Phase 4 (issue #7):** mean `lost_actual` per regular-season team-game is 11-18 for 2012-13 to 2019-20, 22 in 2020-21 and 31-36 from 2021-22 (`full_strength` rises from 84-102 to 120-125). `lost_report` captures 82-85% of `lost_actual`. The availability rule is not changed: picking a rule from 2021-25 results would tune on scored seasons, and any change needs a feature version bump and a retune. Reopen only with a rule chosen without the scored seasons.

## ADR-014: Avaris is an analytics model; The Odds API is dropped

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** Avaris predicts every game's home win probability, margin and total (N(μ, σ), 80% interval) and shows drivers, team ratings and injury impact. No odds, market blend, bets, staking or spend tracking. The odds client, `CreditGuard`, slot planner, backfill and de-vig code are deleted; migration 4 drops `odds_events`, `odds_snapshots` and `api_usage`. No scheduler: `avaris daily` is idempotent and runs on `serve` startup and from the UI Refresh button. `settle` becomes `score`.
- **Why:** user decision. The historical odds backfill was paid-only and the goal is now accurate, calibrated predictions, not beating the market.
- **Consequences:** evaluation uses log loss, Brier, MAE, RMSE, calibration and interval coverage against Elo and two naive baselines, not CLV. Nothing shows absolute quality against the market; a free historical-lines benchmark is a follow-up. Supersedes ADR-005, 006, 008, 011 and 013.

## ADR-013: Odds stored per game and snapshot in decimal; the API key never leaves the request

- **Date:** 2026-10-12 · **Status:** superseded by ADR-014
- **Decision:** request `oddsFormat=decimal`. `odds_snapshots` holds every pregame outcome of the day's matched games per fetched snapshot, keyed by game, snapshot time, book, market and side, with `kind` = close (actual snapshot in [tip − 45, tip)), else decision, else open, else other. Events match games by both teams (either way round) and `commence_time` within 2 hours; moneyline and spread sides follow the stored game's home team. The key is passed only as the `apiKey` query parameter: cache paths are built from request fields, the ledger drops it, errors are scrubbed and raised `from None`, and httpx request logging is silenced.
- **Why:** de-vig works on decimal prices; neutral-site events can list the other team as home; the key must not leak into files or logs.
- **Consequences:** the American price for display is converted in the betting layer. Test fixtures are hand-built in the documented shape until the first paid run records real responses.

## ADR-012: Injury PDFs are fetched by Avaris and parsed with `nba-injury-report`

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** fetch `ak-static.cms.nba.com/referee/injury/` PDFs with a cached httpx client and parse them with `nba_injury_report.report._process_pdf` (pinned `==0.1.0`). `report_ts` comes from the PDF header. Per game day, fetch the report each game's `decision_ts` resolves to plus the 1:30 pm ET report, stepping back a slot when one is missing (403). Players match by normalized name: team-season, first initial + last name, season, then any season.
- **Why:** the package's own fetcher only knows the hourly URL format (`_05PM`, the 5:30 pm report). From 2025-12-22 reports are every 15 minutes as `_05_30PM`. Fetching every report would be about 20k requests.
- **Consequences:** a parser change upstream needs a version bump and the fixture tests. Players with no stats rows at all keep a null `player_id`.

## ADR-011: Snapshot slots are tip-time bands, shared by the backfill and live

- **Date:** 2026-10-12 · **Status:** superseded by ADR-014
- **Decision:** `ingest/odds_slots.py` plans each game day as 1 opening snapshot (09:00 ET), 1 decision snapshot per tip-time band (matinee before 17:00 ET, early before 21:30, late) at the band's earliest `decision_ts`, and closing snapshots placed 2 min before a tip and covering tips within 35 min (45 min less the 10-minute historical snapshot gap). The backfill covers every game; live caps closing slots at `live_max_close_slots`.
- **Why:** a snapshot after a game's `decision_ts` would leak; fixed clock slots miss matinee games entirely. The backfill must make the same decisions as live.
- **Consequences:** matinee days cost one extra decision snapshot. A typical day is 1 open + 2 decision + 3-4 close snapshots, about 30-36k credits per season as planned.

## ADR-010: Neutral site = schedule flag or a venue that is not the home team's arena

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** `neutral_site` is true when the schedule's `isNeutral` is set or the venue is not one of the home team's arenas in `src/avaris/data/arenas.csv`. Alternate home arenas (Spurs in Austin and the Alamodome, Bucks at Panther Arena, Raptors in Tampa 2020-21) are listed as home arenas. `neutral_venues.csv` holds coordinates for the bubble, international and Cup venues.
- **Why:** `isNeutral` is only populated from 2024-25; the 2019-20 bubble and older London, Mexico City and Paris games carry no flag.
- **Consequences:** `avaris ingest status` fails if a non-preseason game is played at a venue missing from both CSVs.

## ADR-009: Thin httpx client for stats.nba.com instead of `nba_api`

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** call `scheduleleaguev2`, `leaguegamelog` and `commonteamroster` directly with httpx, a full browser header set, a ~1 req/s throttle, tenacity retries and a gzip raw cache (`data/cache/final/` immutable for finished seasons, `live/` for the in-progress season, never read back).
- **Why:** stats.nba.com hangs without the full header set; httpx calls can be mocked with respx (the planned test stack), while `nba_api` uses requests; the raw cache needs the response JSON anyway.
- **Consequences:** endpoint parameters live in `ingest/endpoints.py`. Header changes on NBA's side are fixed in one place.

## ADR-008: Paper-trading gate before real stakes

- **Date:** 2026-10-12 · **Status:** superseded by ADR-014
- **Decision:** the first 4 weeks of 2026-27 are paper bets. Real stakes start only if live CLV is positive and ROI sits inside the backtest's bootstrap interval.
- **Why:** one holdout season is thin evidence of edge.
- **Consequences:** `bets` carries a paper/real flag; Performance shows both.

## ADR-007: Jobs run in a background thread under one process-wide lock

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** `POST /api/jobs/*` returns a `job_id`, runs in a background thread, one job at a time (`409` otherwise), status via `GET /api/jobs/{job_id}`, rows in a `jobs` table.
- **Why:** DuckDB has one writer; `train` is long-running and must not block the API.

## ADR-006: Closing lines are captured live by a scheduler inside `avaris serve`

- **Date:** 2026-10-12 · **Status:** superseded by ADR-014
- **Decision:** APScheduler in the server process runs a morning pass (no odds call), 2 decision slots and 3 closing slots per game day. No live opening snapshot on the free tier. Guard refusal order: opening, closing, decision. A refused closing snapshot marks CLV unavailable.
- **Why:** historical odds are paid-only. After the downgrade the closing line exists only if a snapshot was taken near tip-off. 5 calls × 3 credits × 28 game days ≈ 420 of 500 free credits.
- **Consequences:** the server must run on game days. Usage page shows next and missed runs.

## ADR-005: Spread and total edges are per book at the book's line

- **Date:** 2026-10-12 · **Status:** superseded by ADR-014
- **Decision:** no cross-book median price for spreads or totals. Each book's de-vigged price is a fair probability at its own line; model P(cover) is evaluated at that line; bet goes to the largest edge. Moneyline keeps the cross-book median. `w` is per target. `spread` is the home line, negative when home is favored.
- **Why:** books post different lines, so a median price across them is meaningless.

## ADR-004: `season_type` and `neutral_site` on `games`; preseason predicted but never a feature source

- **Date:** 2026-10-12 · **Status:** accepted (amended 2026-10-12 by ADR-014 and the preseason decision; was: betting on the regular season only, preseason dropped)
- **Decision:** preseason is stored with `season_type = preseason`. Every game is predicted and scored, preseason, play-in and playoffs included, with `season_type` as a model feature and σ fitted per bucket (preseason, regular, postseason). Headline metrics use the regular season; the other types are reported separately. Preseason results never update Elo, form or availability features, and preseason games are predicted at full strength (no injury report exists for preseason days). Neutral-site games get `home_court = 0` and venue-based travel.
- **Why:** the user wants preseason covered; preseason rotations are not representative, so they must not leak into regular-season features; playoffs have different home court and rest effects and a small sample; the 2019-20 bubble sits inside the tuning window.

## ADR-003: One `decision_ts` per game freezes injuries and features

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** `decision_ts` = latest injury report at or before tip-off − 60 min, else tip-off − 60 min. Same rule in backtests and live. Leakage test runs at timestamp granularity.
- **Why:** without one instant, backtests use post-hoc availability while live picks are made before the injury report lands, and the backtest metrics are not believable. Amended by ADR-014: no odds are frozen at it.
- **Consequences:** `daily` writes a provisional prediction before `decision_ts` and a final one after it; only final predictions are scored. Timestamps are UTC; `game_date` is the ET date of tip-off.

## ADR-002: Tuning on 2015-16 to 2019-20 only, frozen for 2020-21+, 2025-26 holdout used once

- **Date:** 2026-10-11 · **Status:** accepted
- **Decision:** Optuna and rung selection use walk-forward over 2015-16 to 2019-20 with one refit per season per trial. Hyperparameters and kept rung are frozen afterwards. Production model retrains weekly with frozen hyperparameters and a registry with promotion rules.
- **Why:** no tuning on scored seasons. Amended by ADR-014: the blend `w` and edge thresholds no longer exist.

## ADR-001: Stack and shape

- **Date:** 2026-10-11 · **Status:** accepted
- **Decision:** personal, single-user, local-only. Python 3.12 + uv, DuckDB, scikit-learn + LightGBM, FastAPI serving a statically exported Next.js + shadcn/ui PWA. stats.nba.com for stats (ADR-009), official NBA injury reports. Amended by ADR-014: no odds source.
- **Why:** see `docs/plans/avaris-nba-analytics-model-build-plan.md`.
