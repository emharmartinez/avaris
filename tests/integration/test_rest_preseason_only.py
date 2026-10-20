# The preseason rest adjustment (ADR-022) must leave everything else as it was: model
# features, feature_hash and non-preseason predictions are byte-identical with and without
# ESPN snapshots, preseason box scores and rest_params, and a snapshot fetched after a
# game's decision_ts never changes its rest values. Season openers read the list for
# display only (ADR-025)
import json
import math
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pytest

from avaris.config import Settings
from avaris.db import connect, upsert
from avaris.features.build import FeatureSet, build_features
from avaris.models.registry import Registry
from avaris.pipeline.daily import load_models, prediction_rows, run_daily
from avaris.preseason.rest import FALLBACK, RestParams
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
OPENER = "0022100001"  # 2021-22's first regular-season game: nobody has played yet
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


def one_row(frame: pd.DataFrame, game_id: str) -> dict[str, Any]:
    match = frame[frame["game_id"] == game_id]
    assert len(match) == 1, game_id
    return {str(k): v for k, v in match.iloc[0].to_dict().items()}


def rest_row(fs: FeatureSet, game_id: str) -> dict[str, Any]:
    return one_row(fs.rest, game_id)


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


def test_rest_rows_are_preseason_games_and_season_openers(with_rest: FeatureSet) -> None:
    # Preseason, plus any other game before a team's first of the season, where the
    # report cannot be valued and ESPN's list stands in for display (ADR-025)
    f = with_rest.features
    preseason = f["season_type"] == "preseason"
    opener = ~preseason & ((f["home_gp"] == 0) | (f["away_gp"] == 0))
    assert opener.any()
    assert set(with_rest.rest["game_id"]) == set(f.loc[preseason | opener, "game_id"])


def test_a_one_sided_opener_gets_a_rest_row(synthetic_db: Path) -> None:
    # Without BKN v DEN on opening night, BKN's first game is ATL's second: only BKN's side
    # is unknown, and the game still reads ESPN's list
    con = duckdb.connect(str(synthetic_db))
    con.execute("delete from games where game_id = '0022100002'")
    con.close()
    fs = build(synthetic_db)
    game = one_row(fs.features, "0022100003")  # BKN (home) v ATL
    assert (game["home_gp"], game["away_gp"]) == (0, 1)
    assert math.isnan(game["home_lost_report"]) and not math.isnan(game["away_lost_report"])
    assert rest_row(fs, "0022100003")["game_id"] == "0022100003"


def test_a_season_opener_reads_the_list_before_decision_ts(
    plain: FeatureSet, synthetic_db: Path, tmp_path: Path,
) -> None:
    game = one_row(plain.features, OPENER)
    assert game["season_type"] == "regular" and game["home_gp"] == game["away_gp"] == 0
    assert ATL in (game["home_team_id"], game["away_team_id"])
    decision = pd.Timestamp(game["decision_ts"]).to_pydatetime()
    path = tmp_path / "opener.duckdb"
    path.write_bytes(synthetic_db.read_bytes())
    con = duckdb.connect(str(path))
    add_espn_snapshot(con, decision - timedelta(hours=1), [(ATL, STAR, "Out")])
    add_espn_snapshot(con, decision + timedelta(minutes=5), [(ATL, STAR, "Out"),
                                                             (BOS, 2000, "Out")])
    con.close()
    fs = build(path)
    pd.testing.assert_frame_equal(plain.features, fs.features)
    r = rest_row(fs, OPENER)
    side, other = ("home", "away") if game["home_team_id"] == ATL else ("away", "home")
    assert r["snapshot_ts"] == decision - timedelta(hours=1)
    assert r[f"{side}_lost_espn"] > 0 and r[f"{other}_lost_espn"] == 0  # type: ignore[operator]
    assert math.isnan(r[f"{side}_lost_actual"])  # no preseason box: never in the rest fit


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


def with_fetches(synthetic_db: Path, tmp_path: Path, fill: Any) -> FeatureSet:
    path = tmp_path / "fetches.duckdb"
    path.write_bytes(synthetic_db.read_bytes())
    con = duckdb.connect(str(path))
    fill(con)
    con.close()
    return build(path)


