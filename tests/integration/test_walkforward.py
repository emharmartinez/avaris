from pathlib import Path
from typing import Any, Self

import duckdb
import numpy as np
import pandas as pd
import pytest

from avaris.backtest import walkforward
from avaris.backtest.walkforward import walk_forward
from avaris.features.build import build_features
from avaris.models.dataset import with_targets
from avaris.models.ladder import TARGETS
from avaris.models.predictor import fit_predictor, oof_metric

LGBM = {"n_estimators": 20, "num_leaves": 4, "min_child_samples": 5}


@pytest.fixture(scope="module")
def data(synthetic_db_template: Path) -> pd.DataFrame:
    con = duckdb.connect(str(synthetic_db_template), read_only=True)
    try:
        return with_targets(build_features(con).features, con)
    finally:
        con.close()


def test_targets_only_for_final_games(data: pd.DataFrame) -> None:
    unplayed = data[data["game_id"] == "0022100047"].iloc[0]
    assert np.isnan(unplayed["margin"]) and np.isnan(unplayed["home_win"])
    played = data[data["margin"].notna()]
    assert ((played["margin"] > 0) == (played["home_win"] == 1)).all()


@pytest.mark.parametrize("refit", ["season", "weekly"])
def test_each_block_trains_only_on_earlier_games(
    data: pd.DataFrame, refit: walkforward.Refit, monkeypatch: pytest.MonkeyPatch
) -> None:
    fits: list[int] = []

    class Recording:
        def fit(self, x: pd.DataFrame, y: np.ndarray) -> Self:
            fits.append(len(x))
            return self

        def predict(self, x: pd.DataFrame) -> np.ndarray:
            return np.full(len(x), 0.0)

    def fake_make_rung(*_args: Any) -> Recording:
        return Recording()

    monkeypatch.setattr(walkforward, "make_rung", fake_make_rung)
    preds = walk_forward(data, "margin", "linear", {}, 7, ["2021-22"], refit, calibrated=False)
    test = data[(data["season"] == "2021-22") & data["margin"].notna()]
    assert sorted(preds["game_id"]) == sorted(test["game_id"])
    starts = [b["game_date_et"].min() for b in walkforward._blocks(test, refit)]
    labelled = data[data["margin"].notna()]
    assert fits == [int((labelled["game_date_et"] < s).sum()) for s in starts]
    assert len(fits) == (1 if refit == "season" else len(starts)) and (len(fits) > 1) == (
        refit == "weekly"
    )


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("rung", ["elo", "linear", "lgbm", "naive_home", "naive_net"])
def test_calibrated_walk_forward_outputs(data: pd.DataFrame, target: str, rung: str) -> None:
    params = LGBM if rung == "lgbm" else {}
    preds = walk_forward(data, target, rung, params, 7, ["2021-22"], "weekly", oof_seasons=1)
    assert np.isfinite(preds["pred"]).all()
    if target == "home_win":
        assert preds["pred"].between(0, 1).all()
        assert preds["sigma"].isna().all()
    else:
        assert (preds["sigma"] > 0).all()


def test_fit_predictor_predicts_unplayed_games_with_report_availability(
    data: pd.DataFrame,
) -> None:
    train = data[data["season"] < "2021-22"]
    predictor = fit_predictor(train, "margin", "lgbm", LGBM, seed=7, oof_seasons=1)
    assert np.isfinite(oof_metric(predictor))
    future = data[data["margin"].isna()]
    out = predictor.predict(future, availability="report")
    assert len(out) == len(future)
    assert np.isfinite(out["pred"]).all() and (out["sigma"] > 0).all()


def test_isotonic_calibration_can_be_turned_off(data: pd.DataFrame) -> None:
    raw = walk_forward(data, "home_win", "linear", {}, 7, ["2021-22"], "season", calibrated=False)
    off = walk_forward(data, "home_win", "linear", {}, 7, ["2021-22"], "season", oof_seasons=1,
                       isotonic=False)
    on = walk_forward(data, "home_win", "linear", {}, 7, ["2021-22"], "season", oof_seasons=1)
    np.testing.assert_allclose(off["pred"], raw["pred"])
    assert not np.allclose(on["pred"], raw["pred"])


