import json
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import httpx
import pandas as pd
import pytest
import respx

from avaris.db import connect, upsert
from avaris.ingest.espn import EspnClient, ingest_espn
from avaris.ingest.stats_client import Throttle
from tests.conftest import ESPN_FIXTURE

NYK, TOR, BOS, ATL = 1610612752, 1610612761, 1610612738, 1610612737
BRUNSON = 1628973
TIP = datetime(2026, 10, 13, 23, 30)  # NYK @ TOR, naive UTC
NOON = datetime(2026, 10, 13, 16, 0)
WINDOW = 36.0


def game(
    game_id: str, season_type: str, tip: datetime, home: int = TOR, away: int = NYK,
    season: str = "2026-27", status: str = "scheduled",
) -> dict[str, object]:
    return {
        "game_id": game_id, "season": season, "season_type": season_type,
        "game_date_et": (tip - timedelta(hours=5)).date(), "tip_off_utc": tip,
        "home_team_id": home, "away_team_id": away, "home_pts": None, "away_pts": None,
        "status": status, "venue": "Scotiabank Arena", "venue_city": "Toronto",
        "neutral_site": False,
    }


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    con = connect(tmp_path / "a.duckdb")
    upsert(con, "rosters", pd.DataFrame([{
        "season": "2026-27", "team_id": NYK, "player_id": BRUNSON,
        "player_name": "Jalen Brunson", "position": "G", "how_acquired": None,
    }]))
    return con


@pytest.fixture
def client(tmp_path: Path) -> EspnClient:
    return EspnClient(tmp_path / "cache", Throttle(0.0), retry_wait_s=0.0)


