from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest
from scipy.special import expit

from avaris.analytics.drivers import FAMILIES, explain, top_drivers
from avaris.analytics.injury_impact import injury_impact, player_names
from avaris.features.build import MODEL_FEATURES, FeatureSet, build_features, model_frame
from avaris.models.dataset import with_targets, xy
from avaris.models.ladder import make_rung

LGBM = {"n_estimators": 30, "num_leaves": 4, "min_child_samples": 5}


@pytest.fixture(scope="module")
def built(synthetic_db_template: Path) -> tuple[FeatureSet, pd.DataFrame]:
    con = duckdb.connect(str(synthetic_db_template), read_only=True)
    try:
        fs = build_features(con)
        return fs, with_targets(fs.features, con)
    finally:
        con.close()


def test_every_model_feature_has_a_family() -> None:
    assert set(FAMILIES) == set(MODEL_FEATURES)
    assert set(FAMILIES.values()) == {
        "elo", "form", "rest_travel", "availability", "home_court", "game_type", "league",
    }


@pytest.mark.parametrize("target", ["home_win", "margin", "total"])
@pytest.mark.parametrize("rung", ["elo", "linear", "lgbm"])
def test_contributions_plus_base_sum_to_the_model_output(
    built: tuple[FeatureSet, pd.DataFrame], target: str, rung: str
) -> None:
    data = built[1]
    train = data[data["season"] < "2021-22"]
    test = data[data["season"] == "2021-22"]
    x, y = xy(train, target, rung)
    model = make_rung(target, rung, LGBM if rung == "lgbm" else {}, 7).fit(x, y)
    x_test = model_frame(test, "report")
    d = explain(model, target, x_test)
    np.testing.assert_allclose(d.base + d.contributions.sum(axis=1), d.output, atol=1e-6)
    np.testing.assert_allclose(d.families().sum(axis=1), d.contributions.sum(axis=1), atol=1e-9)
    # The output is the model's prediction on the link scale: log-odds for home_win
    pred = model.predict(x_test)
    np.testing.assert_allclose(expit(d.output) if target == "home_win" else d.output, pred,
                               rtol=1e-6, atol=1e-6)
    assert list(d.contributions.columns) == MODEL_FEATURES


def test_linear_missing_indicators_fold_into_their_feature(
    built: tuple[FeatureSet, pd.DataFrame],
) -> None:
    # Availability is missing in preseason, so the imputer adds indicator columns for it
    data = built[1]
    x, y = xy(data, "margin", "linear")
    model = make_rung("margin", "linear", {}, 7).fit(x, y)
    pre = data[data["season_type"] == "preseason"]
    d = explain(model, "margin", model_frame(pre, "actual"))
    assert (d.contributions["home_lost"] != 0).any()
    np.testing.assert_allclose(d.base + d.contributions.sum(axis=1), d.output, atol=1e-6)


def test_top_drivers_rank_families_by_size() -> None:
    row = pd.Series({"elo": 0.4, "form": -0.9, "league": 0.0, "availability": 0.2})
    top = top_drivers(row, k=2)
    assert top == [{"family": "form", "value": -0.9}, {"family": "elo", "value": 0.4}]


@pytest.mark.parametrize("mode", ["actual", "report"])
def test_injury_impact_matches_the_availability_feature(
    built: tuple[FeatureSet, pd.DataFrame], mode: str
) -> None:
    fs = built[0]
    impact = injury_impact(fs.availability, mode)  # type: ignore[arg-type]
    f = fs.features.set_index("game_id")
    for side in ("home", "away"):
        merged = impact.merge(
            f[[f"{side}_team_id", f"{side}_full_strength", f"{side}_lost_{mode}"]],
            left_on=["game_id", "team_id"], right_on=["game_id", f"{side}_team_id"],
        )
        assert len(merged) > 0
        np.testing.assert_allclose(merged["full_strength"], merged[f"{side}_full_strength"])
        np.testing.assert_allclose(merged["lost"], merged[f"{side}_lost_{mode}"], equal_nan=True)
    played = impact[impact["lost"].notna()]
    for players, lost in zip(played["players"], played["lost"], strict=True):
        assert sum(p["lost"] for p in players) == pytest.approx(lost)
        losses = [p["lost"] for p in players]
        assert losses == sorted(losses, reverse=True) and all(v != 0 for v in losses)


def test_injury_impact_lists_report_status_and_names(
    built: tuple[FeatureSet, pd.DataFrame],
) -> None:
    fs = built[0]
    names = {int(p): f"Player {p}" for p in fs.availability["player_id"].unique()}
    impact = injury_impact(fs.availability, "report", names)
    listed = [p for players in impact["players"] for p in players]
    assert listed and all(p["status"] in ("out", "doubtful", "questionable") for p in listed)
    assert all(p["name"] == f"Player {p['player_id']}" for p in listed)
    share = impact["lost"] / impact["full_strength"]
    np.testing.assert_allclose(impact["lost_share"], share)


def test_player_names_come_from_the_game_logs(synthetic_db: Path) -> None:
    con = duckdb.connect(str(synthetic_db))
    pid, name = con.execute(
        "select player_id, player_name from player_games where player_name is not null limit 1"
    ).fetchone() or (0, "")
    con.execute("update player_games set player_name = 'Old Name' where player_id = ? and "
                "game_date_et = (select min(game_date_et) from player_games where player_id = ?)",
                [pid, pid])
    names = player_names(con)
    con.close()
    assert names[int(pid)] == name
