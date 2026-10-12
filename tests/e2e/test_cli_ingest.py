from datetime import UTC, datetime
from pathlib import Path

import pytest
import respx
import time_machine
from typer.testing import CliRunner

from avaris.cli import app
from avaris.db import connect

runner = CliRunner()


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        f'[paths]\ndb_path = "{tmp_path / "avaris.duckdb"}"\ncache_dir = "{tmp_path / "cache"}"\n'
        "[stats]\nmin_interval_s = 0.0\nfirst_season = \"2025-26\"\n"
    )
    return path


@pytest.mark.e2e
@time_machine.travel(datetime(2026, 10, 12, 16, 0, tzinfo=UTC), tick=False)
def test_ingest_stats_then_status(
    config: Path, tmp_path: Path, stats_api: respx.MockRouter
) -> None:
    result = runner.invoke(app, ["--config", str(config), "ingest", "stats"])
    assert result.exit_code == 0, result.output
    assert "2025-26:" in result.output
    assert "2026-27:" in result.output

    con = connect(tmp_path / "avaris.duckdb", read_only=True)
    seasons = con.execute("select distinct season from games order by 1").fetchall()
    assert seasons == [("2025-26",), ("2026-27",)]
    team_games = con.execute("select count(*) from team_games").fetchone()
    assert team_games == (8,)
    con.close()

    status = runner.invoke(app, ["--config", str(config), "ingest", "status"])
    assert status.exit_code == 0, status.output
    assert "2025-26" in status.output

    # The fixture season is a handful of games, so the done-when check must fail loudly
    checked = runner.invoke(app, ["--config", str(config), "ingest", "status", "--check"])
    assert checked.exit_code == 1
    assert "regular-season games, expected 1230" in checked.output


@pytest.mark.e2e
def test_db_init(config: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["--config", str(config), "db", "init"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "avaris.duckdb").exists()
