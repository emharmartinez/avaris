from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import duckdb
import httpx
import pandas as pd
import pytest
import respx

from avaris.db import connect, upsert
from avaris.ingest.injuries import BASE_URL, InjuryClient, ingest_injuries
from avaris.ingest.stats_client import Throttle
from avaris.ingest.status import injury_report
from tests.conftest import records_by

FIXTURES = Path(__file__).parents[1] / "fixtures" / "injuries"
NOW = datetime(2022, 1, 20, 12, 0)


@pytest.fixture
def injury_api() -> Iterator[respx.MockRouter]:
    # Serves the recorded PDFs; every other report is missing (403, as the NBA CDN does)
    def respond(request: httpx.Request) -> httpx.Response:
        path = FIXTURES / request.url.path.rsplit("/", 1)[-1]
        if path.exists():
            return httpx.Response(200, content=path.read_bytes())
        return httpx.Response(403, text="AccessDenied")

    with respx.mock(assert_all_called=False) as router:
        router.get(url__startswith=BASE_URL).mock(side_effect=respond)
        yield router


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    con = connect(tmp_path / "a.duckdb")
    # TOR@MIL tips at 6:30 pm ET, so its decision report is the 5:30 pm one
    upsert(con, "games", pd.DataFrame([{
        "game_id": "0022100620", "season": "2021-22", "season_type": "regular",
        "game_date_et": date(2022, 1, 15), "tip_off_utc": datetime(2022, 1, 15, 23, 30),
        "home_team_id": 1610612749, "away_team_id": 1610612761, "status": "final",
        "neutral_site": False,
    }]))
    upsert(con, "rosters", pd.DataFrame([{
        "season": "2021-22", "team_id": 1610612749, "player_id": 201950,
        "player_name": "Jrue Holiday", "position": None, "how_acquired": None,
    }]))
    return con


def test_ingest_fetches_decision_report_and_steps_back_past_missing(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, injury_api: respx.MockRouter
) -> None:
    client = InjuryClient(tmp_path / "cache", Throttle(0.0), retry_wait_s=0.0)
    summary = ingest_injuries(con, client, ["2021-22"], now_utc=NOW, max_step_back=2)

    assert summary.reports == 1
    files = dict(con.execute("select slot_ts, status from injury_report_files").fetchall())
    # Decision report found at once; the 1:30 pm report and 2 earlier slots are missing
    assert files == {
        datetime(2022, 1, 15, 22, 30): "ok",
        datetime(2022, 1, 15, 18, 30): "missing",
        datetime(2022, 1, 15, 17, 30): "missing",
        datetime(2022, 1, 15, 16, 30): "missing",
    }
    row = con.execute(
        "select game_id, player_id, status from injury_reports where player_name = 'Holiday, Jrue'"
    ).fetchone()
    assert row == ("0022100620", 201950, "out")
    total = con.execute("select count(*) from injury_reports").fetchone()
    assert total == (123,)

    # A rerun fetches nothing: reports are cached and misses are remembered
    requests = client.requests_made
    again = ingest_injuries(con, client, ["2021-22"], now_utc=NOW, max_step_back=2)
    assert again.reports == 0
    assert client.requests_made == requests


def test_recent_missing_slot_is_retried_later(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, injury_api: respx.MockRouter
) -> None:
    client = InjuryClient(tmp_path / "cache", Throttle(0.0), retry_wait_s=0.0)
    # 2 hours after the 1:30 pm slot: its miss is not remembered yet
    ingest_injuries(con, client, ["2021-22"], now_utc=datetime(2022, 1, 15, 20, 30),
                    max_step_back=0)
    files = con.execute("select count(*) from injury_report_files").fetchone()
    assert files == (0,)


def test_injury_report_counts_games_covered_by_decision_time(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, injury_api: respx.MockRouter
) -> None:
    client = InjuryClient(tmp_path / "cache", Throttle(0.0), retry_wait_s=0.0)
    ingest_injuries(con, client, ["2021-22"], now_utc=NOW, max_step_back=0)
    row = records_by(injury_report(con), "season")["2021-22"]
    assert row["regular_games"] == 1
    assert row["with_decision_report"] == 1
    # Only Jrue Holiday is in the fixture rosters
    assert row["named_entries"] - row["unmatched_players"] == 1
