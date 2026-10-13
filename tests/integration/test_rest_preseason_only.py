# The preseason rest adjustment (ADR-022) must leave everything else as it was: model
# features, feature_hash and non-preseason predictions are byte-identical with and without
# ESPN snapshots, preseason box scores and rest_params, and a snapshot fetched after a
# game's decision_ts never changes its rest values
import math
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pytest

from avaris.config import Settings
from avaris.db import connect
from avaris.features.build import FeatureSet, build_features
from avaris.pipeline.daily import run_daily
from tests.fixtures.live import models_settings, train_before_d1
from tests.fixtures.synthetic import (
    ATL,
    BOS,
    REST_ABSENT,
    add_espn_snapshot,
    add_preseason_boxes,
)

GAME = "0012100001"  # 2021-22 preseason, ATL (home) v BOS; ATL's best player sits out
TIP = datetime(2021, 10, 6, 0, 0)
DECISION = TIP - timedelta(minutes=60)
STAR = REST_ABSENT[ATL]
D1_NOON = datetime(2021, 11, 26, 17, 0)  # the synthetic league's first unplayed day


def build(path: Path) -> FeatureSet:
    con = duckdb.connect(str(path))
    try:
        return build_features(con)
    finally:
        con.close()


def add_rest_data(path: Path, con: duckdb.DuckDBPyConnection | None = None) -> None:
    # Preseason box scores, two ESPN snapshots around GAME's decision_ts and fitted k
    own = con is None
    con = con or duckdb.connect(str(path))
    try:
        add_preseason_boxes(con)
        add_espn_snapshot(con, DECISION - timedelta(hours=3), [(ATL, STAR, "Out")])
        add_espn_snapshot(con, DECISION + timedelta(minutes=5),
                          [(ATL, STAR, "Out"), (BOS, 2000, "Out")])
        con.execute(
            "insert into rest_params values (now(), 0.5, 0.4, 0.05, true, true, true, '{}')")
    finally:
        if own:
            con.close()


def rest_row(fs: FeatureSet, game_id: str) -> dict[str, Any]:
    match = fs.rest[fs.rest["game_id"] == game_id]
    assert len(match) == 1, game_id
    return {str(k): v for k, v in match.iloc[0].to_dict().items()}


@pytest.fixture
def plain(synthetic_db: Path) -> FeatureSet:
    return build(synthetic_db)


@pytest.fixture
def with_rest(synthetic_db: Path, tmp_path: Path) -> FeatureSet:
    path = tmp_path / "rest.duckdb"
    path.write_bytes(synthetic_db.read_bytes())
    add_rest_data(path)
    return build(path)


def test_model_features_are_byte_identical(plain: FeatureSet, with_rest: FeatureSet) -> None:
    pd.testing.assert_frame_equal(plain.features, with_rest.features)
    pd.testing.assert_frame_equal(plain.team_ratings, with_rest.team_ratings)
    pd.testing.assert_frame_equal(plain.availability, with_rest.availability)
    assert not any("espn" in c for c in with_rest.features.columns)


def test_rest_rows_are_preseason_nba_games_only(with_rest: FeatureSet) -> None:
    features = with_rest.features
    preseason = set(features.loc[features["season_type"] == "preseason", "game_id"])
    assert set(with_rest.rest["game_id"]) == preseason


def test_rest_values_come_from_the_snapshot_before_decision_ts(with_rest: FeatureSet) -> None:
    r = rest_row(with_rest, GAME)
    assert r["snapshot_ts"] == DECISION - timedelta(hours=3)
    assert r["home_lost_espn"] > 0  # type: ignore[operator]
    assert r["away_lost_espn"] == 0  # the BOS entry was fetched after decision_ts
    players = r["home_players"]
    assert isinstance(players, list) and [p["player_id"] for p in players] == [STAR]
    assert players[0]["value"] == pytest.approx(r["home_lost_espn"])
    assert players[0]["matched"] is True


