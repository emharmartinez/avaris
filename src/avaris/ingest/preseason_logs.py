from collections.abc import Callable
from datetime import date

import duckdb

from avaris.db import upsert
from avaris.ingest.endpoints import GAME_LOG, PRESEASON_LOG_TYPE, game_log_params
from avaris.ingest.nba_stats import parse_player_log
from avaris.ingest.stats_client import StatsClient
from avaris.seasons import is_finished

Progress = Callable[[str], None]
# Default first season: one before the rest fit window (2015-16)
FIRST_PRESEASON_LOG_SEASON = "2014-15"


def ingest_preseason_logs(
    con: duckdb.DuckDBPyConnection,
    client: StatsClient,
    seasons: list[str],
    today: date,
    progress: Progress = lambda _msg: None,
) -> int:
    # Preseason player box scores, one request per season, into preseason_player_games.
    # They fit the rest adjustment only and never reach player_games, which feeds features
    rows = 0
    for season in seasons:
        payload = client.get_json(
            GAME_LOG, game_log_params(season, PRESEASON_LOG_TYPE, "P"),
            final=is_finished(season, today),
        )
        n = upsert(con, "preseason_player_games", parse_player_log(payload, season))
        rows += n
        progress(f"{season}: {n} preseason player-games")
    return rows
