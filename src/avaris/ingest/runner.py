from collections.abc import Callable
from datetime import date, timedelta

import duckdb
import pandas as pd

from avaris.db import upsert
from avaris.ingest.endpoints import (
    GAME_LOG,
    ROSTER,
    SCHEDULE,
    game_log_params,
    log_season_types,
    roster_params,
    schedule_params,
)
from avaris.ingest.nba_schedule import parse_schedule
from avaris.ingest.nba_stats import parse_player_log, parse_roster, parse_team_log
from avaris.ingest.stats_client import StatsClient
from avaris.ingest.teams import Venues, load_teams
from avaris.seasons import is_finished

Progress = Callable[[str], None]


def log_date_from(
    con: duckdb.DuckDBPyConnection, season: str, finished: bool, refetch_days: int
) -> date | None:
    # In-progress season: refetch from refetch_days before the latest stored game, so
    # stat corrections land; a finished season, or a first fetch, pulls the whole log
    if finished:
        return None
    row = con.execute(
        "select max(game_date_et) from team_games where season = ?", [season]
    ).fetchone()
    latest = row[0] if row else None
    return latest - timedelta(days=refetch_days) if latest else None


def insert_missing_games(con: duckdb.DuckDBPyConnection, season: str) -> None:
    # Games present in the logs but not in the schedule get a row without tip-off time
    con.execute(
        """
        insert or ignore into games (game_id, season, season_type, game_date_et, tip_off_utc,
            home_team_id, away_team_id, home_pts, away_pts, status, neutral_site)
        select h.game_id, h.season, h.season_type, h.game_date_et, null,
            h.team_id, a.team_id, h.pts, a.pts, 'final', false
        from team_games h
        join team_games a on a.game_id = h.game_id and not a.is_home
        where h.is_home and h.season = ?
        """,
        [season],
    )


def _ingest_schedule(
    con: duckdb.DuckDBPyConnection, client: StatsClient, season: str, final: bool, venues: Venues
) -> int:
    payload = client.get_json(SCHEDULE, schedule_params(season), final=final)
    return upsert(con, "games", parse_schedule(payload, season, venues))


def _ingest_logs(
    con: duckdb.DuckDBPyConnection,
    client: StatsClient,
    season: str,
    final: bool,
    date_from: date | None,
) -> tuple[int, int]:
    team_frames, player_frames = [], []
    for season_type in log_season_types(season):
        team = client.get_json(
            GAME_LOG, game_log_params(season, season_type, "T", date_from), final
        )
        player = client.get_json(
            GAME_LOG, game_log_params(season, season_type, "P", date_from), final
        )
        team_frames.append(parse_team_log(team, season))
        player_frames.append(parse_player_log(player, season))
    # Cup group and knockout games appear in both the Regular Season and IST logs
    teams = pd.concat(team_frames).drop_duplicates(["game_id", "team_id"])
    players = pd.concat(player_frames).drop_duplicates(["game_id", "player_id"])
    return upsert(con, "team_games", teams), upsert(con, "player_games", players)


def _ingest_rosters(
    con: duckdb.DuckDBPyConnection, client: StatsClient, season: str, final: bool
) -> int:
    rows = 0
    for team_id in load_teams()["team_id"]:
        payload = client.get_json(ROSTER, roster_params(season, int(team_id)), final=final)
        rows += upsert(con, "rosters", parse_roster(payload, season, int(team_id)))
    return rows


def ingest_stats(
    con: duckdb.DuckDBPyConnection,
    client: StatsClient,
    seasons: list[str],
    today: date,
    refetch_days: int,
    rosters: bool = True,
    progress: Progress = lambda _msg: None,
) -> None:
    venues = Venues.load()
    for season in seasons:
        final = is_finished(season, today)
        games = _ingest_schedule(con, client, season, final, venues)
        date_from = log_date_from(con, season, final, refetch_days)
        team_rows, player_rows = _ingest_logs(con, client, season, final, date_from)
        insert_missing_games(con, season)
        roster_rows = _ingest_rosters(con, client, season, final) if rosters else 0
        progress(
            f"{season}: {games} games, {team_rows} team-games, {player_rows} player-games, "
            f"{roster_rows} roster rows"
            + (f" (logs since {date_from})" if date_from else "")
        )
