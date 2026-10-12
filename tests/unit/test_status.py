from datetime import date

import pandas as pd

from avaris.ingest.status import check_report, expected_regular_games

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
