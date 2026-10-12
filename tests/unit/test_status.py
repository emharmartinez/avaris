from datetime import date, datetime
from pathlib import Path

import pandas as pd

from avaris.db import connect, upsert
from avaris.ingest.status import (
    check_injuries,
    check_report,
    expected_regular_games,
    injury_report,
)
from tests.conftest import records_by

TODAY = date(2026, 10, 12)


def report_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "season": "2021-22",
        "regular": 1230,
        "missing_tip_off": 0,
        "finals_missing_team_logs": 0,
        "roster_teams": 30,
        "unknown_venues": 0,
        "bubble_not_neutral": 0,
        "bubble_neutral": 0,
    }
    return {**row, **overrides}


def check(*rows: dict[str, object]) -> list[str]:
    return check_report(pd.DataFrame(list(rows)), today=TODAY)


def test_expected_regular_games() -> None:
    assert expected_regular_games("2012-13") == 1229
    assert expected_regular_games("2019-20") == 1059
    assert expected_regular_games("2020-21") == 1080
    assert expected_regular_games("2021-22") == 1230


def test_clean_report_passes() -> None:
    assert check(report_row()) == []


def test_wrong_regular_count_fails_for_finished_season() -> None:
    assert check(report_row(regular=1200))


def test_in_progress_season_skips_count_check() -> None:
    assert check(report_row(season="2026-27", regular=10, roster_teams=30)) == []


def test_missing_tip_off_fails_from_2020_21_only() -> None:
    assert check(report_row(season="2018-19", missing_tip_off=3)) == []
    assert check(report_row(season="2020-21", regular=1080, missing_tip_off=1))


def test_bubble_must_be_tagged_neutral() -> None:
    row = report_row(season="2019-20", regular=1059, bubble_neutral=172)
    assert check(row) == []
    assert check({**row, "bubble_not_neutral": 1})
    assert check({**row, "bubble_neutral": 0})


def test_missing_logs_rosters_and_unknown_venues_fail() -> None:
    assert check(report_row(finals_missing_team_logs=1))
    assert check(report_row(roster_teams=29))
    assert check(report_row(unknown_venues=1))


def test_empty_report_fails() -> None:
    assert check_report(pd.DataFrame(), today=TODAY)


def injury_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "season": "2021-22", "regular_games": 1230, "with_decision_report": 1230,
        "named_entries": 1000, "unmatched_players": 10,
    }
    return {**row, **overrides}


def test_injury_coverage_passes_when_every_game_has_a_decision_report() -> None:
    assert check_injuries(pd.DataFrame([injury_row()]), today=TODAY) == []


def test_injury_coverage_gap_fails() -> None:
    failures = check_injuries(pd.DataFrame([injury_row(with_decision_report=1229)]), today=TODAY)
    assert failures == ["2021-22: 1229 of 1230 regular-season games in a report by tip-off - 60"]


def test_injury_coverage_skips_in_progress_season() -> None:
    row = injury_row(season="2026-27", with_decision_report=0)
    assert check_injuries(pd.DataFrame([row]), today=TODAY) == []


def test_injury_unmatched_player_rate_over_five_percent_fails() -> None:
    failures = check_injuries(pd.DataFrame([injury_row(unmatched_players=60)]), today=TODAY)
    assert failures == ["2021-22: 60 of 1000 injury rows without a player ID (6.00%, limit < 5%)"]


def test_no_injury_reports_fails() -> None:
    assert check_injuries(pd.DataFrame(), today=TODAY) == ["no injury reports ingested"]


def test_previous_evening_placeholder_does_not_cover_a_game(tmp_path: Path) -> None:
    con = connect(tmp_path / "a.duckdb")
    upsert(con, "games", pd.DataFrame([{
        "game_id": "g", "season": "2021-22", "season_type": "regular",
        "game_date_et": date(2022, 1, 16), "tip_off_utc": datetime(2022, 1, 16, 18, 0),
        "home_team_id": 1, "away_team_id": 2, "status": "final", "neutral_site": False,
    }]))
    upsert(con, "injury_reports", pd.DataFrame([{
        "report_ts": datetime(2022, 1, 15, 22, 30), "game_date_et": date(2022, 1, 16),
        "matchup": "A@B", "game_id": "g", "team_id": 1, "player_name": "", "player_id": None,
        "status": "not_submitted", "reason": "NOT YET SUBMITTED",
    }]))
    assert records_by(injury_report(con), "season")["2021-22"]["with_decision_report"] == 0
