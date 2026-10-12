from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from avaris.backtest.metrics import primary_metric, score
from avaris.features.build import AvailabilityMode, model_frame
from avaris.models.calibration import IsotonicCalibrator
from avaris.models.dataset import xy
from avaris.models.distributions import fit_sigma, sigma_for
from avaris.models.ladder import Model, make_rung


@dataclass
class Calibration:
    # Fitted on out-of-fold predictions: isotonic for home_win (not Elo), sigma per bucket
    # for margin and total
    calibrator: IsotonicCalibrator | None = None
    sigma: dict[str, float] = field(default_factory=dict)
    oof_metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class GamePredictor:
    target: str
    rung: str
    params: dict[str, Any]
    model: Model
    calibration: Calibration

    def predict(
        self, features: pd.DataFrame, availability: AvailabilityMode = "actual"
    ) -> pd.DataFrame:
        # home_win: p_home_win; margin and total: mu and sigma
        raw = self.model.predict(model_frame(features, availability))
        return finish(self.target, raw, features["season_type"], self.calibration)


def finish(
    target: str, raw: np.ndarray, season_types: pd.Series, calibration: Calibration
) -> pd.DataFrame:
    if target == "home_win":
        p = calibration.calibrator.transform(raw) if calibration.calibrator else raw
        return pd.DataFrame({"pred": p, "sigma": np.nan}, index=season_types.index)
    sigma = sigma_for(calibration.sigma, season_types) if calibration.sigma else np.nan
    return pd.DataFrame({"pred": raw, "sigma": sigma}, index=season_types.index)


def oof_predictions(
    data: pd.DataFrame, target: str, rung: str, params: dict[str, Any], seed: int,
    oof_seasons: int,
) -> pd.DataFrame:
    # Season-wise forward chaining over the last oof_seasons seasons of data: fit on
    # earlier seasons, predict the season
    seasons = sorted(data.loc[data[target].notna(), "season"].unique())
    frames = []
    for season in seasons[1:][-oof_seasons:]:
        x_train, y_train = xy(data[data["season"] < season], target)
        test = data[(data["season"] == season) & data[target].notna()]
        x_test, y_test = xy(test, target)
        raw = make_rung(target, rung, params, seed).fit(x_train, y_train).predict(x_test)
        frames.append(pd.DataFrame({
            "season_type": test["season_type"].to_numpy(), "y": y_test, "raw": raw,
        }))
    return pd.concat(frames, ignore_index=True)


def calibrate(target: str, rung: str, oof: pd.DataFrame) -> Calibration:
    y, raw = oof["y"].to_numpy(), oof["raw"].to_numpy()
    cal = Calibration(oof_metrics=score(target, y, raw))
    if target == "home_win":
        if rung != "elo":
            cal.calibrator = IsotonicCalibrator().fit(raw, y)
    else:
        cal.sigma = fit_sigma(y - raw, oof["season_type"])
    return cal


def fit_predictor(
    data: pd.DataFrame, target: str, rung: str, params: dict[str, Any], seed: int,
    oof_seasons: int,
) -> GamePredictor:
    # Calibration and sigma from out-of-fold predictions, then a refit on every row
    cal = calibrate(target, rung, oof_predictions(data, target, rung, params, seed, oof_seasons))
    x, y = xy(data, target)
    model = make_rung(target, rung, params, seed).fit(x, y)
    return GamePredictor(target, rung, params, model, cal)


def oof_metric(predictor: GamePredictor) -> float:
    return predictor.calibration.oof_metrics[primary_metric(predictor.target)]
