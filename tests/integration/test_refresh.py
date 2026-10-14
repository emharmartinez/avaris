from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import httpx
import pandas as pd
import pytest
import respx

from avaris.config import EspnSettings, InjurySettings, PathsSettings, Settings, StatsSettings
from avaris.db import connect, upsert
from avaris.ingest.injuries import BASE_URL
from avaris.ingest.stats_client import BASE_URL as BASE_STATS_URL
from avaris.pipeline.daily import source_refresher

NOW = datetime(2026, 10, 12, 16, 0)  # naive UTC, 2026-27 preseason


@pytest.fixture
def injury_api() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        router.get(url__startswith=BASE_URL).mock(return_value=httpx.Response(403))
        yield router


def test_refresh_ingests_the_current_season(
    tmp_path: Path, stats_api: respx.MockRouter, injury_api: respx.MockRouter
) -> None:
    settings = Settings(
        paths=PathsSettings(cache_dir=tmp_path / "cache"),
        stats=StatsSettings(min_interval_s=0.0), injuries=InjurySettings(min_interval_s=0.0),
    )
    con = connect(tmp_path / "a.duckdb")
    messages: list[str] = []
    source_refresher(settings)(con, NOW, messages.append)
    seasons = con.execute("select distinct season from games").fetchall()
    assert seasons == [("2026-27",)]
    assert any(m.startswith("2026-27:") for m in messages)
    requested = {call.request.url.params.get("Season") for call in stats_api.calls}
    assert requested == {"2026-27"}


def _settings(tmp_path: Path, espn: bool = True) -> Settings:
    return Settings(
        paths=PathsSettings(cache_dir=tmp_path / "cache"),
        stats=StatsSettings(min_interval_s=0.0), injuries=InjurySettings(min_interval_s=0.0),
        espn=EspnSettings(min_interval_s=0.0, max_attempts=1, enabled=espn),
    )


def _due_preseason_game(con: duckdb.DuckDBPyConnection) -> None:
    upsert(con, "games", pd.DataFrame([{
        "game_id": "0012699999", "season": "2026-27", "season_type": "preseason",
        "game_date_et": NOW.date(), "tip_off_utc": NOW + timedelta(hours=7),
        "home_team_id": 1610612761, "away_team_id": 1610612752, "home_pts": None,
        "away_pts": None, "status": "scheduled", "venue": None, "venue_city": None,
        "neutral_site": False,
    }]))


def test_refresh_fetches_espn_for_a_due_preseason_game(
    tmp_path: Path, stats_api: respx.MockRouter, injury_api: respx.MockRouter
) -> None:
    con = connect(tmp_path / "a.duckdb")
    _due_preseason_game(con)
    source_refresher(_settings(tmp_path))(con, NOW, lambda _m: None)
    assert stats_api.routes["espn"].call_count == 1
    assert con.execute("select count(*) from espn_injury_fetches").fetchone() == (1,)


def test_an_espn_failure_is_a_warning_not_a_failed_refresh(
    tmp_path: Path, stats_api: respx.MockRouter, injury_api: respx.MockRouter
) -> None:
    con = connect(tmp_path / "a.duckdb")
    _due_preseason_game(con)
    stats_api.routes["espn"].mock(return_value=httpx.Response(503))
    messages: list[str] = []
    source_refresher(_settings(tmp_path))(con, NOW, messages.append)
    assert any(m.startswith("WARNING ESPN injuries failed") for m in messages)


def test_espn_can_be_switched_off(
    tmp_path: Path, stats_api: respx.MockRouter, injury_api: respx.MockRouter
) -> None:
    con = connect(tmp_path / "a.duckdb")
    _due_preseason_game(con)
    source_refresher(_settings(tmp_path, espn=False))(con, NOW, lambda _m: None)
    assert stats_api.routes["espn"].call_count == 0


def test_a_stats_failure_still_fetches_espn_then_fails_the_refresh(
    tmp_path: Path, stats_api: respx.MockRouter, injury_api: respx.MockRouter
) -> None:
    con = connect(tmp_path / "a.duckdb")
    _due_preseason_game(con)
    stats_api.get(url__startswith=BASE_STATS_URL).mock(return_value=httpx.Response(500))
    settings = _settings(tmp_path).model_copy(
        update={"stats": StatsSettings(min_interval_s=0.0, max_attempts=1)})
    with pytest.raises(httpx.HTTPStatusError):
        source_refresher(settings)(con, NOW, lambda _m: None)
    assert stats_api.routes["espn"].call_count == 1
