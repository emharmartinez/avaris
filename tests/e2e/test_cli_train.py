import json
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from avaris.cli import app

runner = CliRunner()
LGBM = 'n_estimators = 20\nnum_leaves = 4\nmin_child_samples = 5\n'


@pytest.fixture
def config(tmp_path: Path, synthetic_db: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        f'[paths]\ndb_path = "{synthetic_db}"\n'
        f'[models]\nartifacts_dir = "{tmp_path / "artifacts"}"\noof_seasons = 1\n'
        'n_trials = 2\ntune_first_season = "2020-21"\ntune_last_season = "2021-22"\n'
        '[models.home_win]\nrung = "linear"\n'
        f'[models.margin]\nrung = "lgbm"\n[models.margin.lgbm]\n{LGBM}'
        f'[models.total.lgbm]\n{LGBM}'
    )
    return path


def invoke(config: Path, *args: str) -> str:
    result = runner.invoke(app, ["--config", str(config), *args])
    assert result.exit_code == 0, result.output
    return result.output


@pytest.mark.e2e
def test_features_train_and_manual_promote(
    config: Path, tmp_path: Path, synthetic_db: Path
) -> None:
    assert "features:" in invoke(config, "features", "build")
    con = duckdb.connect(str(synthetic_db), read_only=True)
    assert con.execute("select count(distinct feature_hash) from features").fetchone() == (1,)
    con.close()

    out = invoke(config, "train", "--through", "2021-11-10")
    assert out.count("promoted") == 3
    out = invoke(config, "train", "--through", "2021-11-10", "--target", "total")
    assert "candidate" in out
    models = tmp_path / "artifacts" / "models"
    registry = json.loads((models / "registry.json").read_text())
    candidate = registry["total"]["candidates"][0]
    assert f"total: promoted {candidate}" in invoke(config, "train", "--promote", candidate)
    registry = json.loads((models / "registry.json").read_text())
    assert registry["total"]["production"] == candidate


@pytest.mark.e2e
def test_tune_and_backtest(config: Path, tmp_path: Path) -> None:
    out = invoke(config, "tune", "--target", "margin", "--rung", "linear")
    assert "margin linear: best" in out
    assert (tmp_path / "artifacts" / "optuna.sqlite3").exists()
    out = invoke(config, "backtest", "--from", "2021-22", "--to", "2021-22", "--refit",
                 "season", "--target", "margin")
    assert "Kept rungs" in out
    report = tmp_path / "artifacts" / "reports" / "walkforward_2021-22_2021-22_season.md"
    assert "## margin" in report.read_text()
