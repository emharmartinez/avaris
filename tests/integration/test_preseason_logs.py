from datetime import date
from pathlib import Path

import duckdb
import pytest
import respx

from avaris.db import connect
from avaris.ingest.preseason_logs import ingest_preseason_logs
from avaris.ingest.stats_client import RawCache, StatsClient, Throttle

TODAY = date(2026, 10, 13)


def count(con: duckdb.DuckDBPyConnection, table: str) -> int:
    row = con.execute(f"select count(*) from {table}").fetchone()
    assert row is not None
    return int(row[0])


@pytest.fixture
def client(tmp_path: Path) -> StatsClient:
    return StatsClient(RawCache(tmp_path / "cache"), Throttle(0.0), retry_wait_s=0.0)


def test_preseason_logs_fill_their_own_table_only(
    tmp_path: Path, client: StatsClient, stats_api: respx.MockRouter
) -> None:
    con = connect(tmp_path / "a.duckdb")
    rows = ingest_preseason_logs(con, client, ["2019-20"], today=TODAY)
    assert rows == 18
    assert count(con, "preseason_player_games") == 18
    assert count(con, "player_games") == 0
    stored = con.execute(
        "select distinct season, season_type from preseason_player_games").fetchall()
    assert stored == [("2019-20", "preseason")]
    harden = con.execute(
        "select game_id, team_id, minutes from preseason_player_games where player_id = 201935"
    ).fetchone()
    assert harden == ("0011900002", 1610612745, 28.0)
    params = [dict(c.request.url.params) for c in stats_api.calls]
    assert [(p["SeasonType"], p["PlayerOrTeam"]) for p in params] == [("Pre Season", "P")]


def test_rerun_is_idempotent_and_served_from_cache(
    tmp_path: Path, client: StatsClient, stats_api: respx.MockRouter
) -> None:
    con = connect(tmp_path / "a.duckdb")
    ingest_preseason_logs(con, client, ["2019-20"], today=TODAY)
    ingest_preseason_logs(con, client, ["2019-20"], today=TODAY)
    assert count(con, "preseason_player_games") == 18
    assert client.requests_made == 1  # a finished season's log is cached for good
