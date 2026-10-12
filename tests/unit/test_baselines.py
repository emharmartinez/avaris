import numpy as np
import pandas as pd
import pytest

from avaris.models.baselines import BASELINES, NaiveHome, baseline_frame
from avaris.models.ladder import make_rung


def _features(n: int = 4) -> pd.DataFrame:
    return pd.DataFrame({
        "home_ortg_std": [115.0, np.nan, 110.0, 108.0][:n],
        "home_drtg_std": [105.0, np.nan, 110.0, 112.0][:n],
        "home_pace_std": [100.0, np.nan, 98.0, 99.0][:n],
        "away_ortg_std": [110.0, 112.0, 110.0, np.nan][:n],
        "away_drtg_std": [110.0, 108.0, 110.0, np.nan][:n],
        "away_pace_std": [96.0, 100.0, 98.0, np.nan][:n],
        "league_total": [220.0, 221.0, 222.0, 223.0][:n],
    })


def test_baseline_frame_net_difference_and_expected_total() -> None:
    x = baseline_frame(_features())
    # (115 - 105) - (110 - 110) = 10; (100 + 96) / 2 * (115 + 110 + 110 + 105) / 200 = 215.6
    assert x.loc[0, "net_std_diff"] == pytest.approx(10.0)
    assert x.loc[0, "exp_total_std"] == pytest.approx(98 * 440 / 200)
    # A team with no games this season: no difference, league total
    assert x.loc[1, "net_std_diff"] == 0.0 and x.loc[3, "net_std_diff"] == 0.0
    assert x.loc[1, "exp_total_std"] == 221.0 and x.loc[3, "exp_total_std"] == 223.0


def test_naive_home_predicts_the_recent_mean() -> None:
    model = NaiveHome(window=3).fit(pd.DataFrame(index=range(5)), np.array([0, 0, 1, 1, 0.0]))
    assert model.predict(pd.DataFrame(index=range(2))) == pytest.approx([2 / 3, 2 / 3])


@pytest.mark.parametrize("target", ["home_win", "margin", "total"])
def test_naive_net_follows_the_season_to_date_rating(target: str) -> None:
    rng = np.random.default_rng(0)
    n = 400
    net = rng.normal(0, 5, n)
    feats = pd.DataFrame({
        "home_ortg_std": 110 + net, "home_drtg_std": 110.0, "home_pace_std": 100.0,
        "away_ortg_std": 110.0, "away_drtg_std": 110.0, "away_pace_std": 100.0,
        "league_total": 220.0,
    })
    x = baseline_frame(feats)
    y = {
        "home_win": (net + rng.normal(0, 5, n) > 0).astype(float),
        "margin": net + rng.normal(0, 1, n),
        "total": 2 * (110 + net / 2) + rng.normal(0, 1, n),
    }[target]
    model = make_rung(target, "naive_net", {}, 7).fit(x, y)
    pred = model.predict(x)
    assert pd.Series(pred).corr(pd.Series(net), method="spearman") > 0.99
    if target == "home_win":
        assert ((pred > 0) & (pred < 1)).all()


def test_make_rung_builds_every_baseline() -> None:
    assert BASELINES == ("naive_home", "naive_net")
    for name in BASELINES:
        assert hasattr(make_rung("margin", name, {}, 7), "predict")
