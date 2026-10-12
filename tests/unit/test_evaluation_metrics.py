import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from avaris.backtest.bootstrap import bootstrap
from avaris.backtest.metrics import ece, pit, pit_counts, reliability

# Calibration


def test_reliability_bins_mean_probability_and_frequency() -> None:
    y = np.array([0, 1, 1, 1])
    p = np.array([0.05, 0.08, 0.72, 0.78])
    table = reliability(y, p, bins=10)
    assert list(table["bin"]) == [0, 7]
    assert list(table["n"]) == [2, 2]
    assert table["mean_p"].to_numpy() == pytest.approx([0.065, 0.75])
    assert table["freq"].to_numpy() == pytest.approx([0.5, 1.0])


def test_ece_is_the_weighted_gap_between_probability_and_frequency() -> None:
    y = np.array([0, 1, 1, 1])
    p = np.array([0.05, 0.08, 0.72, 0.78])
    assert ece(y, p, bins=10) == pytest.approx(0.5 * 0.435 + 0.5 * 0.25)
    # Perfectly calibrated within each bin
    assert ece(np.array([0, 1]), np.array([0.5, 0.5])) == pytest.approx(0.0)


def test_probability_one_falls_in_the_top_bin() -> None:
    assert list(reliability(np.array([1]), np.array([1.0]))["bin"]) == [9]


def test_pit_and_counts() -> None:
    y = np.array([0.0, 1.0, -1.0])
    values = pit(y, np.zeros(3), np.ones(3))
    assert values == pytest.approx([0.5, norm.cdf(1), norm.cdf(-1)])
    assert list(pit_counts(values, bins=10)) == [0, 1, 0, 0, 0, 1, 0, 0, 1, 0]
    assert pit_counts(np.array([1.0]), bins=10)[-1] == 1


# Bootstrap


def _preds(pred: list[float], y: list[float], sigma: float = np.nan) -> pd.DataFrame:
    return pd.DataFrame({
        "game_id": [f"g{i}" for i in range(len(y))], "y": y, "pred": pred, "sigma": sigma,
    })


def test_bootstrap_point_estimates_and_intervals() -> None:
    rng = np.random.default_rng(0)
    y = rng.normal(0, 10, 400)
    preds = {
        "elo": _preds(list(y + rng.normal(0, 8, 400)), list(y), 8.0),
        "model": _preds(list(y + rng.normal(0, 4, 400)), list(y), 4.0),
    }
    table = bootstrap("margin", preds, reference="elo", n_boot=200, seed=1)
    row = table[(table["model"] == "model") & (table["metric"] == "mae")].iloc[0]
    assert row["value"] == pytest.approx(np.mean(np.abs(preds["model"]["pred"] - y)))
    assert row["lo"] < row["value"] < row["hi"]
    assert row["diff"] == pytest.approx(
        row["value"] - table[(table["model"] == "elo") & (table["metric"] == "mae")]["value"].iloc[0]
    )
    assert row["diff_hi"] < 0  # clearly better than the reference
    assert set(table["metric"]) == {"mae", "rmse", "coverage_80"}
    ref = table[table["model"] == "elo"]
    assert ref["diff"].isna().all()


def test_bootstrap_draws_are_paired_across_models() -> None:
    # Two identical models: every replicate difference is exactly zero
    y = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
    p = [0.7, 0.4, 0.6, 0.55, 0.3, 0.8]
    table = bootstrap("home_win", {"elo": _preds(p, y), "twin": _preds(p, y)}, "elo", 50, 3)
    twin = table[table["model"] == "twin"]
    assert (twin["diff_lo"] == 0).all() and (twin["diff_hi"] == 0).all()
    assert set(twin["metric"]) == {"log_loss", "brier", "accuracy", "ece"}


def test_bootstrap_requires_aligned_games() -> None:
    a = _preds([0.5, 0.5], [1.0, 0.0])
    b = a.iloc[::-1].reset_index(drop=True)
    with pytest.raises(ValueError, match="same games"):
        bootstrap("home_win", {"elo": a, "other": b}, "elo", 10, 0)
