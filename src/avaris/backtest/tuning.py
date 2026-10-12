from pathlib import Path
from typing import Any

import optuna
import pandas as pd

from avaris.backtest.metrics import primary_metric, score
from avaris.backtest.walkforward import regular_season, walk_forward
from avaris.features.build import FEATURE_VERSION


def search_space(trial: optuna.Trial, target: str, rung: str) -> dict[str, Any]:
    if rung == "linear":
        if target == "home_win":
            return {"C": trial.suggest_float("C", 1e-3, 10.0, log=True)}
        return {"alpha": trial.suggest_float("alpha", 1e-2, 1e4, log=True)}
    return {
        "n_estimators": trial.suggest_int("n_estimators", 100, 1500, log=True),
        "learning_rate": trial.suggest_float("learning_rate", 0.005, 0.1, log=True),
        "num_leaves": trial.suggest_int("num_leaves", 4, 64, log=True),
        "min_child_samples": trial.suggest_int("min_child_samples", 10, 300, log=True),
        "subsample": trial.suggest_float("subsample", 0.5, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.3, 1.0),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 30.0, log=True),
    }


def tune(
    data: pd.DataFrame,
    target: str,
    rung: str,
    seasons: list[str],
    n_trials: int,
    n_jobs: int,
    seed: int,
    storage: Path,
    overrides: dict[str, Any] | None = None,
) -> optuna.Study:
    # Walk-forward with one refit per season; the objective is the uncalibrated
    # regular-season log loss or MAE. Trials are stored in SQLite, so a rerun resumes
    storage.parent.mkdir(parents=True, exist_ok=True)
    study = optuna.create_study(
        study_name=f"{target}-{rung}-features-v{FEATURE_VERSION}",
        storage=f"sqlite:///{storage}",
        direction="minimize",
        sampler=optuna.samplers.TPESampler(seed=seed),
        load_if_exists=True,
    )

    def objective(trial: optuna.Trial) -> float:
        params = {**search_space(trial, target, rung), **(overrides or {})}
        preds = regular_season(walk_forward(
            data, target, rung, params, seed, seasons, refit="season", calibrated=False
        ))
        result = score(target, preds["y"].to_numpy(), preds["pred"].to_numpy())
        return result[primary_metric(target)]

    done = sum(t.state == optuna.trial.TrialState.COMPLETE for t in study.trials)
    if n_trials > done:
        study.optimize(objective, n_trials=n_trials - done, n_jobs=n_jobs)
    return study


def best_params(study: optuna.Study, rung: str) -> dict[str, Any]:
    params = dict(study.best_params)
    if rung == "lgbm":
        params["subsample_freq"] = 1
    return params
