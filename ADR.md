# Architecture Decision Records

One entry per binding decision. Newest first. Status is `accepted`, `superseded` or `proposed`.

## ADR-013: Odds stored per game and snapshot in decimal; the API key never leaves the request

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** request `oddsFormat=decimal`. `odds_snapshots` holds every pregame outcome of the day's matched games per fetched snapshot, keyed by game, snapshot time, book, market and side, with `kind` = close (actual snapshot in [tip − 45, tip)), else decision, else open, else other. Events match games by both teams (either way round) and `commence_time` within 2 hours; moneyline and spread sides follow the stored game's home team. The key is passed only as the `apiKey` query parameter: cache paths are built from request fields, the ledger drops it, errors are scrubbed and raised `from None`, and httpx request logging is silenced.
- **Why:** de-vig works on decimal prices; neutral-site events can list the other team as home; the key must not leak into files or logs.
- **Consequences:** the American price for display is converted in the betting layer. Test fixtures are hand-built in the documented shape until the first paid run records real responses.

## ADR-012: Injury PDFs are fetched by Avaris and parsed with `nba-injury-report`

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** fetch `ak-static.cms.nba.com/referee/injury/` PDFs with a cached httpx client and parse them with `nba_injury_report.report._process_pdf` (pinned `==0.1.0`). `report_ts` comes from the PDF header. Per game day, fetch the report each game's `decision_ts` resolves to plus the 1:30 pm ET report, stepping back a slot when one is missing (403). Players match by normalized name: team-season, first initial + last name, season, then any season.
- **Why:** the package's own fetcher only knows the hourly URL format (`_05PM`, the 5:30 pm report). From 2025-12-22 reports are every 15 minutes as `_05_30PM`. Fetching every report would be about 20k requests.
- **Consequences:** a parser change upstream needs a version bump and the fixture tests. Players with no stats rows at all keep a null `player_id`.

## ADR-011: Snapshot slots are tip-time bands, shared by the backfill and live

- **Date:** 2026-10-12 · **Status:** accepted
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

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** the first 4 weeks of 2026-27 are paper bets. Real stakes start only if live CLV is positive and ROI sits inside the backtest's bootstrap interval.
- **Why:** one holdout season is thin evidence of edge.
- **Consequences:** `bets` carries a paper/real flag; Performance shows both.

## ADR-007: Jobs run in a background thread under one process-wide lock

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** `POST /api/jobs/*` returns a `job_id`, runs in a background thread, one job at a time (`409` otherwise), status via `GET /api/jobs/{job_id}`, rows in a `jobs` table.
- **Why:** DuckDB has one writer; `train` is long-running and must not block the API.

## ADR-006: Closing lines are captured live by a scheduler inside `avaris serve`

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** APScheduler in the server process runs a morning pass (no odds call), 2 decision slots and 3 closing slots per game day. No live opening snapshot on the free tier. Guard refusal order: opening, closing, decision. A refused closing snapshot marks CLV unavailable.
- **Why:** historical odds are paid-only. After the downgrade the closing line exists only if a snapshot was taken near tip-off. 5 calls × 3 credits × 28 game days ≈ 420 of 500 free credits.
- **Consequences:** the server must run on game days. Usage page shows next and missed runs.

## ADR-005: Spread and total edges are per book at the book's line

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** no cross-book median price for spreads or totals. Each book's de-vigged price is a fair probability at its own line; model P(cover) is evaluated at that line; bet goes to the largest edge. Moneyline keeps the cross-book median. `w` is per target. `spread` is the home line, negative when home is favored.
- **Why:** books post different lines, so a median price across them is meaningless.

## ADR-004: Regular season only for betting; `season_type` and `neutral_site` on `games`

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** preseason is dropped at ingest. Training uses regular season, play-in and playoffs with `season_type` as a feature. Betting simulation and live bets cover regular season only in v1. Neutral-site games get `home_court = 0` and venue-based travel.
- **Why:** the Odds API lists preseason events; playoffs have different home court and rest effects and a small sample; the 2019-20 bubble sits inside the tuning window.

## ADR-003: One `decision_ts` per game freezes odds, injuries and features

- **Date:** 2026-10-12 · **Status:** accepted
- **Decision:** `decision_ts` = latest injury report at or before tip-off − 60 min, else tip-off − 60 min. Pick odds are the last snapshot at or before `decision_ts`; closing line is the last snapshot within 45 min before tip-off. Same rule in backtests and live. Leakage test runs at timestamp granularity.
- **Why:** without one instant, backtests use post-hoc availability while live picks are made before the injury report lands, and the backtest ROI is not believable.
- **Consequences:** `daily` runs in passes (morning provisional, decision final). Timestamps are UTC; `game_date` is the ET date of tip-off.

## ADR-002: Tuning on 2015-16 to 2019-20 only, frozen for 2020-21+, 2025-26 holdout used once

- **Date:** 2026-10-11 · **Status:** accepted
- **Decision:** Optuna and rung selection use walk-forward over 2015-16 to 2019-20 with one refit per season per trial. Hyperparameters and kept rung are frozen afterwards. `w` and thresholds are fitted walk-forward per season from 2020-21 (warm-up season). Production model retrains weekly with frozen hyperparameters and a registry with promotion rules.
- **Why:** no tuning on scored seasons; evaluation is against the de-vigged close.

## ADR-001: Stack and shape

- **Date:** 2026-10-11 · **Status:** accepted
- **Decision:** personal, single-user, local-only. Python 3.12 + uv, DuckDB, scikit-learn + LightGBM, FastAPI serving a statically exported Next.js + shadcn/ui PWA. nba_api for stats, The Odds API for odds behind `CreditGuard`, official NBA injury reports. Market odds are never a model feature; they enter only through the betting-layer blend.
- **Why:** see `docs/plans/avaris-nba-betting-model-build-plan.md`.
