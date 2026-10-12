from typing import Any, Literal

import numpy as np
import pandas as pd

from avaris.analytics.drivers import explain
from avaris.features.build import AvailabilityMode
from avaris.models.dataset import xy
from avaris.models.ladder import make_rung
from avaris.models.predictor import Calibration, calibrate, finish, oof_predictions

Refit = Literal["season", "weekly"]
WEEK_DAYS = 7


def _blocks(test: pd.DataFrame, refit: Refit) -> list[pd.DataFrame]:
    if refit == "season":
        return [test]
    dates = pd.to_datetime(test["game_date_et"])
    week = (dates - dates.min()).dt.days // WEEK_DAYS
    return [block for _, block in test.groupby(week)]


def walk_forward(
    data: pd.DataFrame,
    target: str,
    rung: str,
    params: dict[str, Any],
    seed: int,
    test_seasons: list[str],
    refit: Refit,
    calibrated: bool = True,
    oof_seasons: int = 3,
    isotonic: bool = True,
    availability: AvailabilityMode = "actual",
    drivers: bool = False,
) -> pd.DataFrame:
    # Train on every game before the block, predict the block. Calibration and sigma are
    # refitted once per test season from out-of-fold predictions on earlier seasons.
    # `availability` applies to the test block only: training always sees who played.
    # `drivers` adds each prediction's base, raw output and contribution per feature family
    rows = []
    for season in test_seasons:
        test = data[(data["season"] == season) & data[target].notna()]
        if test.empty:
            continue
        cal = Calibration()
        if calibrated:
            before = data[data["season"] < season]
            oof = oof_predictions(before, target, rung, params, seed, oof_seasons)
            cal = calibrate(target, rung, oof, isotonic)
        for block in _blocks(test, refit):
            start = block["game_date_et"].min()
            x_train, y_train = xy(data[data["game_date_et"] < start], target, rung)
            x_test, y_test = xy(block, target, rung, availability)
            model = make_rung(target, rung, params, seed).fit(x_train, y_train)
            raw = model.predict(x_test)
            out = finish(target, raw, block["season_type"], cal)
            frame = pd.DataFrame({
                "game_id": block["game_id"].to_numpy(), "season": season,
                "season_type": block["season_type"].to_numpy(),
                "game_date_et": block["game_date_et"].to_numpy(), "y": y_test,
                "pred": out["pred"].to_numpy(), "sigma": out["sigma"].to_numpy(dtype=float),
            })
            if drivers:
                d = explain(model, target, x_test)
                families = d.families().add_prefix("drv_").reset_index(drop=True)
                frame = pd.concat([frame.assign(base=d.base, raw=d.output), families], axis=1)
            rows.append(frame)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def regular_season(preds: pd.DataFrame) -> pd.DataFrame:
    # Headline metrics use the regular season (ADR-004)
    return preds[preds["season_type"] == "regular"]


def has_sigma(preds: pd.DataFrame) -> bool:
    return bool(np.isfinite(preds["sigma"].to_numpy(dtype=float)).all())
