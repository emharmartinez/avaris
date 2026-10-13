import json
import shutil
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import httpx
import numpy as np
import pandas as pd
import pytest

from avaris.config import Settings
from avaris.db import connect, upsert
from avaris.features.build import build_features, feature_hash
from avaris.models.dataset import with_targets
from avaris.models.registry import Registry
from avaris.pipeline.daily import DailySummary, is_stale, prediction_status, run_daily
from avaris.pipeline.score import score_predictions
from avaris.pipeline.train import train
from tests.fixtures.live import D1, D2, models_settings, train_before_d1
from tests.fixtures.synthetic import ATL, BOS, INJURED_STAR

TIP_D1 = datetime(2021, 11, 27, 0, 0)  # naive UTC, 7 pm ET
NOON_D1 = datetime(2021, 11, 26, 17, 0)  # noon ET
AFTER_CUTOFF_D1 = datetime(2021, 11, 26, 23, 30)  # tip - 30 min


@pytest.fixture(scope="module")
def trained(
    synthetic_db_template: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, Path]:
    # The synthetic league plus models trained on every game before D1
    root = tmp_path_factory.mktemp("daily")
    db = root / "league.duckdb"
    shutil.copy(synthetic_db_template, db)
    train_before_d1(db, root / "artifacts")
    return db, root / "artifacts"


@pytest.fixture
def env(trained: tuple[Path, Path], tmp_path: Path) -> Iterator[tuple[duckdb.DuckDBPyConnection,
                                                                         Settings]]:
    db, artifacts = trained
    shutil.copy(db, tmp_path / "league.duckdb")
    shutil.copytree(artifacts, tmp_path / "artifacts")
    settings = Settings(models=models_settings(tmp_path / "artifacts"))
    con = connect(tmp_path / "league.duckdb")
    yield con, settings
    con.close()


def daily(con: duckdb.DuckDBPyConnection, settings: Settings, now: datetime) -> DailySummary:
    return run_daily(con, settings, now=now, refresh=None)


