from datetime import datetime

from avaris.features.decision_time import decision_ts

TIP = datetime(2022, 1, 16, 0, 0)  # 7:00 pm ET on Jan 15


def test_latest_report_at_or_before_tip_minus_60() -> None:
    reports = [datetime(2022, 1, 15, 18, 30), datetime(2022, 1, 15, 22, 30)]
    assert decision_ts(TIP, reports) == datetime(2022, 1, 15, 22, 30)


def test_report_exactly_at_cutoff_counts() -> None:
    reports = [datetime(2022, 1, 15, 22, 30), datetime(2022, 1, 15, 23, 0)]
    assert decision_ts(TIP, reports) == datetime(2022, 1, 15, 23, 0)


def test_reports_after_cutoff_are_ignored() -> None:
    reports = [datetime(2022, 1, 15, 22, 30), datetime(2022, 1, 15, 23, 30)]
    assert decision_ts(TIP, reports) == datetime(2022, 1, 15, 22, 30)


def test_no_report_falls_back_to_tip_minus_60() -> None:
    # All of 2020-21 and any day with no report
    assert decision_ts(TIP, []) == datetime(2022, 1, 15, 23, 0)
    assert decision_ts(TIP, [datetime(2022, 1, 16, 0, 30)]) == datetime(2022, 1, 15, 23, 0)


def test_unsorted_reports() -> None:
    reports = [datetime(2022, 1, 15, 22, 30), datetime(2022, 1, 15, 18, 30)]
    assert decision_ts(TIP, reports) == datetime(2022, 1, 15, 22, 30)


def test_previous_day_report_is_ignored() -> None:
    # Only reports within 12 h of tip-off belong to the game's day
    assert decision_ts(TIP, [datetime(2022, 1, 14, 22, 30)]) == datetime(2022, 1, 15, 23, 0)
    assert decision_ts(TIP, [datetime(2022, 1, 15, 11, 30)]) == datetime(2022, 1, 15, 23, 0)
    assert decision_ts(TIP, [datetime(2022, 1, 15, 12, 0)]) == datetime(2022, 1, 15, 12, 0)
