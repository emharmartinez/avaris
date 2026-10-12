from datetime import date, datetime

import pytest

from avaris.features.availability import PlayerTracker, game_score
from avaris.features.elo import (
    ELO_MEAN,
    EloRatings,
    carry_over,
    expected_margin,
    home_advantage,
    win_prob,
)
from avaris.features.schedule import ScheduleTracker, haversine_km
from avaris.features.team_form import EwMean, TeamForm, game_ratings
from avaris.ingest.teams import Venue

BOS = Venue("TD Garden", "Boston", 42.3662, -71.0621, "America/New_York", 5)
DEN = Venue("Ball Arena", "Denver", 39.7487, -105.0077, "America/Denver", 1609)


# Elo


def test_win_prob_is_symmetric_and_increasing() -> None:
    assert win_prob(0) == pytest.approx(0.5)
    assert win_prob(100) == pytest.approx(1 - win_prob(-100))
    assert win_prob(200) > win_prob(100) > 0.5


def test_expected_margin_scales_elo_points() -> None:
    assert expected_margin(280) == pytest.approx(10)


def test_home_advantage_by_site_and_season() -> None:
    assert home_advantage(home_court=1, no_fans=0) == 100
    assert home_advantage(home_court=0, no_fans=0) == 0
    assert home_advantage(home_court=1, no_fans=1) == 50


def test_carry_over_regresses_to_mean() -> None:
    assert carry_over(1605) == pytest.approx(0.75 * 1605 + 0.25 * ELO_MEAN)


def test_winner_gains_what_loser_loses_and_upsets_move_more() -> None:
    ratings = EloRatings()
    ratings.update(1, 2, "2019-20", home_pts=110, away_pts=100, hca=100)
    assert ratings.rating(1, "2019-20") > 1500 > ratings.rating(2, "2019-20")
    assert ratings.rating(1, "2019-20") + ratings.rating(2, "2019-20") == pytest.approx(3000)
    favored, upset = EloRatings(), EloRatings()
    favored.update(1, 2, "2019-20", home_pts=110, away_pts=100, hca=100)
    upset.update(2, 1, "2019-20", home_pts=100, away_pts=110, hca=100)
    assert upset.rating(1, "2019-20") - 1500 > favored.rating(1, "2019-20") - 1500


def test_rating_in_a_new_season_is_carried_over_without_mutating() -> None:
    ratings = EloRatings()
    ratings.update(1, 2, "2019-20", home_pts=120, away_pts=90, hca=100)
    end = ratings.rating(1, "2019-20")
    assert ratings.rating(1, "2020-21") == pytest.approx(carry_over(end))
    assert ratings.rating(1, "2019-20") == end


# Team form


def test_game_ratings_from_box_totals() -> None:
    team = {"pts": 110, "fga": 88, "fta": 20, "oreb": 10, "tov": 14, "minutes": 240.0}
    opp = {"pts": 100, "fga": 85, "fta": 25, "oreb": 12, "tov": 12, "minutes": 240.0}
    ortg, drtg, pace = game_ratings(team, opp)
    team_poss = 88 + 0.44 * 20 - 10 + 14
    opp_poss = 85 + 0.44 * 25 - 12 + 12
    poss = (team_poss + opp_poss) / 2
    assert ortg == pytest.approx(100 * 110 / poss)
    assert drtg == pytest.approx(100 * 100 / poss)
    assert pace == pytest.approx(poss)


def test_ew_mean_weights_recent_values_more() -> None:
    ew = EwMean(half_life=1)
    ew.add(0)
    ew.add(10)
    assert ew.value == pytest.approx(10 / 1.5)
    assert EwMean(half_life=1).value is None


def test_team_form_new_season_regresses_toward_league_and_resets_counts() -> None:
    form = TeamForm()
    for _ in range(20):
        form.add("2019-20", ortg=120, drtg=100, pace=100)
    now = form.snapshot("2019-20", league_rtg=110, league_pace=100)
    assert now["ortg"] == pytest.approx(120, abs=0.5)
    assert now["gp"] == 20
    assert now["net_l10"] == pytest.approx(20)
    nxt = form.snapshot("2020-21", league_rtg=110, league_pace=100)
    assert nxt["ortg"] is not None and now["ortg"] is not None
    assert 110 < nxt["ortg"] < now["ortg"]
    assert nxt["gp"] == 0
    assert nxt["net_l10"] is None


# Schedule


