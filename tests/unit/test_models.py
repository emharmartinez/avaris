import math

import numpy as np
import pandas as pd
import pytest

from avaris.backtest.metrics import brier, coverage, log_loss, mae, rmse, score
from avaris.models.calibration import IsotonicCalibrator
from avaris.models.distributions import bucket, fit_sigma, interval, prob_above
from avaris.models.ladder import TARGETS, make_rung
from avaris.models.predictor import win_probability

# Metrics


def test_log_loss_and_brier() -> None:
    y = np.array([1, 0])
    p = np.array([0.8, 0.4])
    assert log_loss(y, p) == pytest.approx(-(math.log(0.8) + math.log(0.6)) / 2)
    assert brier(y, p) == pytest.approx((0.04 + 0.16) / 2)
    # Clipped, so certain mistakes stay finite
    assert math.isfinite(log_loss(np.array([1]), np.array([0.0])))


def test_mae_rmse_and_interval_coverage() -> None:
    y = np.array([0.0, 10.0])
    mu = np.array([2.0, 4.0])
    assert mae(y, mu) == pytest.approx(4)
    assert rmse(y, mu) == pytest.approx(math.sqrt((4 + 36) / 2))
    # 80% interval: mu +- 1.2816 sigma
    assert coverage(y, mu, np.array([2.0, 2.0])) == pytest.approx(0.5)


def test_score_by_target() -> None:
    assert set(score("home_win", np.array([1, 0]), np.array([0.6, 0.3]))) == {
        "log_loss", "brier", "accuracy", "n",
    }
    margin = score("margin", np.array([3.0]), np.array([1.0]), np.array([5.0]))
    assert set(margin) == {"mae", "rmse", "coverage_80", "n"}


# Distributions


def test_bucket_by_season_type() -> None:
    assert bucket("preseason") == "preseason"
    assert bucket("regular") == bucket("cup_final") == "regular"
    assert bucket("playoffs") == bucket("play_in") == "postseason"


def test_sigma_per_bucket_with_fallback_for_small_buckets() -> None:
    residuals = np.array([10.0, -10.0] * 20 + [20.0, -20.0] * 20 + [5.0])
    types = pd.Series(["regular"] * 40 + ["preseason"] * 40 + ["playoffs"])
    sigma = fit_sigma(residuals, types, min_rows=30)
    assert sigma["regular"] == pytest.approx(10)
    assert sigma["preseason"] == pytest.approx(20)
    assert sigma["postseason"] == sigma["all"]


def test_interval_and_probability_above() -> None:
    lo, hi = interval(np.array([0.0]), np.array([10.0]))
    assert (lo[0], hi[0]) == (pytest.approx(-12.816, abs=1e-3), pytest.approx(12.816, abs=1e-3))
    assert prob_above(np.array([5.0]), np.array([10.0]), 5.0)[0] == pytest.approx(0.5)


# Calibration


def test_preseason_win_probability_is_read_off_the_margin_normal() -> None:
    # ADR-023: preseason p_home_win = P(margin > 0) under N(mu, sigma); the classifier's
    # probability everywhere else
    types = pd.Series(["preseason", "regular", "preseason", "playoffs"])
    p = np.array([0.8, 0.7, 0.3, 0.6])
    mu = np.array([0.0, 5.0, -15.0, 5.0])
    sigma = np.array([15.0, 12.0, 15.0, 12.0])
    out = win_probability(types, p, mu, sigma)
    assert out[0] == pytest.approx(0.5)
    assert out[2] == pytest.approx(0.158655, abs=1e-6)  # one sigma below zero
    assert (out[1], out[3]) == (0.7, 0.6)


def test_isotonic_calibrator_is_monotone_and_bounded() -> None:
    rng = np.random.default_rng(0)
    p = rng.uniform(0, 1, 2000)
    y = (rng.uniform(0, 1, 2000) < p**2).astype(int)
    cal = IsotonicCalibrator().fit(p, y)
    out = cal.transform(np.array([0.0, 0.5, 1.0]))
    assert out[0] <= out[1] <= out[2]
    assert out[0] > 0 and out[2] < 1
    assert out[1] == pytest.approx(0.25, abs=0.07)


# Rungs


def frame(n: int = 400) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    rng = np.random.default_rng(1)
    x = pd.DataFrame({
        "elo_prob": rng.uniform(0.2, 0.8, n),
        "elo_margin": rng.normal(0, 5, n),
        "league_total": np.full(n, 220.0),
        "other": rng.normal(0, 1, n),
    })
    x.loc[::10, "other"] = np.nan
    margin = x["elo_margin"].to_numpy() * 1.5 + rng.normal(0, 10, n)
    return x, {
        "home_win": (margin > 0).astype(int),
        "margin": margin,
        "total": 220 + rng.normal(0, 15, n),
    }


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("rung", ["elo", "linear", "lgbm"])
def test_rungs_fit_and_predict(target: str, rung: str) -> None:
    x, ys = frame()
    params = {"n_estimators": 20} if rung == "lgbm" else {}
    model = make_rung(target, rung, params, seed=7).fit(x, ys[target])
    pred = model.predict(x)
    assert pred.shape == (len(x),) and np.isfinite(pred).all()
    if target == "home_win":
        assert ((pred > 0) & (pred < 1)).all()


def test_elo_rung_reads_elo_columns() -> None:
    x, _ = frame()
    np.testing.assert_allclose(make_rung("home_win", "elo", {}, 7).predict(x), x["elo_prob"])
    np.testing.assert_allclose(make_rung("margin", "elo", {}, 7).predict(x), x["elo_margin"])
    np.testing.assert_allclose(make_rung("total", "elo", {}, 7).predict(x), x["league_total"])
