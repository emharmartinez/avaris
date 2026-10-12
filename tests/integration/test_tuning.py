from pathlib import Path

import duckdb
import optuna
import pandas as pd
import pytest

from avaris.backtest.tuning import best_params, tune
from avaris.features.build import build_features
from avaris.models.dataset import with_targets


@pytest.fixture(scope="module")
def data(synthetic_db_template: Path) -> pd.DataFrame:
    con = duckdb.connect(str(synthetic_db_template), read_only=True)
    try:
        return with_targets(build_features(con).features, con)
    finally:
        con.close()


def run(data: pd.DataFrame, storage: Path, rung: str, n_trials: int) -> optuna.Study:
    return tune(
        data, "margin", rung, ["2020-21", "2021-22"], n_trials=n_trials, n_jobs=1, seed=7,
        storage=storage, overrides={"n_estimators": 10} if rung == "lgbm" else None,
    )


@pytest.mark.parametrize("rung", ["linear", "lgbm"])
def test_tuning_is_logged_and_resumable(data: pd.DataFrame, tmp_path: Path, rung: str) -> None:
    storage = tmp_path / "optuna.sqlite3"
    study = run(data, storage, rung, n_trials=2)
    assert len(study.trials) == 2 and storage.exists()
    # Asking for 3 trials again runs only the missing one
    study = run(data, storage, rung, n_trials=3)
    assert len(study.trials) == 3
    params = best_params(study, rung)
    assert params and all(isinstance(v, int | float) for v in params.values())
