import json
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from avaris.cli import app

runner = CliRunner()
LGBM = 'n_estimators = 20\nnum_leaves = 4\nmin_child_samples = 5\n'


def write_config(tmp_path: Path, db: Path, holdout: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        f'[paths]\ndb_path = "{db}"\n'
        f'[models]\nartifacts_dir = "{tmp_path / "artifacts"}"\noof_seasons = 1\n'
        f'eval_first_season = "2021-22"\neval_last_season = "2021-22"\n'
        f'holdout_season = "{holdout}"\n'
        f'holdout_marker = "{tmp_path / "docs" / "holdout_used.json"}"\n'
        '[models.home_win]\nrung = "linear"\ncalibration = "none"\n'
        f'[models.margin]\nrung = "lgbm"\n[models.margin.lgbm]\n{LGBM}'
        '[models.total]\nrung = "linear"\n'
    )
    return path


def invoke(config: Path, *args: str) -> tuple[int, str]:
    result = runner.invoke(app, ["--config", str(config), *args])
    return result.exit_code, result.output


@pytest.mark.e2e
def test_evaluate_writes_report_charts_and_predictions(tmp_path: Path, synthetic_db: Path) -> None:
    config = write_config(tmp_path, synthetic_db, holdout="2025-26")
    code, out = invoke(config, "evaluate", "--availability", "actual", "--availability",
                       "report", "--n-boot", "20")
    assert code == 0, out
    report_dir = tmp_path / "artifacts" / "reports" / "evaluation_2021-22_2021-22"
    report = (report_dir / "report.md").read_text()
    assert "## Run: actual availability" in report and "## Run: report availability" in report
    assert (report_dir / "reliability_report.svg").exists()
    assert (report_dir / "predictions.csv.gz").exists()


@pytest.mark.e2e
def test_report_availability_needs_injury_reports(tmp_path: Path, synthetic_db: Path) -> None:
    config = write_config(tmp_path, synthetic_db, holdout="2025-26")
    code, out = invoke(config, "evaluate", "--from", "2020-21", "--availability", "report")
    assert code != 0 and "injury reports start in 2021-22" in out


def finish_season(db: Path, season: str) -> None:
    # The synthetic 2021-22 ends with unplayed rounds; a holdout needs a finished season
    con = duckdb.connect(str(db))
    con.execute("delete from games where season = ? and status <> 'final'", [season])
    con.close()


@pytest.mark.e2e
@pytest.mark.parametrize("args", [
    ("evaluate", "--from", "2021-22", "--to", "2021-22"),
    ("evaluate", "--to", "2021"),
    ("backtest", "--from", "2021-22", "--to", "2021-22"),
    ("backtest", "--to", "2021"),
])
def test_only_evaluate_holdout_scores_the_holdout(
    tmp_path: Path, synthetic_db: Path, args: tuple[str, ...]
) -> None:
    config = write_config(tmp_path, synthetic_db, holdout="2021-22")
    code, out = invoke(config, *args)
    assert code != 0
    assert "--holdout" in out or "season label" in out


@pytest.mark.e2e
def test_holdout_needs_a_finished_season(tmp_path: Path, synthetic_db: Path) -> None:
    config = write_config(tmp_path, synthetic_db, holdout="2021-22")
    code, out = invoke(config, "evaluate", "--holdout", "--n-boot", "20")
    assert code != 0 and "not final" in out
    assert not (tmp_path / "docs" / "holdout_used.json").exists()


@pytest.mark.e2e
def test_holdout_is_scored_once_in_both_modes(tmp_path: Path, synthetic_db: Path) -> None:
    finish_season(synthetic_db, "2021-22")
    config = write_config(tmp_path, synthetic_db, holdout="2021-22")
    code, out = invoke(config, "evaluate", "--holdout", "--availability", "actual")
    assert code != 0 and "both availability modes" in out
    code, out = invoke(config, "evaluate", "--holdout", "--n-boot", "20")
    assert code == 0, out
    marker_path = tmp_path / "docs" / "holdout_used.json"
    marker = json.loads(marker_path.read_text())
    assert marker["season"] == "2021-22" and marker["status"] == "scored"
    assert marker["availability"] == ["actual", "report"]
    report = (tmp_path / "artifacts" / "reports" / "holdout_2021-22" / "report.md").read_text()
    assert "## Run: actual availability" in report and "## Run: report availability" in report
    code, out = invoke(config, "evaluate", "--holdout")
    assert code != 0 and "already been scored" in out
    # Losing the marker does not reopen it while the holdout report exists
    marker_path.unlink()
    code, out = invoke(config, "evaluate", "--holdout")
    assert code != 0 and "already been scored" in out