def snapshots(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("select * from espn_injury_snapshots order by team_id, player_name").df()


def fetches(con: duckdb.DuckDBPyConnection) -> list[tuple[datetime, datetime]]:
    return con.execute(
        "select fetched_at, snapshot_ts from espn_injury_fetches order by fetched_at").fetchall()


def test_a_due_preseason_game_stores_a_snapshot(
    con: duckdb.DuckDBPyConnection, client: EspnClient, stats_api: respx.MockRouter,
    tmp_path: Path,
) -> None:
    upsert(con, "games", pd.DataFrame([game("0012600050", "preseason", TIP)]))
    summary = ingest_espn(con, client, NOON, WINDOW)
    assert summary.fetched and summary.new_snapshot
    assert stats_api.routes["espn"].call_count == 1
    snap = snapshots(con)
    assert len(snap) == 10 and set(snap["fetched_at"]) == {NOON}
    brunson = snap[snap["player_name"] == "Jalen Brunson"].iloc[0]
    assert brunson["player_id"] == BRUNSON and brunson["team_id"] == NYK
    assert snap["player_id"].isna().sum() == 9  # only Brunson is on the stored rosters
    assert summary.unmatched == 9
    assert fetches(con) == [(NOON, NOON)]
    assert len(list((tmp_path / "cache" / "live" / "espn").iterdir())) == 1


def test_an_unchanged_list_is_one_snapshot_with_two_fetches(
    con: duckdb.DuckDBPyConnection, client: EspnClient, stats_api: respx.MockRouter,
) -> None:
    upsert(con, "games", pd.DataFrame([game("0012600050", "preseason", TIP)]))
    ingest_espn(con, client, NOON, WINDOW)
    later = NOON + timedelta(hours=2)
    summary = ingest_espn(con, client, later, WINDOW)
    assert summary.fetched and not summary.new_snapshot
    assert len(snapshots(con)) == 10
    assert fetches(con) == [(NOON, NOON), (later, NOON)]

    # A changed list is a new snapshot
    changed = json.loads(ESPN_FIXTURE.read_text())
    changed["injuries"][1]["injuries"] = changed["injuries"][1]["injuries"][:1]
    stats_api.routes["espn"].mock(return_value=httpx.Response(200, json=changed))
    last = later + timedelta(hours=1)
    assert ingest_espn(con, client, last, WINDOW).new_snapshot
    assert fetches(con)[-1] == (last, last)
    assert len(snapshots(con)[lambda d: d["fetched_at"] == last]) == 6


EARLIER = TIP - timedelta(days=2)


@pytest.mark.parametrize("earlier", [
    [],
    [game("0012600040", "preseason", EARLIER, status="final")],  # preseason never counts
    [game("0022600001", "regular", EARLIER, BOS, ATL, status="final")],  # other teams
    [game("0022600001", "regular", EARLIER, TOR, ATL, status="final")],  # NYK's opener
    [game("0022500001", "regular", EARLIER, season="2025-26", status="final")],  # last season
    [game("0022600001", "regular", EARLIER)],  # scheduled but not played (postponed)
])
def test_a_teams_first_game_of_the_season_is_due(
    con: duckdb.DuckDBPyConnection, client: EspnClient, stats_api: respx.MockRouter,
    earlier: list[dict[str, object]],
) -> None:
    # Before a team's first game the NBA report cannot be valued, so ESPN's list stands in
    # (ADR-025)
    upsert(con, "games", pd.DataFrame([game("0022600020", "regular", TIP), *earlier]))
    assert ingest_espn(con, client, NOON, WINDOW).fetched
    assert stats_api.routes["espn"].call_count == 1


def test_no_request_once_both_teams_have_opened_their_season(
    con: duckdb.DuckDBPyConnection, client: EspnClient, stats_api: respx.MockRouter,
) -> None:
    upsert(con, "games", pd.DataFrame([
        game("0022600001", "regular", EARLIER, status="final"),
        game("0022600020", "regular", TIP),
    ]))
    assert not ingest_espn(con, client, NOON, WINDOW).fetched
    assert stats_api.routes["espn"].call_count == 0


@pytest.mark.parametrize(("season_type", "tip"), [
    ("preseason", NOON + timedelta(hours=WINDOW, minutes=1)),  # too far ahead
    ("preseason", NOON - timedelta(minutes=1)),  # already started
    ("regular", NOON + timedelta(hours=WINDOW, minutes=1)),
])
def test_no_request_without_a_due_game(
    con: duckdb.DuckDBPyConnection, client: EspnClient, stats_api: respx.MockRouter,
    season_type: str, tip: datetime,
) -> None:
    upsert(con, "games", pd.DataFrame([game("0012600050", season_type, tip)]))
    summary = ingest_espn(con, client, NOON, WINDOW)
    assert not summary.fetched
    assert stats_api.routes["espn"].call_count == 0
    assert snapshots(con).empty and fetches(con) == []


def test_no_request_once_the_game_has_a_final_prediction(
    con: duckdb.DuckDBPyConnection, client: EspnClient, stats_api: respx.MockRouter,
) -> None:
    upsert(con, "games", pd.DataFrame([game("0012600050", "preseason", TIP)]))
    con.execute(
        "insert into predictions (game_id, status, decision_ts, predicted_at, feature_hash, "
        "home_win_run, margin_run, total_run, p_home_win, margin_mu, margin_sigma, "
        "total_mu, total_sigma, drivers, injuries) values ('0012600050', 'final', now(), "
        "now(), 'h', 'r', 'r', 'r', 0.5, 1, 10, 220, 15, '{}', '{}')"
    )
    assert not ingest_espn(con, client, NOON, WINDOW).fetched
    assert stats_api.routes["espn"].call_count == 0


def test_a_server_error_raises_and_stores_nothing(
    con: duckdb.DuckDBPyConnection, client: EspnClient, stats_api: respx.MockRouter,
) -> None:
    upsert(con, "games", pd.DataFrame([game("0012600050", "preseason", TIP)]))
    stats_api.routes["espn"].mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        ingest_espn(con, client, NOON, WINDOW)
    assert stats_api.routes["espn"].call_count == 3  # retried
    assert snapshots(con).empty and fetches(con) == []

