# Architecture Decision Records

One entry per binding decision. Newest first. Status is `accepted`, `superseded` or `proposed`.

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