def test_haversine_boston_denver() -> None:
    assert haversine_km(BOS, DEN) == pytest.approx(2840, rel=0.02)


def test_rest_b2b_and_three_in_four() -> None:
    sched = ScheduleTracker()
    sched.add(1, datetime(2022, 1, 2, 0), date(2022, 1, 1), BOS)
    sched.add(1, datetime(2022, 1, 4, 0), date(2022, 1, 3), BOS)
    f = sched.snapshot(1, datetime(2022, 1, 5, 0), date(2022, 1, 4), DEN)
    assert f["rest_days"] == 1
    assert f["b2b"] == 1
    assert f["3in4"] == 1
    assert f["travel_km"] == pytest.approx(haversine_km(BOS, DEN))
    assert f["tz_shift"] == -2


def test_first_game_and_long_gap_mean_full_rest_and_no_travel() -> None:
    sched = ScheduleTracker()
    first = sched.snapshot(1, datetime(2022, 1, 2, 0), date(2022, 1, 1), DEN)
    assert (first["rest_days"], first["b2b"], first["3in4"]) == (7, 0, 0)
    assert (first["travel_km"], first["tz_shift"]) == (0, 0)
    sched.add(1, datetime(2022, 1, 2, 0), date(2022, 1, 1), BOS)
    later = sched.snapshot(1, datetime(2022, 1, 12, 0), date(2022, 1, 11), DEN)
    assert (later["rest_days"], later["travel_km"], later["tz_shift"]) == (7, 0, 0)


def test_unknown_venue_gives_missing_travel() -> None:
    sched = ScheduleTracker()
    sched.add(1, datetime(2022, 1, 2, 0), date(2022, 1, 1), BOS)
    f = sched.snapshot(1, datetime(2022, 1, 4, 0), date(2022, 1, 3), None)
    assert f["travel_km"] is None and f["tz_shift"] is None
    assert f["rest_days"] == 2


# Availability


def line(**kw: float) -> dict[str, float]:
    base = dict(pts=0, fgm=0, fga=0, fta=0, ftm=0, oreb=0, dreb=0, stl=0, ast=0, blk=0,
                pf=0, tov=0)
    return {**base, **kw}


def test_game_score_formula() -> None:
    row = line(pts=20, fgm=8, fga=15, fta=4, ftm=3, oreb=2, dreb=5, stl=1, ast=4, blk=1,
               pf=2, tov=3)
    expected = 20 + 0.4 * 8 - 0.7 * 15 - 0.4 * 1 + 0.7 * 2 + 0.3 * 5 + 1 + 0.7 * 4 + 0.7 - 0.8 - 3
    assert game_score(row) == pytest.approx(expected)


def test_tracker_rates_members_and_trades() -> None:
    tracker = PlayerTracker()
    tracker.add_game("2021-22", 1, {10: (30.0, 15.0), 11: (20.0, 4.0)})
    assert tracker.members(1, "2021-22", listed=set()) == {10, 11}
    rate, minutes = tracker.rate(10, "2021-22")
    assert (rate, minutes) == (pytest.approx(0.5), pytest.approx(30.0))
    # Player 11 appears for team 2: he leaves team 1 at once
    tracker.add_game("2021-22", 2, {11: (25.0, 5.0)})
    assert tracker.members(1, "2021-22", listed=set()) == {10}
    assert tracker.members(2, "2021-22", listed=set()) == {11}


def test_ten_straight_misses_drop_a_player_unless_listed() -> None:
    tracker = PlayerTracker()
    tracker.add_game("2021-22", 1, {10: (30.0, 15.0), 11: (20.0, 4.0)})
    for _ in range(10):
        tracker.add_game("2021-22", 1, {10: (30.0, 15.0)})
    assert tracker.members(1, "2021-22", listed=set()) == {10}
    assert tracker.members(1, "2021-22", listed={11}) == {10, 11}


def test_new_season_has_no_members_and_falls_back_to_last_season_rate() -> None:
    tracker = PlayerTracker()
    tracker.add_game("2020-21", 1, {10: (30.0, 15.0)})
    assert tracker.members(1, "2021-22", listed=set()) == set()
    assert tracker.rate(10, "2021-22") == (pytest.approx(0.5), pytest.approx(30.0))
    assert tracker.rate(99, "2021-22") == (0.0, 0.0)
    tracker.add_game("2021-22", 1, {10: (20.0, 4.0)})
    assert tracker.rate(10, "2021-22") == (pytest.approx(0.2), pytest.approx(20.0))
