from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import respx

from avaris.config import InjurySettings, PathsSettings, Settings, StatsSettings
from avaris.db import connect
from avaris.ingest.injuries import BASE_URL
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
