from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from avaris.seasons import (
    et_date,
    is_finished,
    season_for_date,
    season_range,
    season_start_year,
    season_type_from_game_id,
)

ET = ZoneInfo("America/New_York")


@pytest.mark.parametrize(
    ("d", "season"),
    [
        (date(2026, 10, 12), "2026-27"),
        (date(2026, 6, 20), "2025-26"),
        (date(2026, 7, 1), "2025-26"),
        (date(2026, 9, 1), "2026-27"),
        (date(2013, 1, 1), "2012-13"),
        (date(2020, 8, 15), "2019-20"),  # bubble ran past July 1
        (date(2020, 10, 11), "2019-20"),  # 2020 Finals ended Oct 11
        (date(2020, 12, 22), "2020-21"),
    ],
)
def test_season_for_date(d: date, season: str) -> None:
    assert season_for_date(d) == season


def test_season_range_inclusive() -> None:
    assert season_range("2012-13", "2015-16") == ["2012-13", "2013-14", "2014-15", "2015-16"]
    assert season_range("1999-00", "2000-01") == ["1999-00", "2000-01"]


def test_season_start_year() -> None:
    assert season_start_year("2019-20") == 2019
    assert season_start_year("1999-00") == 1999


def test_is_finished() -> None:
    assert is_finished("2025-26", today=date(2026, 10, 12))
    assert not is_finished("2026-27", today=date(2026, 10, 12))


@pytest.mark.parametrize(
    ("game_id", "season_type"),
    [
        ("0012500001", "preseason"),
        ("0022500604", "regular"),
        ("0042500101", "playoffs"),
        ("0052000101", "play_in"),
        ("0062300001", "cup_final"),
        ("0032500001", None),  # All-Star events are dropped
    ],
)
def test_season_type_from_game_id(game_id: str, season_type: str | None) -> None:
    assert season_type_from_game_id(game_id) == season_type


def test_et_date_late_tip_stays_same_day() -> None:
    # 10:30 pm EST tip = 03:30 UTC next day
    assert et_date(datetime(2020, 1, 11, 3, 30)) == date(2020, 1, 10)
    # 10:30 pm EDT tip = 02:30 UTC next day
    assert et_date(datetime(2019, 10, 23, 2, 30)) == date(2019, 10, 22)


@given(
    st.datetimes(min_value=datetime(2012, 1, 1), max_value=datetime(2030, 12, 31)),
)
def test_et_date_matches_zoneinfo(naive_utc: datetime) -> None:
    expected = naive_utc.replace(tzinfo=UTC).astimezone(ET).date()
    assert et_date(naive_utc) == expected


@given(st.dates(min_value=date(2012, 1, 1), max_value=date(2030, 12, 31)), st.integers(12, 23))
def test_et_evening_tips_map_to_their_et_date(d: date, hour: int) -> None:
    local = datetime(d.year, d.month, d.day, hour, 0, tzinfo=ET)
    utc_naive = local.astimezone(UTC).replace(tzinfo=None)
    assert et_date(utc_naive) == d
