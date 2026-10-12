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
@pytest.mark.parametrize("rung", ["elo", "linear", "lgbm"])
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
