from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from avaris.db import connect, upsert
from avaris.ingest.odds_status import check_odds, odds_report, reconcile_run
from tests.conftest import records_by

TODAY = date(2026, 10, 12)


def report_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "season": "2021-22", "regular_games": 1230, "with_open": 1230, "with_decision": 1230,
        "with_close": 1230, "events": 1300, "unmatched_events": 5,
    }
    return {**row, **overrides}


def check(*rows: dict[str, object]) -> list[str]:
    return check_odds(pd.DataFrame(list(rows)), today=TODAY)


def test_complete_season_passes() -> None:
    assert check(report_row()) == []


def test_missing_kinds_fail() -> None:
    failures = check(report_row(with_close=1200, with_open=1229))
    assert any("1200 of 1230 regular-season games have a close" in f for f in failures)
    assert any("open" in f for f in failures)


def test_unmatched_rate_over_one_percent_fails() -> None:
    assert check(report_row(unmatched_events=13)) == [
        "2021-22: 13 of 1300 events unmatched (1.00%, limit < 1%)"
    ]


def test_no_odds_for_a_finished_season_fails() -> None:
    assert check(report_row(events=0, unmatched_events=0, with_open=0, with_decision=0,
                            with_close=0))


def test_in_progress_season_is_not_checked() -> None:
    assert check(report_row(season="2026-27", with_close=0)) == []


def test_empty_report_fails() -> None:
    assert check_odds(pd.DataFrame(), today=TODAY) == ["no odds snapshots ingested"]


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    return connect(tmp_path / "a.duckdb")


def test_odds_report_counts_kinds_and_unmatched_events(con: duckdb.DuckDBPyConnection) -> None:
    games = [
        {"game_id": g, "season": "2021-22", "season_type": "regular",
         "game_date_et": date(2022, 1, 15), "tip_off_utc": datetime(2022, 1, 16, 0, 0),
         "home_team_id": h, "away_team_id": 1, "status": "final", "neutral_site": False}
        for g, h in (("g1", 2), ("g2", 3))
    ]
    upsert(con, "games", pd.DataFrame(games))
    snaps = [
        {"game_id": "g1", "event_id": "e1", "snapshot_ts": datetime(2022, 1, 15, h), "book": "b",
         "market": "h2h", "side": "home", "line": None, "price": 1.9, "book_last_update": None,
         "kind": k}
        for h, k in ((14, "open"), (22, "decision"), (23, "close"))
    ]
    upsert(con, "odds_snapshots", pd.DataFrame(snaps))
    events = [
        {"event_id": e, "game_id": g, "home_team": "x", "away_team": "y", "home_team_id": None,
         "away_team_id": None, "commence_time_utc": datetime(2022, 1, 16, 0, 0),
         "match_status": s}
        for e, g, s in (("e1", "g1", "matched"), ("e2", None, "no_game"),
                        ("e3", None, "preseason"))
    ]
    upsert(con, "odds_events", pd.DataFrame(events))
    row = records_by(odds_report(con), "season")["2021-22"]
    assert row["regular_games"] == 2
    assert (row["with_open"], row["with_decision"], row["with_close"]) == (1, 1, 1)
    assert row["events"] == 2  # preseason events are not counted
    assert row["unmatched_events"] == 1


def _ledger(con: duckdb.DuckDBPyConnection, rows: list[tuple[str, int, int | None, str]]) -> None:
    for purpose, actual, used, status in rows:
        con.execute(
            "insert into api_usage (run_id, ts_utc, endpoint, purpose, est_cost, actual_cost, "
            "requests_used, status) values ('r1', now(), '/x', ?, ?, ?, ?, ?)",
            [purpose, actual, actual, used, status],
        )


def test_reconcile_run_matches_ledger_to_usage_headers(con: duckdb.DuckDBPyConnection) -> None:
    _ledger(con, [("prime", 0, 100, "ok"), ("open", 30, 130, "ok"),
                  ("close", 30, 160, "ok"), ("close", 0, None, "refused")])
    assert reconcile_run(con, "r1") == (60, 60)


def test_reconcile_run_exposes_a_gap(con: duckdb.DuckDBPyConnection) -> None:
    _ledger(con, [("prime", 0, 100, "ok"), ("open", 30, 140, "ok")])
    assert reconcile_run(con, "r1") == (30, 40)
