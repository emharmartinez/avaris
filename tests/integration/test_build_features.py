import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import pytest

from avaris.features.build import (
    MODEL_FEATURES,
    FeatureSet,
    build_features,
    feature_hash,
    model_frame,
    write_features,
)
from tests.fixtures.synthetic import ATL, BOS, BUBBLE, TRADE_ROUND, TRADED_PLAYER

# The contract, independent of the implementation's constant: a result is known 3 h
# after tip-off
RESULT_LAG = timedelta(hours=3)


def build(path: Path) -> FeatureSet:
    con = duckdb.connect(str(path))
    try:
        return build_features(con)
    finally:
        con.close()


@pytest.fixture
def built(synthetic_db: Path) -> FeatureSet:
    return build(synthetic_db)


def row(fs: FeatureSet, game_id: str) -> dict[str, Any]:
    match = fs.features[fs.features["game_id"] == game_id]
    assert len(match) == 1, game_id
    return {str(k): v for k, v in match.iloc[0].to_dict().items()}


def same(a: Any, b: Any) -> bool:
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    if a is None or b is None or (isinstance(a, float) and math.isnan(a)):
        return (a is None or a != a) and (b is None or b != b)
    return a == pytest.approx(b) if isinstance(a, float) else a == b


def assert_rows_equal(a: dict[str, Any], b: dict[str, Any]) -> None:
    diffs = {k: (a[k], b[k]) for k in a if not same(a[k], b[k])}
    assert not diffs


def test_one_row_per_game_with_a_tip_off(built: FeatureSet, synthetic_db: Path) -> None:
    con = duckdb.connect(str(synthetic_db))
    row_ = con.execute("select count(*) from games where tip_off_utc is not null").fetchone()
    assert row_ is not None
    assert len(built.features) == row_[0] == built.features["game_id"].nunique()
    assert len(built.team_ratings) == 2 * len(built.features)


def cut_after(path: Path, game_id: str, decision_ts: datetime) -> None:
    # Delete everything with a timestamp after decision_ts: results (tip-off + lag) and
    # injury reports. The schedule is known in advance, so games rows stay. The target
    # game's own player rows stay: who played is post-hoc by design (lost_actual)
    con = duckdb.connect(str(path))
    late = "select game_id from games where tip_off_utc + ? > ?"
    params = [RESULT_LAG, decision_ts]
    con.execute(f"delete from team_games where game_id in ({late})", params)
    con.execute(
        f"delete from player_games where game_id in ({late}) and game_id <> ?",
        [*params, game_id],
    )
    con.execute(
        f"update games set home_pts = null, away_pts = null, status = 'scheduled' "
        f"where game_id in ({late})",
        params,
    )
    con.execute("delete from injury_reports where report_ts > ?", [decision_ts])
    con.execute("delete from injury_report_files where report_ts > ?", [decision_ts])
    con.close()


@pytest.mark.parametrize(
    "game_id",
    [
        "0022100013",  # 2021-22, a late scratch reported after decision_ts
        "0022100031",  # 2021-22, after the trade, during the long injury
        "0022000040",  # 2020-21, no reports
        "0042000049",  # playoffs
        "0012100003",  # preseason
        "0021900045",  # bubble
    ],
)
def test_leakage_deleting_rows_after_decision_ts_changes_nothing(
    built: FeatureSet, synthetic_db: Path, game_id: str
) -> None:
    before = row(built, game_id)
    cut_after(synthetic_db, game_id, before["decision_ts"].to_pydatetime())
    after = row(build(synthetic_db), game_id)
    assert_rows_equal(before, after)


def test_leakage_test_detects_a_late_report(built: FeatureSet, synthetic_db: Path) -> None:
    # Guard: the report after decision_ts lists more players out than the decision report
    game = row(built, "0022100013")
    con = duckdb.connect(str(synthetic_db))
    counts = con.execute(
        "select count(*) filter (where report_ts > $d), count(*) filter (where report_ts = $d) "
        "from injury_reports where game_id = $g and status = 'out'",
        {"d": game["decision_ts"], "g": "0022100013"},
    ).fetchone()
    assert counts is not None and counts[0] > counts[1]
    assert game["report_ts"] == game["decision_ts"]


