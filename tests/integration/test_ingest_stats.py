from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest
import respx

from avaris.db import connect, upsert
from avaris.ingest.nba_stats import parse_team_log
from avaris.ingest.runner import ingest_stats, insert_missing_games, log_date_from
from avaris.ingest.stats_client import RawCache, StatsClient, Throttle
from tests.conftest import load_stats_fixture

TODAY = date(2026, 10, 12)
SEASONS = ["2019-20", "2025-26", "2026-27"]


def count(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    row = con.execute(sql).fetchone()
    assert row is not None
    return int(row[0])


def make_client(tmp_path: Path) -> StatsClient:
    return StatsClient(RawCache(tmp_path / "cache"), Throttle(0.0), retry_wait_s=0.0)


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    return connect(tmp_path / "avaris.duckdb")


def test_ingest_fills_all_phase_1_tables(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, stats_api: respx.MockRouter
) -> None:
    ingest_stats(con, make_client(tmp_path), SEASONS, today=TODAY, refetch_days=7)

    assert count(con, "select count(*) from games") == 13
    assert count(con, "select count(*) from games where season_type = 'preseason'") == 2
    assert count(con, "select count(*) from team_games") == 20
    assert count(con, "select count(*) from team_games where season_type = 'cup_final'") == 2
    # 3 players per team-game, plus 3 extra on the Cup knockout game whose IST fixture
    # was trimmed to different players than its Regular Season one
    assert count(con, "select count(*) from player_games") == 63
    assert count(
        con, "select count(*) from (select game_id, player_id from player_games group by all)"
    ) == 63
    # Only 2025-26 has a recorded roster (4 players), served for all 30 teams
    assert count(con, "select count(*) from rosters") == 30 * 4
    assert count(con, "select count(*) from games where neutral_site and season = '2019-20'") == 4


def test_rerun_is_idempotent_and_finished_seasons_come_from_cache(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, stats_api: respx.MockRouter
) -> None:
    client = make_client(tmp_path)
    ingest_stats(con, client, SEASONS, today=TODAY, refetch_days=7)
    first = client.requests_made
    before = [count(con, f"select count(*) from {t}") for t in ("games", "team_games", "rosters")]

    ingest_stats(con, client, SEASONS, today=TODAY, refetch_days=7)

    after = [count(con, f"select count(*) from {t}") for t in ("games", "team_games", "rosters")]
    assert after == before
    # Only the in-progress season is refetched: schedule + 4 log types x 2 + 30 rosters
    assert client.requests_made - first == 1 + 8 + 30


def test_log_date_from_uses_refetch_window(con: duckdb.DuckDBPyConnection) -> None:
    assert log_date_from(con, "2025-26", finished=False, refetch_days=7) is None
    log = parse_team_log(load_stats_fixture("leaguegamelog", "2025-26_Regular-Season_T"), "2025-26")
    upsert(con, "team_games", log)
    latest = max(log["game_date_et"])
    assert log_date_from(con, "2025-26", finished=False, refetch_days=7) == latest - pd.Timedelta(
        days=7
    )
    assert log_date_from(con, "2025-26", finished=True, refetch_days=7) is None


def test_games_missing_from_schedule_are_added_from_logs(con: duckdb.DuckDBPyConnection) -> None:
    log = parse_team_log(load_stats_fixture("leaguegamelog", "2019-20_Regular-Season_T"), "2019-20")
    upsert(con, "team_games", log)
    insert_missing_games(con, "2019-20")
    row = con.execute(
        "select home_team_id, away_team_id, home_pts, away_pts, tip_off_utc, status, season_type "
        "from games where game_id = '0021900573'"
    ).fetchone()
    assert row == (1610612756, 1610612753, 98, 94, None, "final", "regular")