def test_lost_actual_is_who_sat_out_the_box_score(with_rest: FeatureSet) -> None:
    r = rest_row(with_rest, GAME)
    # The star is listed out and sat out, at the same value
    assert r["home_lost_actual"] == pytest.approx(r["home_lost_espn"])
    assert r["away_lost_actual"] == 0
    bkn = rest_row(with_rest, "0012100002")  # BKN v DEN
    # BKN's best player sits out; DEN is at full strength
    assert bkn["home_lost_actual"] > 0 and bkn["away_lost_actual"] == 0  # type: ignore[operator]


def test_no_snapshot_in_the_window_means_unknown(with_rest: FeatureSet) -> None:
    # A preseason game with no snapshot: lost_espn is unknown, not zero
    r = rest_row(with_rest, "0012000001")
    assert pd.isna(r["snapshot_ts"])
    assert math.isnan(r["home_lost_espn"]) and math.isnan(r["away_lost_espn"])  # type: ignore[arg-type]
    assert r["home_players"] == [] and r["away_players"] == []


def test_a_snapshot_older_than_the_window_is_not_used(
    synthetic_db: Path, tmp_path: Path,
) -> None:
    path = tmp_path / "old.duckdb"
    path.write_bytes(synthetic_db.read_bytes())
    con = duckdb.connect(str(path))
    add_espn_snapshot(con, TIP - timedelta(hours=36, minutes=1), [(ATL, STAR, "Out")])
    con.close()
    assert pd.isna(rest_row(build(path), GAME)["snapshot_ts"])


def test_leakage_snapshots_after_decision_ts_change_nothing(
    with_rest: FeatureSet, synthetic_db: Path, tmp_path: Path,
) -> None:
    path = tmp_path / "cut.duckdb"
    path.write_bytes(synthetic_db.read_bytes())
    add_rest_data(path)
    con = duckdb.connect(str(path))
    con.execute("delete from espn_injury_fetches where fetched_at > ?", [DECISION])
    con.execute("delete from espn_injury_snapshots where fetched_at > ?", [DECISION])
    con.close()
    cut = build(path)
    before, after = rest_row(with_rest, GAME), rest_row(cut, GAME)
    for key in ("snapshot_ts", "home_lost_espn", "away_lost_espn", "home_players",
                "away_players"):
        assert before[key] == after[key], key


def test_a_late_snapshot_is_detected(synthetic_db: Path, tmp_path: Path) -> None:
    # Guard for the leakage test: the late snapshot alone would change BOS's value
    path = tmp_path / "late.duckdb"
    path.write_bytes(synthetic_db.read_bytes())
    con = duckdb.connect(str(path))
    add_espn_snapshot(con, DECISION - timedelta(minutes=1), [(BOS, 2000, "Out")])
    con.close()
    assert rest_row(build(path), GAME)["away_lost_espn"] > 0  # type: ignore[operator]


@pytest.fixture(scope="module")
def trained(synthetic_db_template: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("rest_daily")
    shutil.copy(synthetic_db_template, root / "league.duckdb")
    train_before_d1(root / "league.duckdb", root / "artifacts")
    return root


def daily_predictions(root: Path, tmp_path: Path, name: str, rest_data: bool) -> pd.DataFrame:
    work = tmp_path / name
    shutil.copytree(root, work)
    con = connect(work / "league.duckdb")
    try:
        if rest_data:
            add_rest_data(work / "league.duckdb", con)
            add_espn_snapshot(con, D1_NOON - timedelta(hours=1), [(ATL, STAR, "Out")])
        settings = Settings(models=models_settings(work / "artifacts"))
        run_daily(con, settings, now=D1_NOON + timedelta(hours=7), refresh=None)
        return con.execute("select * from predictions order by game_id").df()
    finally:
        con.close()


def test_non_preseason_predictions_are_byte_identical(trained: Path, tmp_path: Path) -> None:
    plain = daily_predictions(trained, tmp_path, "plain", rest_data=False)
    rest = daily_predictions(trained, tmp_path, "rest", rest_data=True)
    assert len(plain) == 2 and set(plain["status"]) == {"final"}
    pd.testing.assert_frame_equal(plain, rest)
    assert plain["rest"].isna().all() and plain["raw_margin_mu"].isna().all()