def test_a_deduped_fetch_uses_the_older_snapshot_it_points_at(
    synthetic_db: Path, tmp_path: Path,
) -> None:
    # The list was first seen 5 days before tip-off (outside the window) and confirmed
    # unchanged by a fetch 2 h before decision_ts
    first_seen = TIP - timedelta(days=5)

    def fill(con: duckdb.DuckDBPyConnection) -> None:
        add_espn_snapshot(con, first_seen, [(ATL, STAR, "Out")])
        upsert(con, "espn_injury_fetches", pd.DataFrame([
            {"fetched_at": DECISION - timedelta(hours=2), "snapshot_ts": first_seen}]))

    r = rest_row(with_fetches(synthetic_db, tmp_path, fill), GAME)
    assert r["snapshot_ts"] == first_seen
    assert r["home_lost_espn"] > 0


def test_a_fetch_at_decision_ts_counts(synthetic_db: Path, tmp_path: Path) -> None:
    r = rest_row(with_fetches(synthetic_db, tmp_path, lambda con: add_espn_snapshot(
        con, DECISION, [(ATL, STAR, "Out")])), GAME)
    assert r["snapshot_ts"] == DECISION and r["home_lost_espn"] > 0


def test_a_rest_note_and_an_unmatched_player_flow_through(
    synthetic_db: Path, tmp_path: Path,
) -> None:
    # GAME tips off on a Tuesday evening ET; the note is posted 20 h before
    fetched = DECISION - timedelta(hours=1)

    def fill(con: duckdb.DuckDBPyConnection) -> None:
        upsert(con, "espn_injury_snapshots", pd.DataFrame([
            {"fetched_at": fetched, "team_id": ATL, "player_name": "Player 1000",
             "player_id": STAR, "status": "Day-To-Day", "comment": "He won't play Tuesday.",
             "entry_ts": TIP - timedelta(hours=20)},
            {"fetched_at": fetched, "team_id": ATL, "player_name": "Camp Invite",
             "player_id": None, "status": "Out", "comment": None, "entry_ts": None},
            {"fetched_at": fetched, "team_id": BOS, "player_name": "Player 2000",
             "player_id": 2000, "status": "Day-To-Day", "comment": "He won't play Friday.",
             "entry_ts": TIP - timedelta(hours=20)},
        ]))
        upsert(con, "espn_injury_fetches",
               pd.DataFrame([{"fetched_at": fetched, "snapshot_ts": fetched}]))

    r = rest_row(with_fetches(synthetic_db, tmp_path, fill), GAME)
    players = {p["name"]: p for p in r["home_players"]}
    assert players["Player 1000"]["matched"] and players["Player 1000"]["value"] > 0
    assert not players["Camp Invite"]["matched"] and players["Camp Invite"]["value"] == 0
    assert r["home_lost_espn"] == pytest.approx(players["Player 1000"]["value"])
    assert r["away_players"] == [] and r["away_lost_espn"] == 0


def opener_prediction(root: Path, tmp_path: Path, name: str, rest_data: bool) -> pd.DataFrame:
    path = tmp_path / f"{name}.duckdb"
    shutil.copy(root / "league.duckdb", path)
    con = duckdb.connect(str(path))
    try:
        fs = build_features(con)
        if rest_data:
            decision = one_row(fs.features, OPENER)["decision_ts"]
            add_espn_snapshot(con, pd.Timestamp(decision).to_pydatetime() - timedelta(hours=1),
                              [(ATL, STAR, "Out")])
            fs = build_features(con)
        games = con.execute("select game_id, tip_off_utc from games").df()
    finally:
        con.close()
    rows = fs.features.merge(games, on="game_id")
    rows = rows[rows["game_id"] == OPENER].reset_index(drop=True)
    models = load_models(Registry(models_settings(root / "artifacts").models_dir))
    params = RestParams(0.5, 0.4, 0.0, use_margin=True, use_total=True, use_win=False,
                        fitted_at=D1_NOON)
    return prediction_rows(fs, rows, models, {}, D1_NOON, params)


def test_a_season_opener_shows_the_list_but_keeps_the_model_values(
    trained: Path, tmp_path: Path,
) -> None:
    plain = opener_prediction(trained, tmp_path, "plain", rest_data=False)
    shown = opener_prediction(trained, tmp_path, "shown", rest_data=True)
    pd.testing.assert_frame_equal(plain.drop(columns="rest"), shown.drop(columns="rest"))
    assert plain["raw_margin_mu"].isna().all()
    block = json.loads(shown["rest"].iloc[0])
    assert block["adjusted"] is False and block["note"] == FALLBACK
    listed = [s for s in ("home", "away") if block[s]["players"]]
    assert len(listed) == 1
    side, other = listed[0], {"home": "away", "away": "home"}[listed[0]]
    assert block[side]["players"][0]["player_id"] == STAR and block[side]["lost"] > 0
    assert block[other] == {"lost": 0.0, "players": []}
