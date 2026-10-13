import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest
import time_machine
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from avaris.api.main import create_app
from avaris.cli import app
from avaris.config import load_settings
from tests.fixtures.live import D1

runner = CliRunner()
LGBM = 'n_estimators = 20\nnum_leaves = 4\nmin_child_samples = 5\n'
NOON_D1 = datetime(2021, 11, 26, 17, 0, tzinfo=UTC)
AFTER_CUTOFF_D1 = datetime(2021, 11, 26, 23, 30, tzinfo=UTC)  # tip - 30 min
NEXT_DAY = datetime(2021, 11, 27, 15, 0, tzinfo=UTC)


@pytest.fixture
def config(tmp_path: Path, synthetic_db: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        f'[paths]\ndb_path = "{synthetic_db}"\ncache_dir = "{tmp_path / "cache"}"\n'
        f'[models]\nartifacts_dir = "{tmp_path / "artifacts"}"\noof_seasons = 1\n'
        '[models.home_win]\nrung = "linear"\ncalibration = "none"\n'
        f'[models.margin]\nrung = "lgbm"\n[models.margin.lgbm]\n{LGBM}'
        '[models.total]\nrung = "linear"\n'
    )
    return path


def invoke(config: Path, *args: str) -> str:
    result = runner.invoke(app, ["--config", str(config), *args])
    assert result.exit_code == 0, result.output
    return result.output


def predictions(db: Path) -> list[tuple[str, str]]:
    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute("select game_id, status from predictions order by 1").fetchall()
    finally:
        con.close()


@pytest.mark.e2e
def test_train_daily_before_and_after_decision_ts_then_score(
    config: Path, synthetic_db: Path
) -> None:
    with time_machine.travel(NOON_D1, tick=False):
        assert invoke(config, "train", "--through", D1.isoformat()).count("promoted") == 3
        out = invoke(config, "daily", "--offline")
        assert "2 provisional, 0 final" in out
        assert [s for _, s in predictions(synthetic_db)] == ["provisional"] * 2
        assert "0 provisional, 0 final, 2 unchanged" in invoke(config, "daily", "--offline")

        # The done-when: today's games with probability, mu and 80% intervals, drivers, status
        con = duckdb.connect(str(synthetic_db))
        api = create_app(load_settings(config), con=con, daily_on_startup=False)
        with TestClient(api, base_url="http://127.0.0.1:8000") as client:
            games = client.get("/api/predictions/today").json()["games"]
        con.close()
        assert len(games) == 2
        for g in games:
            p = g["prediction"]
            assert p["status"] == "provisional" and 0 < p["p_home_win"] < 1
            assert p["margin"]["lo"] < p["margin"]["mu"] < p["margin"]["hi"]
            assert p["total"]["lo"] < p["total"]["mu"] < p["total"]["hi"]
            assert len(p["top_drivers"]["home_win"]) == 3

    with time_machine.travel(AFTER_CUTOFF_D1, tick=False):
        assert "0 provisional, 2 final" in invoke(config, "daily", "--offline")
        assert [s for _, s in predictions(synthetic_db)] == ["final"] * 2

    con = duckdb.connect(str(synthetic_db))
    con.execute("update games set home_pts = 101, away_pts = 99, status = 'final' "
                "where game_date_et = ?", [D1])
    con.close()
    with time_machine.travel(NEXT_DAY, tick=False):
        assert "2 scored" in invoke(config, "score")
        assert "0 scored" in invoke(config, "score")
    con = duckdb.connect(str(synthetic_db), read_only=True)
    scores = con.execute("select margin, margin_error, log_loss from prediction_scores").fetchall()
    row = con.execute("select drivers from predictions limit 1").fetchone()
    con.close()
    assert len(scores) == 2 and all(margin == 2 for margin, _, _ in scores)
    assert row is not None
    assert set(json.loads(row[0])) == {"home_win", "margin", "total"}