def predictions(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(
        "select p.*, g.game_date_et from predictions p join games g using (game_id) "
        "order by game_id"
    ).df()


def add_report(
    con: duckdb.DuckDBPyConnection, report_ts: datetime, day: date, player_id: int, team: int
) -> None:
    upsert(con, "injury_report_files", pd.DataFrame([{
        "slot_ts": report_ts, "report_ts": report_ts, "url": "test", "status": "ok",
        "n_entries": 1, "fetched_at": report_ts, "message": None,
    }]))
    upsert(con, "injury_reports", pd.DataFrame([{
        "report_ts": report_ts, "game_date_et": day, "matchup": "test", "game_id": None,
        "team_id": team, "player_name": f"Player, {player_id}", "player_id": player_id,
        "status": "out", "reason": "Injury",
    }]))


def test_prediction_status_turns_final_at_tip_minus_60() -> None:
    assert prediction_status(TIP_D1, TIP_D1 - timedelta(minutes=61)) == "provisional"
    assert prediction_status(TIP_D1, TIP_D1 - timedelta(minutes=60)) == "final"


def test_provisional_predictions_for_todays_games(
    env: tuple[duckdb.DuckDBPyConnection, Settings],
) -> None:
    con, settings = env
    summary = daily(con, settings, NOON_D1)
    preds = predictions(con)
    assert summary.provisional == 2 and summary.final == 0
    assert set(preds["game_date_et"].dt.date) == {D1}
    assert set(preds["status"]) == {"provisional"}
    assert (preds[["home_win_run", "margin_run", "total_run"]] == "r1").all().all()
    assert preds["p_home_win"].between(0, 1).all()
    assert (preds["margin_sigma"] > 0).all() and (preds["total_sigma"] > 0).all()
    assert (preds["decision_ts"] == TIP_D1 - timedelta(minutes=60)).all()
    for _, row in preds.iterrows():
        drivers = json.loads(row["drivers"])
        assert drivers["home_win"]["scale"] == "log_odds"
        for target, mu in (("margin", row["margin_mu"]), ("total", row["total_mu"])):
            d = drivers[target]
            assert d["base"] + sum(d["families"].values()) == pytest.approx(mu)
            assert len(d["top"]) == 3
        p = 1 / (1 + np.exp(-(drivers["home_win"]["base"]
                               + sum(drivers["home_win"]["families"].values()))))
        assert p == pytest.approx(row["p_home_win"])
        injuries = json.loads(row["injuries"])
        assert set(injuries) == {"home", "away"}
        assert injuries["home"]["full_strength"] > 0


def test_rerun_changes_nothing_unless_new_data_arrived(
    env: tuple[duckdb.DuckDBPyConnection, Settings],
) -> None:
    con, settings = env
    daily(con, settings, NOON_D1)
    first = predictions(con)
    summary = daily(con, settings, NOON_D1 + timedelta(hours=1))
    assert summary.provisional == 0 and summary.unchanged == 2
    pd.testing.assert_frame_equal(predictions(con), first)

    # A new report listing BOS's best player out moves BOS's game
    report_ts = NOON_D1 + timedelta(hours=2)
    add_report(con, report_ts, D1, INJURED_STAR, BOS)
    summary = daily(con, settings, report_ts + timedelta(minutes=5))
    assert summary.provisional == 2  # every game's decision report changed
    after = predictions(con)
    assert (after["report_ts"] == report_ts).all()
    bos = after[after["game_id"].isin(con.execute(
        "select game_id from games where game_date_et = ? and ? in (home_team_id, away_team_id)",
        [D1, BOS]).df()["game_id"])]
    side = json.loads(bos.iloc[0]["injuries"])
    lost = [p["player_id"] for s in side.values() if s for p in s["players"]]
    assert INJURED_STAR in lost


def test_final_after_decision_ts_is_never_rewritten(
    env: tuple[duckdb.DuckDBPyConnection, Settings],
) -> None:
    con, settings = env
    daily(con, settings, NOON_D1)
    summary = daily(con, settings, AFTER_CUTOFF_D1)
    assert summary.final == 2
    final = predictions(con)
    assert set(final["status"]) == {"final"}
    # A report for the decision window that lands after the final changes nothing
    add_report(con, TIP_D1 - timedelta(minutes=75), D1, INJURED_STAR, BOS)
    summary = daily(con, settings, AFTER_CUTOFF_D1 + timedelta(minutes=10))
    assert summary.final == 0 and summary.provisional == 0
    pd.testing.assert_frame_equal(predictions(con), final)


def test_catch_up_predicts_missed_games_before_a_stale_retrain(
    env: tuple[duckdb.DuckDBPyConnection, Settings],
) -> None:
    con, settings = env
    later = datetime(2021, 12, 6, 17, 0)  # D1 + 10 days, the model is stale
    summary = daily(con, settings, later)
    preds = predictions(con)
    assert summary.final == 4
    assert set(preds["game_date_et"].dt.date) == {D1, D2}
    assert set(preds["status"]) == {"final"}
    assert (preds["margin_run"] == "r1").all()  # predicted by the model that never saw them
    assert summary.retrained
    registry = Registry(settings.models.models_dir)
    runs = [registry.production("margin"), *registry.candidates("margin")]
    assert any(r != "r1" and registry.read_meta("margin", r)["through"] == "2021-12-06"
               for r in runs if r)
    # The retrained runs are not stale: a rerun neither retrains nor predicts
    again = daily(con, settings, later + timedelta(hours=1))
    assert not again.retrained and again.final == 0


def test_games_the_model_trained_on_are_skipped(
    env: tuple[duckdb.DuckDBPyConnection, Settings], tmp_path: Path
) -> None:
    con, settings = env
    data = with_targets(build_features(con).features, con)
    train(data, settings.models, through=D2 + timedelta(days=1), run_id="r2",
          now=datetime(2021, 11, 28))
    for target in ("home_win", "margin", "total"):
        Registry(settings.models.models_dir).promote(target, "r2", feature_hash())
    summary = daily(con, settings, datetime(2021, 11, 28, 17, 0))
    assert summary.final == 0 and summary.provisional == 0
    assert predictions(con).empty


def test_is_stale(env: tuple[duckdb.DuckDBPyConnection, Settings], tmp_path: Path) -> None:
    _, settings = env
    registry = Registry(settings.models.models_dir)
    assert not is_stale(registry, D1 + timedelta(days=6), 7)
    assert is_stale(registry, D1 + timedelta(days=7), 7)
    assert is_stale(Registry(tmp_path / "empty"), D1, 7)


def test_score_fills_prediction_scores_once_per_result(
    env: tuple[duckdb.DuckDBPyConnection, Settings],
) -> None:
    con, settings = env
    daily(con, settings, AFTER_CUTOFF_D1)
    assert score_predictions(con, AFTER_CUTOFF_D1) == 0  # games not final yet
    con.execute("update games set home_pts = 110, away_pts = 100, status = 'final' "
                "where game_date_et = ?", [D1])
    scored_at = datetime(2021, 11, 27, 12, 0)
    assert score_predictions(con, scored_at) == 2
    scores = con.execute(
        "select s.*, p.p_home_win, p.margin_mu, p.margin_sigma from prediction_scores s "
        "join predictions p using (game_id)"
    ).df()
    assert (scores["home_win"] == 1).all() and (scores["margin"] == 10).all()
    assert scores["log_loss"].to_numpy() == pytest.approx(-np.log(scores["p_home_win"]))
    assert scores["margin_error"].to_numpy() == pytest.approx(10 - scores["margin_mu"])
    assert scores["correct"].tolist() == (scores["p_home_win"] > 0.5).tolist()
    assert score_predictions(con, scored_at + timedelta(hours=1)) == 0
    con.execute("update games set home_pts = 99 where game_date_et = ? and home_team_id = ?",
                [D1, ATL])
    assert score_predictions(con, scored_at + timedelta(hours=2)) == 1


def test_provisional_predictions_are_not_scored(
    env: tuple[duckdb.DuckDBPyConnection, Settings],
) -> None:
    con, settings = env
    daily(con, settings, NOON_D1)
    con.execute("update games set home_pts = 110, away_pts = 100, status = 'final' "
                "where game_date_et = ?", [D1])
    assert score_predictions(con, NOON_D1) == 0


def test_a_failed_refresh_is_a_warning(
    env: tuple[duckdb.DuckDBPyConnection, Settings],
) -> None:
    con, settings = env

    def offline(*_args: object) -> None:
        raise httpx.ConnectError("no network")

    summary = run_daily(con, settings, now=NOON_D1, refresh=offline)
    assert not summary.refreshed
    assert any("no network" in w for w in summary.warnings)
    assert summary.provisional == 2



def test_a_same_day_retrain_repredicts_todays_games(
    env: tuple[duckdb.DuckDBPyConnection, Settings],
) -> None:
    con, settings = env
    settings.models.retrain_every_days = 1
    noon_d2 = datetime(2021, 11, 27, 17, 0)
    # D1's results arrived, so the retrain through D2 has more rows and is promoted
    con.execute("update games set home_pts = 110, away_pts = 100, status = 'final' "
                "where game_date_et = ?", [D1])
    summary = daily(con, settings, noon_d2)
    assert summary.retrained
    preds = predictions(con)
    d1 = preds[preds["game_date_et"].dt.date == D1]
    d2 = preds[preds["game_date_et"].dt.date == D2]
    assert set(d1["status"]) == {"final"} and (d1["margin_run"] == "r1").all()
    assert set(d2["status"]) == {"provisional"} and (d2["margin_run"] != "r1").all()
    # Counts are per game, not per pass
    assert summary.final == 2 and summary.provisional == 2 and summary.unchanged == 0


def test_a_held_candidate_warns_on_every_run(
    env: tuple[duckdb.DuckDBPyConnection, Settings],
) -> None:
    con, settings = env
    later = datetime(2021, 12, 6, 17, 0)
    daily(con, settings, later)  # retrains: same rows, so the runs are held as candidates
    registry = Registry(settings.models.models_dir)
    assert registry.production("margin") == "r1" and registry.candidates("margin")
    again = daily(con, settings, later + timedelta(hours=1))
    assert not again.retrained
    assert any("held candidate" in w and "r1" in w for w in again.warnings)


def test_any_refresh_error_is_a_warning(
    env: tuple[duckdb.DuckDBPyConnection, Settings],
) -> None:
    con, settings = env

    def blocked(*_args: object) -> None:
        raise ValueError("Injury-Report.pdf: response is not a PDF")

    summary = run_daily(con, settings, now=NOON_D1, refresh=blocked)
    assert any("not a PDF" in w for w in summary.warnings)
    assert summary.provisional == 2
