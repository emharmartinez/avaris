from typing import Any, Self

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, LogisticRegression

# Naive baselines for the Phase 4 evaluation, fitted on the walk-forward training window
BASELINES = ("naive_home", "naive_net")
HOME_WINDOW = 1230  # games: about one regular season
BASELINE_INPUT = {"home_win": "net_std_diff", "margin": "net_std_diff", "total": "exp_total_std"}


def baseline_frame(features: pd.DataFrame) -> pd.DataFrame:
    # Season-to-date net rating difference (0 while a team has no games this season) and
    # expected total from season-to-date ratings and pace (else the league total)
    f = features
    net = (f["home_ortg_std"] - f["home_drtg_std"]) - (f["away_ortg_std"] - f["away_drtg_std"])
    exp_total = (
        (f["home_pace_std"] + f["away_pace_std"]) / 2
        * (f["home_ortg_std"] + f["away_drtg_std"] + f["away_ortg_std"] + f["home_drtg_std"])
        / 200
    )
    return pd.DataFrame({
        "net_std_diff": net.fillna(0.0).astype(float),
        "exp_total_std": exp_total.fillna(f["league_total"]).astype(float),
    }, index=f.index)


class NaiveHome:
    # The home team at the recent home win rate (or mean home margin, mean total)
    def __init__(self, window: int = HOME_WINDOW) -> None:
        self.window = window
        self.mean = np.nan

    def fit(self, x: pd.DataFrame, y: np.ndarray) -> Self:
        self.mean = float(np.mean(y[-self.window:]))
        return self

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return np.full(len(x), self.mean)


class NaiveNet:
    # One-feature fit: logistic for home_win, least squares for margin and total
    def __init__(self, target: str) -> None:
        self.column = BASELINE_INPUT[target]
        self.classifier = target == "home_win"
        self.model: Any = LogisticRegression() if self.classifier else LinearRegression()

    def _x(self, x: pd.DataFrame) -> pd.DataFrame:
        return x[[self.column]].fillna(x[self.column].median())

    def fit(self, x: pd.DataFrame, y: np.ndarray) -> Self:
        self.model.fit(self._x(x), y)
        return self

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        if self.classifier:
            return np.asarray(self.model.predict_proba(self._x(x))[:, 1], dtype=float)
        return np.asarray(self.model.predict(self._x(x)), dtype=float)
