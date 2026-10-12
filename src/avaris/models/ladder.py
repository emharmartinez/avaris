from typing import Any, Literal, Protocol, Self

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

Target = Literal["home_win", "margin", "total"]
Rung = Literal["elo", "linear", "lgbm"]
TARGETS: tuple[Target, ...] = ("home_win", "margin", "total")
RUNGS: tuple[Rung, ...] = ("elo", "linear", "lgbm")
# Rung 0 reads these as-of columns: Elo win probability and margin, league-average total
ELO_COLUMN = {"home_win": "elo_prob", "margin": "elo_margin", "total": "league_total"}


class Model(Protocol):
    def fit(self, x: pd.DataFrame, y: np.ndarray) -> Self: ...
    def predict(self, x: pd.DataFrame) -> np.ndarray: ...


class EloRung:
    def __init__(self, target: str) -> None:
        self.column = ELO_COLUMN[target]

    def fit(self, x: pd.DataFrame, y: np.ndarray) -> Self:
        return self

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return x[self.column].to_numpy(dtype=float)


class SklearnRung:
    # Logistic/ridge on standardized, median-imputed features, or LightGBM; win
    # probability for home_win, mean otherwise
    def __init__(self, target: str, estimator: Any) -> None:
        self.classifier = target == "home_win"
        self.estimator = estimator

    def fit(self, x: pd.DataFrame, y: np.ndarray) -> Self:
        self.estimator.fit(x, y)
        return self

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        if self.classifier:
            return np.asarray(self.estimator.predict_proba(x)[:, 1], dtype=float)
        return np.asarray(self.estimator.predict(x), dtype=float)


def _linear(target: str, params: dict[str, Any], seed: int) -> Pipeline:
    if target == "home_win":
        model: Any = LogisticRegression(C=params.get("C", 1.0), max_iter=2000, random_state=seed)
    else:
        model = Ridge(alpha=params.get("alpha", 1.0))
    imputer = SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)
    return make_pipeline(imputer, StandardScaler(), model)


def _lgbm(target: str, params: dict[str, Any], seed: int) -> Any:
    kwargs = {"random_state": seed, "verbose": -1, "n_jobs": 1, **params}
    if kwargs.get("subsample", 1.0) < 1.0:
        kwargs.setdefault("subsample_freq", 1)
    if target == "home_win":
        return lgb.LGBMClassifier(**kwargs)
    return lgb.LGBMRegressor(**kwargs)


def make_rung(target: str, rung: str, params: dict[str, Any], seed: int) -> Model:
    if rung == "elo":
        return EloRung(target)
    if rung == "linear":
        return SklearnRung(target, _linear(target, params, seed))
    if rung == "lgbm":
        return SklearnRung(target, _lgbm(target, params, seed))
    raise ValueError(f"unknown rung {rung}")
