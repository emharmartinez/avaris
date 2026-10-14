# ADR-023: a preseason p_home_win is P(margin > 0) under the margin model's N(mu, sigma), and
# its win drivers are the margin drivers; every other game keeps the classifier
import json
import shutil
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from avaris.features.build import FeatureSet, build_features
from avaris.models.distributions import prob_above
from avaris.models.registry import Registry
from avaris.pipeline.daily import Models, load_models, prediction_rows
from tests.fixtures.live import models_settings, train_before_d1

NOW = datetime(2021, 11, 26, 17, 0)


@pytest.fixture(scope="module")
def league(
    synthetic_db_template: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[FeatureSet, pd.DataFrame, Models]:
    root = tmp_path_factory.mktemp("preseason_win")
    db = root / "league.duckdb"
    shutil.copy(synthetic_db_template, db)
    train_before_d1(db, root / "artifacts")
    con = duckdb.connect(str(db), read_only=True)
    try:
        fs = build_features(con)
        games = con.execute("select game_id, tip_off_utc from games").df()
    finally:
        con.close()
    rows = fs.features.merge(games, on="game_id")
    rows = rows[(rows["season"] == "2021-22")
                & rows["season_type"].isin(["preseason", "regular"])].reset_index(drop=True)
    assert set(rows["season_type"]) == {"preseason", "regular"}
    models = load_models(Registry(models_settings(root / "artifacts").models_dir))
    return fs, rows, models


@pytest.fixture(scope="module")
def predicted(league: tuple[FeatureSet, pd.DataFrame, Models]) -> pd.DataFrame:
    fs, rows, models = league
    return prediction_rows(fs, rows, models, {}, NOW).assign(
        season_type=rows["season_type"].to_numpy())


def test_preseason_win_probability_comes_from_the_margin(
    league: tuple[FeatureSet, pd.DataFrame, Models], predicted: pd.DataFrame,
) -> None:
    _, rows, models = league
    preseason = (predicted["season_type"] == "preseason").to_numpy()
    expected = prob_above(predicted["margin_mu"].to_numpy(float),
                          predicted["margin_sigma"].to_numpy(float), 0.0)
    np.testing.assert_allclose(predicted.loc[preseason, "p_home_win"], expected[preseason])
    classifier = models["home_win"][0].predict(rows, "report")["pred"].to_numpy()
    np.testing.assert_array_equal(predicted.loc[~preseason, "p_home_win"],
                                  classifier[~preseason])
    assert not np.allclose(classifier[preseason], expected[preseason])


def test_preseason_win_drivers_are_the_margin_drivers(predicted: pd.DataFrame) -> None:
    for row in predicted.to_dict("records"):
        drivers = json.loads(row["drivers"])
        if row["season_type"] == "preseason":
            assert drivers["home_win"] == drivers["margin"]
            assert drivers["home_win"]["scale"] == "points"
        else:
            assert drivers["home_win"]["scale"] == "log_odds"