def test_calibration_fits_only_on_seasons_before_the_test_season(
    data: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    from avaris.models import predictor

    fits: list[int] = []
    real = predictor.make_rung

    def recording(*args: Any) -> Any:
        model = real(*args)
        fit = model.fit

        def record(x: pd.DataFrame, y: np.ndarray) -> Any:
            fits.append(len(x))
            return fit(x, y)

        model.fit = record  # type: ignore[method-assign]
        return model

    monkeypatch.setattr(predictor, "make_rung", recording)
    walk_forward(data, "margin", "linear", {}, 7, ["2021-22"], "season", oof_seasons=1)
    labelled = data[data["margin"].notna()]
    # One OOF fit: trained on 2019-20, predicting 2020-21; nothing from 2021-22
    assert fits == [int((labelled["season"] < "2020-21").sum())]


def test_calibration_needs_two_labelled_seasons(data: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="at least 2 labelled seasons"):
        walk_forward(data, "margin", "elo", {}, 7, ["2020-21"], "season")


def test_report_availability_applies_to_the_test_block_only(
    data: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    fitted: list[pd.DataFrame] = []
    predicted: list[pd.DataFrame] = []

    class Recording:
        def fit(self, x: pd.DataFrame, y: np.ndarray) -> Self:
            fitted.append(x)
            return self

        def predict(self, x: pd.DataFrame) -> np.ndarray:
            predicted.append(x)
            return np.full(len(x), 0.0)

    def fake_make_rung(*_args: Any) -> Recording:
        return Recording()

    monkeypatch.setattr(walkforward, "make_rung", fake_make_rung)
    walk_forward(data, "margin", "linear", {}, 7, ["2021-22"], "season", calibrated=False,
                 availability="report")
    rows = data
    test_x, train_x = predicted[0], fitted[0]
    np.testing.assert_allclose(test_x["home_lost"], rows.loc[test_x.index, "home_lost_report"])
    np.testing.assert_allclose(
        train_x["home_lost"], rows.loc[train_x.index, "home_lost_actual"], equal_nan=True
    )
    assert not np.allclose(
        rows.loc[test_x.index, "home_lost_report"], rows.loc[test_x.index, "home_lost_actual"],
        equal_nan=True,
    )


def test_baselines_read_season_to_date_inputs(data: pd.DataFrame) -> None:
    preds = walk_forward(data, "margin", "naive_net", {}, 7, ["2021-22"], "season",
                         calibrated=False)
    home = walk_forward(data, "margin", "naive_home", {}, 7, ["2021-22"], "season",
                        calibrated=False)
    assert preds["pred"].nunique() > 1
    assert home["pred"].nunique() == 1


@pytest.mark.parametrize("target", TARGETS)
def test_walk_forward_drivers_sum_to_the_raw_output(data: pd.DataFrame, target: str) -> None:
    from avaris.analytics.drivers import FAMILY_FEATURES

    preds = walk_forward(data, target, "lgbm", LGBM, 7, ["2021-22"], "weekly", oof_seasons=1,
                         isotonic=False, drivers=True)
    families = [f"drv_{f}" for f in FAMILY_FEATURES]
    assert set(families) <= set(preds.columns)
    gap = preds["base"] + preds[families].sum(axis=1) - preds["raw"]
    assert gap.abs().max() < 1e-6
    without = walk_forward(data, target, "lgbm", LGBM, 7, ["2021-22"], "weekly", oof_seasons=1,
                           isotonic=False)
    assert "base" not in without.columns
    np.testing.assert_allclose(preds["pred"], without["pred"])
    # raw is the model's own prediction on the link scale, not the drivers' sum
    from scipy.special import logit

    expected = logit(preds["pred"]) if target == "home_win" else preds["pred"]
    np.testing.assert_allclose(preds["raw"], expected, rtol=1e-6, atol=1e-6)
