import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pytest

from avaris.config import ModelsSettings, Settings
from avaris.db import connect
from avaris.features.build import build_features
from avaris.models.dataset import with_targets
from avaris.models.distributions import prob_above
from avaris.preseason.fit import (
    fit_coefficients,
    fit_rest,
    k_ols,
    preseason_predictions,
)
from avaris.preseason.rest import load_params
from tests.fixtures.live import models_settings
from tests.fixtures.synthetic import add_preseason_boxes

FIT, GATE = ["2015-16", "2016-17"], ["2020-21", "2021-22"]
MARGIN_SD = 3.0


def planted(n: int, seasons: list[str], k: dict[str, float], seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    home, away = rng.uniform(0, 30, n), rng.uniform(0, 30, n)
    diff = home - away
    margin_pred, total_pred = rng.normal(0, 6, n), rng.normal(220, 8, n)
    margin_y = margin_pred - k["margin"] * diff + rng.normal(0, MARGIN_SD, n)
    return pd.DataFrame({
        "game_id": [f"g{seed}_{i}" for i in range(n)],
        "season": rng.choice(seasons, n), "home_lost": home, "away_lost": away,
        "margin_pred": margin_pred, "margin_y": margin_y, "margin_sigma": MARGIN_SD,
        "total_pred": total_pred,
        "total_y": total_pred - k["total"] * (home + away) + rng.normal(0, 5, n),
        # The win is read off the margin (ADR-023)
        "home_win_pred": prob_above(margin_pred, np.full(n, MARGIN_SD), 0.0),
        "home_win_y": (margin_y > 0).astype(float),
    })


def test_k_ols_recovers_a_planted_k() -> None:
    x = np.linspace(-10, 10, 201)
    assert k_ols(-0.7 * x, x) == pytest.approx(0.7)
    assert k_ols(np.zeros(3), np.zeros(3)) == 0.0


def test_fit_recovers_planted_k_and_the_win_follows_the_margin() -> None:
    k = {"margin": 0.6, "total": 0.3}
    frame = pd.concat([planted(3000, FIT, k, seed=2), planted(3000, GATE, k, seed=3)])
    fit = fit_coefficients(frame, FIT, GATE)
    assert fit.params.k_margin == pytest.approx(0.6, abs=0.03)
    assert fit.params.k_total == pytest.approx(0.3, abs=0.03)
    assert fit.params.use_margin and fit.params.use_total
    # k_win is retired (stored as 0); use_win records that the win moves with the margin
    assert fit.params.k_win == 0.0 and fit.params.use_win
    assert fit.report["win_follows_margin"] is True
    assert set(fit.report["k"]) == {"margin", "total"}
    gate = fit.report["gate"]
    assert gate["margin"]["adjusted"] < gate["margin"]["raw"]
    assert gate["home_win"]["adjusted"] < gate["home_win"]["raw"]
    assert gate["home_win"]["enabled"] is True
    assert fit.report["n_fit"] == 3000 and fit.report["n_gate"] == 3000


def test_a_k_that_does_not_beat_raw_in_the_gate_window_is_disabled() -> None:
    fit_rows = planted(3000, FIT, {"margin": 0.6, "total": 0.3}, seed=4)
    gate_rows = planted(3000, GATE, {"margin": 0.0, "total": 0.0}, seed=5)
    fit = fit_coefficients(pd.concat([fit_rows, gate_rows]), FIT, GATE)
    assert fit.params.k_margin > 0.5  # fitted, then switched off
    assert not (fit.params.use_margin or fit.params.use_total or fit.params.use_win)
    assert fit.report["gate"]["home_win"]["enabled"] is False


def test_fit_needs_rows_in_both_windows() -> None:
    frame = planted(100, FIT, {"margin": 0, "total": 0}, seed=6)
    with pytest.raises(ValueError, match="gate window"):
        fit_coefficients(frame, FIT, GATE)


@pytest.fixture
def league(synthetic_db: Path) -> Path:
    con = duckdb.connect(str(synthetic_db))
    add_preseason_boxes(con)
    con.close()
    return synthetic_db


def test_preseason_predictions_walk_forward_only_preseason_games(
    league: Path, tmp_path: Path
) -> None:
    con = duckdb.connect(str(league), read_only=True)
    data = with_targets(build_features(con).features, con)
    con.close()
    preds = preseason_predictions(data, models_settings(tmp_path), ["2021-22"])
    preseason = data[(data["season"] == "2021-22") & (data["season_type"] == "preseason")
                     & data["margin"].notna()]
    assert set(preds["game_id"]) == set(preseason["game_id"]) and len(preds) == 4
    for target in ("margin", "total", "home_win"):
        assert np.isfinite(preds[f"{target}_pred"]).all()
        assert (preds[f"{target}_y"].to_numpy() == preseason.set_index("game_id").loc[
            preds["game_id"], target].to_numpy()).all()
    # ADR-023: the win probability production shows is read off the margin
    assert (preds["margin_sigma"] > 0).all()
    np.testing.assert_allclose(preds["home_win_pred"], prob_above(
        preds["margin_pred"].to_numpy(), preds["margin_sigma"].to_numpy(), 0.0))
    assert np.isfinite(preds["home_win_classifier"]).all()


def test_fit_rest_reads_the_windows_only_and_stores_the_fit(
    league: Path, tmp_path: Path
) -> None:
    models = models_settings(tmp_path).model_copy(update={
        "tune_first_season": "2019-20", "tune_last_season": "2020-21",
        "eval_first_season": "2021-22", "eval_last_season": "2021-22",
        "holdout_season": "2022-23",
    })
    seen: dict[str, Any] = {}

    def fake(data: pd.DataFrame, cfg: ModelsSettings, seasons: list[str]) -> pd.DataFrame:
        seen["data_seasons"] = set(data["season"])
        seen["seasons"] = seasons
        rows = data[data["season_type"] == "preseason"].dropna(subset=["margin"])
        out = pd.DataFrame({"game_id": rows["game_id"], "season": rows["season"]})
        for target, bias in (("margin", 1.0), ("total", -2.0), ("home_win", 0.0)):
            out[f"{target}_y"] = rows[target].to_numpy()
            out[f"{target}_pred"] = (rows[target].to_numpy() + bias if target != "home_win"
                                     else np.full(len(rows), 0.5))
        out["margin_sigma"] = 12.0
        return out.reset_index(drop=True)

    con = connect(league)
    fit = fit_rest(con, Settings(models=models), predict=fake)
    assert seen["seasons"] == ["2019-20", "2020-21", "2021-22"]
    assert seen["data_seasons"] <= {"2019-20", "2020-21", "2021-22"}
    assert fit.report["n_fit"] + fit.report["n_gate"] > 0
    stored = load_params(con)
    assert stored.k_margin == pytest.approx(fit.params.k_margin)
    assert stored.fitted_at is not None
    report = con.execute("select report from rest_params").fetchone()
    assert report is not None and json.loads(report[0])["n_gate"] == fit.report["n_gate"]
    assert not math.isnan(fit.params.k_total)
    con.close()


def test_fit_rest_refuses_a_window_reaching_the_holdout(league: Path, tmp_path: Path) -> None:
    models = models_settings(tmp_path).model_copy(update={"eval_last_season": "2025-26"})
    con = connect(league)
    with pytest.raises(ValueError, match="holdout"):
        fit_rest(con, Settings(models=models))
    con.close()
