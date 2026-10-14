import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from avaris.preseason.win_check import candidates, render_win_check, win_check_table

SIGMA = 15.0


def preseason_frame(n: int, seed: int) -> pd.DataFrame:
    # The margin model is calibrated; the classifier is twice as sure on the log-odds scale
    rng = np.random.default_rng(seed)
    mu = rng.normal(0, 4, n)
    p_true = norm.cdf(mu / SIGMA)
    logit = np.log(p_true / (1 - p_true))
    return pd.DataFrame({
        "game_id": [f"001{i:07d}" for i in range(n)][::-1],
        "season": rng.choice(["2015-16", "2016-17"], n),
        "home_win_y": (rng.random(n) < p_true).astype(float),
        "home_win_classifier": 1 / (1 + np.exp(-2.5 * logit)),
        "margin_pred": mu, "margin_sigma": SIGMA,
    })


def test_candidates_score_the_same_games_in_order() -> None:
    frame = preseason_frame(5, seed=0)
    out = candidates(frame)
    assert list(out) == ["classifier", "margin"]
    for c in out.values():
        assert c["game_id"].is_monotonic_increasing
        assert list(c.columns) == ["game_id", "y", "pred", "sigma"]
    first = frame.sort_values("game_id").iloc[0]
    assert out["margin"]["pred"].iloc[0] == pytest.approx(norm.cdf(first["margin_pred"] / SIGMA))
    assert out["classifier"]["pred"].iloc[0] == first["home_win_classifier"]


def test_the_calibrated_margin_beats_an_overconfident_classifier() -> None:
    table = win_check_table(preseason_frame(4000, seed=1), n_boot=200)
    margin = table[(table["model"] == "margin") & (table["metric"] == "log_loss")].iloc[0]
    assert margin["diff"] < 0 and margin["diff_hi"] < 0
    ece = table[table["metric"] == "ece"].set_index("model")["value"]
    assert ece["margin"] < ece["classifier"]


def test_report_lists_scores_seasons_and_reliability() -> None:
    md, charts = render_win_check(preseason_frame(400, seed=2), "Preseason home_win", n_boot=50)
    assert md.startswith("# Preseason home_win")
    for text in ("400 preseason games", "classifier", "margin", "2015-16", "2016-17",
                 "Reliability", "mean_p"):
        assert text in md
    assert list(charts) == ["reliability_preseason_home_win.svg"]
    assert "reliability_preseason_home_win.svg" in md
