from pathlib import Path
from xml.etree import ElementTree

import duckdb
import numpy as np
import pandas as pd
import pytest

from avaris.backtest.evaluate import (
    MODELS,
    availability_by_season,
    driver_check,
    evaluate,
    not_beating_elo,
    render_report,
    score_tables,
)
from avaris.config import ModelsSettings, TargetModelSettings
from avaris.features.build import build_features
from avaris.models.dataset import with_targets

LGBM = {"n_estimators": 20, "num_leaves": 4, "min_child_samples": 5}
SETTINGS = ModelsSettings(
    oof_seasons=1,
    home_win=TargetModelSettings(rung="linear", calibration="none"),
    margin=TargetModelSettings(rung="lgbm", lgbm=LGBM),
    total=TargetModelSettings(rung="linear"),
)


@pytest.fixture(scope="module")
def data(synthetic_db_template: Path) -> pd.DataFrame:
    con = duckdb.connect(str(synthetic_db_template), read_only=True)
    try:
        return with_targets(build_features(con).features, con)
    finally:
        con.close()


@pytest.fixture(scope="module")
def preds(data: pd.DataFrame) -> pd.DataFrame:
    return evaluate(data, SETTINGS, ["2021-22"], "report")


def test_every_model_scores_the_same_games(preds: pd.DataFrame) -> None:
    assert set(preds["model"]) == set(MODELS)
    for _, part in preds.groupby("target"):
        games = [tuple(g["game_id"]) for _, g in part.groupby("model")]
        assert all(g == games[0] for g in games)
    assert set(preds.loc[preds["model"] == "model", "rung"]) == {"linear", "lgbm"}
    assert (preds["availability"] == "report").all()


def test_drivers_sum_to_the_output_for_every_model_prediction(preds: pd.DataFrame) -> None:
    check = driver_check(preds)
    assert set(check["target"]) == {"home_win", "margin", "total"}
    assert (check["max_gap"] < 1e-6).all()
    assert (check["n"] > 0).all()


def test_score_tables_have_bootstrap_intervals_per_scope(preds: pd.DataFrame) -> None:
    table = score_tables(preds, n_boot=50, seed=1)
    regular = table[(table["scope"] == "regular") & (table["target"] == "home_win")]
    assert set(regular["model"]) == set(MODELS)
    # ECE is biased upward under resampling, so only mean-type metrics must cover the point
    means = regular[regular["metric"] != "ece"]
    assert means["lo"].le(means["value"]).all() and means["hi"].ge(means["value"]).all()
    assert {"regular", "preseason"} <= set(table["scope"])
    assert table.loc[table["model"] == "elo", "diff"].isna().all()


def test_play_in_and_playoffs_are_scored_apart_and_together() -> None:
    types = ["regular"] * 4 + ["play_in"] * 2 + ["playoffs"] * 3 + ["cup_final"]
    base = pd.DataFrame({
        "game_id": [f"g{i}" for i in range(10)], "season_type": types, "target": "margin",
        "y": np.arange(10.0), "sigma": 5.0,
    })
    preds = pd.concat([base.assign(model=m, pred=base["y"] + k) for k, m in enumerate(MODELS)])
    table = score_tables(preds, n_boot=10, seed=0)
    n = table.groupby("scope")["n"].first().to_dict()
    assert n == {"regular": 4, "play_in": 2, "playoffs": 3, "postseason": 5}


def test_not_beating_elo_lists_worse_and_unproven_metrics() -> None:
    table = pd.DataFrame([
        {"target": "margin", "scope": "regular", "model": "model", "metric": "mae",
         "value": 9.8, "diff": -0.1, "diff_lo": -0.2, "diff_hi": -0.01},
        {"target": "margin", "scope": "playoffs", "model": "model", "metric": "mae",
         "value": 11.0, "diff": 0.2, "diff_lo": -0.1, "diff_hi": 0.5},
        {"target": "home_win", "scope": "regular", "model": "model", "metric": "accuracy",
         "value": 0.66, "diff": 0.01, "diff_lo": -0.01, "diff_hi": 0.03},
        {"target": "home_win", "scope": "regular", "model": "naive_net", "metric": "brier",
         "value": 0.3, "diff": 0.1, "diff_lo": 0.05, "diff_hi": 0.15},
    ])
    out = not_beating_elo(table)
    assert list(out["verdict"]) == ["worse", "not significantly better"]
    assert list(out["scope"]) == ["playoffs", "regular"]


def test_availability_by_season_measures_the_era_shift(data: pd.DataFrame) -> None:
    out = availability_by_season(data)
    assert {"season", "lost_actual", "lost_report", "team_games"} <= set(out.columns)
    no_reports = out[out["season"] == "2020-21"].iloc[0]
    assert no_reports["lost_report"] == 0
    assert out["team_games"].gt(0).all()


def test_render_report_has_every_section_and_valid_charts(preds: pd.DataFrame) -> None:
    md, charts = render_report(
        {"report": preds}, title="Evaluation", data=None, n_boot=20, seed=1
    )
    for heading in ("## home_win", "## margin", "## total", "Where the model does not beat Elo",
                    "Calibration", "Drivers"):
        assert heading in md
    assert charts and all(name.endswith(".svg") for name in charts)
    for name, svg in charts.items():
        ElementTree.fromstring(svg)
        assert f"]({name})" in md
    assert np.isfinite(preds["pred"]).all()
