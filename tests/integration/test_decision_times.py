from datetime import timedelta
from pathlib import Path

import duckdb
import pytest

from avaris.features.decision_time import decision_times
from tests.conftest import records_by


@pytest.fixture
def con(synthetic_db: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(synthetic_db))


def test_one_decision_ts_per_game_with_a_tip_off(con: duckdb.DuckDBPyConnection) -> None:
    times = decision_times(con)
    row = con.execute("select count(*) from games where tip_off_utc is not null").fetchone()
    assert row is not None
    assert len(times) == row[0] == times["game_id"].nunique()


def test_report_before_cutoff_wins_over_later_same_day_report(
    con: duckdb.DuckDBPyConnection,
) -> None:
    # 2021-22 games have reports at tip - 6 h, tip - 90 min and tip - 30 min
    rows = records_by(decision_times(con), "game_id")
    game = rows["0022100003"]
    assert game["report_ts"] == game["tip_off_utc"] - timedelta(minutes=90)
    assert game["decision_ts"] == game["report_ts"]


def test_no_report_falls_back_to_tip_minus_60(con: duckdb.DuckDBPyConnection) -> None:
    rows = records_by(decision_times(con), "game_id")
    for game_id in ("0022000003", "0012100001"):  # 2020-21 regular, 2021-22 preseason
        game = rows[game_id]
        assert game["report_ts"] is None
        assert game["decision_ts"] == game["tip_off_utc"] - timedelta(minutes=60)