def test_traded_player_leaves_old_team_at_first_appearance_for_new_team(
    built: FeatureSet, synthetic_db: Path
) -> None:
    con = duckdb.connect(str(synthetic_db))
    first_bos = con.execute(
        "select min(g.tip_off_utc) from player_games p join games g using (game_id) "
        "where p.player_id = ? and p.team_id = ?",
        [TRADED_PLAYER, BOS],
    ).fetchone()
    assert first_bos is not None
    known = first_bos[0] + RESULT_LAG
    avail = built.availability.merge(built.features[["game_id", "decision_ts", "season"]])
    traded = avail[(avail["player_id"] == TRADED_PLAYER) & (avail["season"] == "2021-22")]
    atl = traded[traded["team_id"] == ATL]
    bos = traded[traded["team_id"] == BOS]
    assert (atl["decision_ts"] < known).all()
    assert len(atl) >= TRADE_ROUND - 1
    assert (bos["decision_ts"] >= known).all()
    assert len(bos) > 0


def test_neutral_site_bubble_games(built: FeatureSet) -> None:
    con_games = built.features
    bubble = con_games[con_games["game_id"].isin(bubble_ids(built))]
    assert len(bubble) == 8
    assert (bubble["home_court"] == 0).all()
    for side in ("home", "away"):
        assert (bubble[f"{side}_travel_km"] == 0).all()
        assert (bubble[f"{side}_tz_shift"] == 0).all()
    assert (bubble["elo_margin"].abs() < 15).all()


def bubble_ids(fs: FeatureSet) -> list[str]:
    return fs.venues[fs.venues["venue"] == BUBBLE]["game_id"].tolist()


def test_no_fans_and_season_type_flags(built: FeatureSet) -> None:
    f = built.features.set_index("game_id")
    assert f.loc["0022000003", "no_fans"] == 1
    assert f.loc["0022100003", "no_fans"] == 0
    assert f.loc["0012100001", "is_preseason"] == 1
    assert f.loc["0042000049", "is_postseason"] == 1


def test_preseason_game_gets_features_at_full_strength(built: FeatureSet) -> None:
    game = row(built, "0012100001")
    assert game["home_elo"] != 1500 and not math.isnan(game["home_ortg"])
    assert game["home_gp"] == 0
    for col in ("home_lost_actual", "home_lost_report", "home_full_strength"):
        assert math.isnan(game[col])


def test_deleting_preseason_leaves_other_games_unchanged(
    built: FeatureSet, synthetic_db: Path
) -> None:
    con = duckdb.connect(str(synthetic_db))
    con.execute("delete from games where season_type = 'preseason'")
    con.close()
    after = build(synthetic_db).features
    before = built.features[built.features["season_type"] != "preseason"]
    pd.testing.assert_frame_equal(
        before.reset_index(drop=True), after.reset_index(drop=True), check_dtype=False
    )


def test_actual_vs_report_availability(built: FeatureSet) -> None:
    f = built.features
    # Unknown before a team's first game of the season
    first = f[(f["season_type"] == "regular") & (f["home_gp"] == 0)]
    assert len(first) > 0 and first["home_full_strength"].isna().all()
    f = f[f["home_gp"] > 0]
    reg = f[(f["season"] == "2021-22") & (f["season_type"] == "regular")]
    played = reg.dropna(subset=["home_lost_actual"])
    assert (played["home_lost_actual"] >= 0).all()
    assert (reg["home_lost_report"] >= 0).all()
    # 2020-21 has no injury report: nothing is reported lost
    old = f[(f["season"] == "2020-21") & (f["season_type"] == "regular")]
    assert (old["home_lost_report"] == 0).all()
    # Unplayed games have no actual availability
    assert f[f["game_id"] == "0022100047"]["home_lost_actual"].isna().all()


