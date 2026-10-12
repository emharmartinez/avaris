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
from avaris.ingest.status import season_report
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

    assert count(con, "select count(*) from games") == 15
    assert count(con, "select count(*) from games where season_type = 'preseason'") == 2
    assert count(con, "select count(*) from team_games") == 24
    assert count(con, "select count(*) from team_games where season_type = 'cup_final'") == 2
    # 3 players per team-game, plus 3 extra on the Cup knockout game whose IST fixture
    # was trimmed to different players than its Regular Season one
    assert count(con, "select count(*) from player_games") == 75
    # The recorded 4-player roster is served for every season and team
    assert count(con, "select count(*) from rosters") == 3 * 30 * 4
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


def test_in_progress_season_logs_use_the_refetch_window(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, stats_api: respx.MockRouter
) -> None:
    # Treat 2025-26 as in progress: the second run must ask for logs since latest - 7 days
    today = date(2026, 3, 1)
    ingest_stats(con, make_client(tmp_path), ["2025-26"], today=today, refetch_days=7)
    first_run_calls = len(stats_api.calls)
    ingest_stats(con, make_client(tmp_path), ["2025-26"], today=today, refetch_days=7)

    latest = con.execute(
        "select max(game_date_et) from team_games where season = '2025-26'"
    ).fetchone()
    assert latest is not None
    expected = (latest[0] - pd.Timedelta(days=7)).strftime("%m/%d/%Y")
    second_run = list(stats_api.calls)[first_run_calls:]
    log_calls = [c for c in second_run if c.request.url.path.endswith("/leaguegamelog")]
    assert len(log_calls) == 8
    assert {c.request.url.params["DateFrom"] for c in log_calls} == {expected}


def test_season_report_on_fixture_db(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, stats_api: respx.MockRouter
) -> None:
    ingest_stats(con, make_client(tmp_path), SEASONS, today=TODAY, refetch_days=7)
    report = season_report(con).set_index("season")

    bubble = report.loc["2019-20"].to_dict()
    assert bubble["regular"] == 4
    assert bubble["playoffs"] == 1
    assert bubble["play_in"] == 1
    assert bubble["neutral"] == 4
    assert bubble["bubble_neutral"] == 3
    assert bubble["bubble_not_neutral"] == 0
    assert bubble["unknown_venues"] == 0
    assert bubble["missing_tip_off"] == 0
    assert bubble["finals_missing_team_logs"] == 0
    assert bubble["team_games"] == 12

    recent = report.loc["2025-26"].to_dict()
    assert recent["preseason"] == 1
    assert recent["regular"] == 3
    assert recent["playoffs"] == 1
    assert recent["play_in"] == 1
    assert recent["cup_final"] == 1
    assert recent["neutral"] == 1  # Abu Dhabi preseason is excluded; Las Vegas Cup final counts
    assert recent["finals_missing_team_logs"] == 0
    assert recent["roster_teams"] == 30


def test_report_flags_final_games_without_logs(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, stats_api: respx.MockRouter
) -> None:
    ingest_stats(con, make_client(tmp_path), ["2019-20"], today=TODAY, refetch_days=7)
    con.execute("delete from team_games where game_id = '0021900573' and not is_home")
    report = season_report(con).set_index("season")
    assert report.loc["2019-20"].to_dict()["finals_missing_team_logs"] == 1


def test_season_logs_are_written_atomically(
    con: duckdb.DuckDBPyConnection,
    tmp_path: Path,
    stats_api: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A crash between the team and player upserts must not leave team rows behind,
    # or the next run's refetch window would skip the missing player rows for good
    import avaris.ingest.runner as runner

    real_upsert = runner.upsert

    def failing_upsert(c: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> int:
        if table == "player_games":
            raise RuntimeError("crash")
        return real_upsert(c, table, df)

    monkeypatch.setattr(runner, "upsert", failing_upsert)
    with pytest.raises(RuntimeError):
        ingest_stats(con, make_client(tmp_path), ["2019-20"], today=TODAY, refetch_days=7)
    assert count(con, "select count(*) from team_games") == 0
