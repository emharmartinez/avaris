import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest
import respx

from avaris.ingest.endpoints import GAME_LOG, ROSTER, SCHEDULE
from avaris.ingest.espn import ESPN_INJURIES_URL
from avaris.ingest.stats_client import BASE_URL
from tests.fixtures.synthetic import write_league

STATS_FIXTURES = Path(__file__).parent / "fixtures" / "stats"
ESPN_FIXTURE = Path(__file__).parent / "fixtures" / "espn" / "injuries.json"


def records_by(df: pd.DataFrame, *keys: str) -> dict[Any, dict[str, Any]]:
    # Typed row access for tests: {key or key tuple: row dict}
    rows: dict[Any, dict[str, Any]] = {}
    for row in df.to_dict("records"):
        key = tuple(row[k] for k in keys)
        rows[key[0] if len(keys) == 1 else key] = {str(k): v for k, v in row.items()}
    return rows


def load_stats_fixture(endpoint: str, name: str) -> dict[str, Any]:
    return json.loads((STATS_FIXTURES / endpoint / f"{name}.json").read_text())


def _empty_result_set(name: str) -> dict[str, Any]:
    return {"resultSets": [{"name": name, "headers": [], "rowSet": []}]}


def _fixture_response(request: httpx.Request) -> httpx.Response:
    endpoint = request.url.path.rsplit("/", 1)[-1]
    params = request.url.params
    season = params["Season"]
    if endpoint == SCHEDULE:
        name = season
    elif endpoint == GAME_LOG:
        season_type = params["SeasonType"].replace(" ", "-")
        name = f"{season}_{season_type}_{params['PlayerOrTeam']}"
    else:
        name = "2025-26"  # one recorded roster stands in for every season and team
    path = STATS_FIXTURES / endpoint / f"{name}.json"
    if path.exists():
        payload = json.loads(path.read_text())
        if endpoint == ROSTER:
            # Re-key the recorded roster to the requested team
            team_id = int(params["TeamID"])
            result = payload["resultSets"][0]
            col = result["headers"].index("TeamID")
            result["rowSet"] = [[*r[:col], team_id, *r[col + 1 :]] for r in result["rowSet"]]
        return httpx.Response(200, json=payload)
    if endpoint == SCHEDULE:
        return httpx.Response(200, json={"leagueSchedule": {"seasonYear": season, "gameDates": []}})
    return httpx.Response(200, json=_empty_result_set(endpoint))


@pytest.fixture
def stats_api() -> Iterator[respx.MockRouter]:
    # Serves recorded stats.nba.com responses and the recorded ESPN injury list (route
    # "espn"); any other host fails the test
    with respx.mock(assert_all_called=False) as router:
        router.get(url__startswith=BASE_URL).mock(side_effect=_fixture_response)
        router.get(url__startswith=ESPN_INJURIES_URL, name="espn").mock(
            return_value=httpx.Response(200, json=json.loads(ESPN_FIXTURE.read_text())))
        yield router


@pytest.fixture(scope="session")
def synthetic_db_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_league(tmp_path_factory.mktemp("synthetic") / "league.duckdb")


@pytest.fixture
def synthetic_db(synthetic_db_template: Path, tmp_path: Path) -> Path:
    # A fresh copy per test, so tests can delete rows
    path = tmp_path / "league.duckdb"
    shutil.copy(synthetic_db_template, path)
    return path