def test_model_frame_uses_neutral_availability_names(built: FeatureSet) -> None:
    actual = model_frame(built.features, availability="actual")
    report = model_frame(built.features, availability="report")
    assert list(actual.columns) == list(report.columns)
    assert "home_lost" in actual.columns
    assert not any("actual" in c or "report" in c for c in actual.columns)
    pd.testing.assert_series_equal(
        actual["home_lost"], built.features["home_lost_actual"], check_names=False
    )


def test_write_features_replaces_tables(built: FeatureSet, synthetic_db: Path) -> None:
    con = duckdb.connect(str(synthetic_db))
    from avaris.db import migrate

    migrate(con)
    write_features(con, built)
    write_features(con, built)
    counts = con.execute(
        "select (select count(*) from features), (select count(*) from team_ratings)"
    ).fetchone()
    assert counts == (len(built.features), len(built.team_ratings))


def test_report_entries_come_from_the_games_own_date(
    built: FeatureSet, synthetic_db: Path
) -> None:
    # Reports also list the next day's games; those entries must not leak into today's
    con = duckdb.connect(str(synthetic_db))
    entries = con.execute(
        "select report_ts, team_id, game_date_et, player_id, status from injury_reports"
    ).df()
    con.close()
    avail = built.availability.merge(
        built.features[["game_id", "report_ts", "game_date_et"]], on="game_id"
    )
    listed = avail[avail["report_status"].notna()]
    assert len(listed) > 0
    merged = listed.merge(
        entries, on=["report_ts", "team_id", "game_date_et", "player_id"], how="left"
    )
    assert (merged["status"] == merged["report_status"]).all()


def test_listed_player_without_games_this_season_joins_the_set(built: FeatureSet) -> None:
    # BOS's star is hurt from 2021-22 round 4: once out of the set (10 misses) he is
    # still counted while listed, in full strength and in both lost columns
    from tests.fixtures.synthetic import INJURED_STAR

    avail = built.availability.merge(built.features[["game_id", "season"]])
    star = avail[(avail["player_id"] == INJURED_STAR) & (avail["season"] == "2021-22")]
    listed = star[star["report_status"] == "out"]
    assert len(listed) >= 10
    assert (listed["absent_report"] == 1).all()
    assert listed["absent_actual"].dropna().astype(bool).all()


@pytest.mark.parametrize(("offset", "included"), [
    (timedelta(minutes=-1), True), (timedelta(0), True), (timedelta(minutes=1), False),
])
def test_result_counts_from_tip_off_plus_3_hours(
    synthetic_db: Path, offset: timedelta, included: bool
) -> None:
    # Move another game's tip so its result lands just before, at or just after this
    # game's decision_ts; only the first two may feed the league average
    target, other = "0022000041", "0022000042"  # same 2020-21 day, different teams
    con = duckdb.connect(str(synthetic_db))
    tip = con.execute("select tip_off_utc from games where game_id = ?", [target]).fetchone()
    assert tip is not None
    decision = tip[0] - timedelta(minutes=60)
    con.execute("update games set tip_off_utc = ? where game_id = ?",
                [decision - RESULT_LAG + offset, other])
    con.close()
    with_result = row(build(synthetic_db), target)["league_total"]
    con = duckdb.connect(str(synthetic_db))
    con.execute("update games set home_pts = null, away_pts = null, status = 'scheduled' "
                "where game_id = ?", [other])
    con.close()
    without = row(build(synthetic_db), target)["league_total"]
    assert (with_result != without) == included


def test_season_to_date_ratings_are_stored_but_not_model_features(built: FeatureSet) -> None:
    # Naive-baseline inputs: adding them must not change the frozen models' features
    std = [f"{side}_{k}_std" for side in ("home", "away") for k in ("ortg", "drtg", "pace")]
    assert set(std) <= set(built.features.columns)
    assert not set(std) & set(MODEL_FEATURES)
    assert feature_hash() == "7723ef74696d81d3"  # feature version 2, the tuned models
    opener = built.features[(built.features["season_type"] == "regular")].iloc[0]
    assert math.isnan(opener["home_ortg_std"])
    later = built.features[built.features["home_gp"] >= 3].iloc[0]
    assert later["home_ortg_std"] > 0
