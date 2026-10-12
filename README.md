# Avaris

Personal, single-user, local-only NBA betting model for moneyline, spread and total. It compares model probabilities with de-vigged sportsbook lines and is evaluated against the closing line.

- **Plan:** `docs/plans/avaris-nba-betting-model-build-plan.md`
- **Status:** `STATUS.md` · **Decisions:** `ADR.md` · **Changes:** `CHANGELOG.md`

## Setup

```
uv sync
uv run avaris db init
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

## Odds (The Odds API)

```
uv run avaris odds backfill --from 2022-01-10 --to 2022-01-16             # estimate only, offline
uv run avaris odds backfill --from 2022-01-10 --to 2022-01-16 --confirm \
    --max-credits 2000 --monthly-budget 250000                           # spends credits
uv run avaris odds usage                       # credits per month from the ledger
uv run avaris odds status --check              # open/decision/close coverage, unmatched events
```

- Needs `ODDS_API_KEY` in the environment or `.env.local`. Commands that spend credits are user-run.
- Every call goes through `CreditGuard` (per-run cap, monthly budget, USD cap, reserve) and is written to the `api_usage` ledger. Without `--confirm` the command only prints the estimate.
- Per game day the backfill takes 1 opening snapshot, 1 decision snapshot per tip-time band and the closing snapshots (ADR-011); responses are cached, so reruns are free.

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
| `odds_events` | Odds API events and the game each matched (or why not) |
| `odds_snapshots` | Pregame prices (decimal) per game, snapshot, book, market and side, with `kind` open/decision/close/other |
| `api_usage` | Ledger of every Odds API call: estimate, `x-requests-last`, usage headers, status |

Reference data in `src/avaris/data/`: `teams.csv`, `arenas.csv` (home arenas with coordinates, time zone, altitude) and `neutral_venues.csv` (bubble, international and Cup venues).

## Development

```
uv run ruff check
uv run pyright
uv run pytest                 # unit, integration and e2e
uv run pytest -m e2e          # CLI end-to-end only
```

Tests never hit the network: they use trimmed recorded responses in `tests/fixtures/stats/`, regenerated from the cache with `uv run python tests/fixtures/make_stats_fixtures.py`, two recorded injury PDFs in `tests/fixtures/injuries/`, and hand-built Odds API responses in `tests/odds_payloads.py` (to be replaced by recorded ones after the first paid run).
