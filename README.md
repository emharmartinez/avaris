# Avaris

Personal, single-user, local-only NBA analytics model. It predicts each game's home win probability, margin and total (with 80% intervals), explains each prediction, and tracks team ratings and injury impact. It is evaluated with proper scoring rules against Elo and naive baselines.

- **Plan:** `docs/plans/avaris-nba-analytics-model-build-plan.md`
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

Reference data in `src/avaris/data/`: `teams.csv`, `arenas.csv` (home arenas with coordinates, time zone, altitude) and `neutral_venues.csv` (bubble, international and Cup venues).

## Development

```
uv run ruff check
uv run pyright
uv run pytest                 # unit, integration and e2e
uv run pytest -m e2e          # CLI end-to-end only
```

Tests never hit the network: they use trimmed recorded responses in `tests/fixtures/stats/`, regenerated from the cache with `uv run python tests/fixtures/make_stats_fixtures.py`, and two recorded injury PDFs in `tests/fixtures/injuries/`.
