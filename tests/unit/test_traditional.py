import copy
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest
from scipy.stats import norm

from avaris.ingest.scoreboard import (
    GameKey,
    LiveGame,
    first_live,
    parse_espn_scoreboard,
    parse_scoreboard,
)
from avaris.traditional.live import clock_minutes, game_minutes, live_update
from avaris.traditional.pregame import (
    B2B_PTS,
    INJURY_PTS,
    SIGMA_MARGIN,
    SIGMA_TOTAL,
    pregame,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "scoreboard"
ESPN_FIXTURES = Path(__file__).parents[1] / "fixtures" / "espn"
MIA, BKN, BOS, CHA, LAC, DEN = (1610612748, 1610612751, 1610612738, 1610612766, 1610612746,
                                1610612743)
OKC, UTA = 1610612760, 1610612762
REPORT_TS = datetime(2021, 11, 27, 22, 30)


def features(**overrides: Any) -> dict[str, Any]:
    # League rating 110 (220 points at pace 100); ratings over 10 games each
    row: dict[str, Any] = {
        "elo_margin": 4.0, "league_total": 220.0, "league_pace": 100.0,
        "home_court": 1, "no_fans": 0, "home_b2b": 0, "away_b2b": 0,
        "home_gp": 10, "away_gp": 10,
        "home_ortg_std": 115.0, "home_drtg_std": 108.0, "home_pace_std": 102.0,
        "away_ortg_std": 110.0, "away_drtg_std": 112.0, "away_pace_std": 98.0,
    }
    return {**row, **overrides}


def test_no_games_played_is_elo_and_the_league_total() -> None:
    out = pregame(features(home_gp=0, away_gp=0, home_ortg_std=math.nan,
                           home_drtg_std=None, home_pace_std=None))
    assert out is not None
    assert out.margin_mu == pytest.approx(4.0)
    assert out.total_mu == pytest.approx(220.0)
    assert out.p_home_win == pytest.approx(norm.cdf(4.0 / SIGMA_MARGIN))
    assert out.inputs["eff_margin"] is None
    assert out.inputs["weight"] == 0.0


def test_ratings_blend_with_elo_by_games_played() -> None:
    # Points per 100: home 115 + 112 - 110 = 117, away 110 + 108 - 110 = 108; pace 100
    # eff margin 9 + 2.5 home court; g = 10: w = 0.25 on the margin, 0.5 on the total
    out = pregame(features())
    assert out is not None
    assert out.inputs["eff_margin"] == pytest.approx(11.5)
    assert out.inputs["eff_total"] == pytest.approx(225.0)
    assert out.margin_mu == pytest.approx(0.75 * 4.0 + 0.25 * 11.5)
    assert out.total_mu == pytest.approx(222.5)
    assert out.margin_sigma == SIGMA_MARGIN
    assert out.total_sigma == SIGMA_TOTAL


def test_home_court_is_dropped_on_a_neutral_site_and_halved_without_fans() -> None:
    neutral = pregame(features(home_court=0))
    no_fans = pregame(features(no_fans=1))
    assert neutral is not None and no_fans is not None
    assert neutral.inputs["eff_margin"] == pytest.approx(9.0)
    assert no_fans.inputs["eff_margin"] == pytest.approx(10.25)


def test_back_to_back_costs_points() -> None:
    base = pregame(features())
    home_b2b = pregame(features(home_b2b=1))
    away_b2b = pregame(features(away_b2b=1))
    assert base is not None and home_b2b is not None and away_b2b is not None
    assert home_b2b.margin_mu == pytest.approx(base.margin_mu - B2B_PTS)
    assert away_b2b.margin_mu == pytest.approx(base.margin_mu + B2B_PTS)


def test_injuries_beyond_the_usual_cost_points() -> None:
    # Home misses 20 more than usual (a star newly out), away 5 more
    base = pregame(features())
    out = pregame(features(home_lost_report=30.0, home_lost_usual=10.0,
                           away_lost_report=12.0, away_lost_usual=7.0, report_ts=REPORT_TS))
    assert base is not None and out is not None
    assert out.margin_mu == pytest.approx(base.margin_mu + INJURY_PTS * (5.0 - 20.0))
    assert out.total_mu == pytest.approx(base.total_mu)
    assert out.p_home_win == pytest.approx(norm.cdf(out.margin_mu / SIGMA_MARGIN))
    assert out.inputs["injury"] == pytest.approx(INJURY_PTS * -15.0)
    assert out.inputs["injury_source"] == "report"
    assert out.inputs["home_lost"] == pytest.approx(20.0)
    assert out.inputs["away_lost"] == pytest.approx(5.0)


def test_a_team_missing_less_than_usual_gains_points() -> None:
    base = pregame(features())
    out = pregame(features(home_lost_report=4.0, home_lost_usual=24.0,
                           away_lost_report=10.0, away_lost_usual=10.0, report_ts=REPORT_TS))
    assert base is not None and out is not None
    assert out.margin_mu == pytest.approx(base.margin_mu + INJURY_PTS * 20.0)


def test_without_a_usual_the_whole_report_counts() -> None:
    out = pregame(features(home_lost_report=20.0, home_lost_usual=math.nan,
                           away_lost_report=0.0, away_lost_usual=None, report_ts=REPORT_TS))
    assert out is not None
    assert out.inputs["injury"] == pytest.approx(-INJURY_PTS * 20.0)


def test_preseason_uses_the_espn_list() -> None:
    # No injury report in preseason: the value ESPN lists out, with no usual
    base = pregame(features(home_gp=0, away_gp=0))
    out = pregame(features(home_gp=0, away_gp=0, home_lost_report=math.nan,
                           away_lost_report=math.nan, home_lost_espn=52.5,
                           away_lost_espn=3.3))
    assert base is not None and out is not None
    assert out.margin_mu == pytest.approx(base.margin_mu + INJURY_PTS * (3.3 - 52.5))
    assert out.inputs["injury_source"] == "espn"


@pytest.mark.parametrize("overrides", [
    {},
    {"home_lost_report": 20.0, "away_lost_report": math.nan, "report_ts": REPORT_TS},
    # No report at decision time (a morning before the day's first, or before 2021-22):
    # lost_report reads 0 but nobody is known to be out
    {"home_lost_report": 0.0, "home_lost_usual": 25.0, "away_lost_report": 0.0,
     "away_lost_usual": 5.0, "report_ts": None},
    {"home_lost_report": 0.0, "away_lost_report": 0.0, "report_ts": pd.NaT},
    {"home_lost_espn": 20.0, "away_lost_espn": None},
])
def test_no_injury_term_unless_both_teams_are_known(overrides: dict[str, Any]) -> None:
    base = pregame(features())
    out = pregame(features(**overrides))
    assert base is not None and out is not None
    assert out.margin_mu == pytest.approx(base.margin_mu)
    assert out.inputs["injury"] == 0.0
    assert out.inputs["injury_source"] is None


def test_missing_elo_or_league_total_gives_no_prediction() -> None:
    assert pregame(features(elo_margin=None)) is None
    assert pregame(features(league_total=math.nan)) is None


@pytest.mark.parametrize(("text", "minutes"), [
    ("PT05M23.00S", 5 + 23 / 60), ("PT00M00.00S", 0.0), ("PT12M00.00S", 12.0),
    ("5:23", 5 + 23 / 60), ("PT5S", 5 / 60), ("", None), ("  ", None), ("PT", None),
])
def test_clock_minutes(text: str, minutes: float | None) -> None:
    got = clock_minutes(text)
    assert got == pytest.approx(minutes) if minutes is not None else got is None


def test_game_minutes_in_regulation_and_overtime() -> None:
    # (elapsed, left)
    assert game_minutes(1, 12.0) == (0.0, 48.0)
    assert game_minutes(3, 5.0) == pytest.approx((31.0, 17.0))
    assert game_minutes(4, 0.0) == (48.0, 0.0)
    assert game_minutes(5, 2.0) == pytest.approx((51.0, 2.0))
    assert game_minutes(0, None) == (0.0, 48.0)


def test_live_update_before_tip_is_the_pregame_line() -> None:
    pre = pregame(features())
    assert pre is not None
    out = live_update(pre, home_pts=0, away_pts=0, elapsed=0.0, left=48.0)
    assert out.margin_mu == pytest.approx(pre.margin_mu)
    assert out.margin_sigma == pytest.approx(pre.margin_sigma)
    assert out.total_mu == pytest.approx(pre.total_mu)
    assert out.p_home_win == pytest.approx(pre.p_home_win)


def test_live_update_at_halftime() -> None:
    pre = pregame(features(home_gp=0, away_gp=0))  # margin 4, total 220
    assert pre is not None
    out = live_update(pre, home_pts=60, away_pts=50, elapsed=24.0, left=24.0)
    assert out.margin_mu == pytest.approx(10 + 4 * 0.5)
    assert out.margin_sigma == pytest.approx(SIGMA_MARGIN * math.sqrt(0.5))
    assert out.p_home_win == pytest.approx(norm.cdf(12 / (SIGMA_MARGIN * math.sqrt(0.5))))
    # Rate: half pregame (220 / 48), half observed (110 / 24)
    rate = 0.5 * 220 / 48 + 0.5 * 110 / 24
    assert out.total_mu == pytest.approx(110 + rate * 24)
    assert out.total_sigma == pytest.approx(SIGMA_TOTAL * math.sqrt(0.5))


def test_live_update_at_the_buzzer() -> None:
    pre = pregame(features())
    assert pre is not None
    ahead = live_update(pre, home_pts=100, away_pts=98, elapsed=48.0, left=0.0)
    assert ahead.p_home_win == 1.0
    assert ahead.total_mu == pytest.approx(198.0)
    # The spread never shrinks below 30 s of play
    floor = math.sqrt(0.5 / 48)
    assert ahead.margin_sigma == pytest.approx(SIGMA_MARGIN * floor)
    assert ahead.total_sigma == pytest.approx(SIGMA_TOTAL * floor)


def test_tie_at_the_buzzer_plays_an_overtime() -> None:
    pre = pregame(features())
    assert pre is not None
    tied = live_update(pre, home_pts=100, away_pts=100, elapsed=48.0, left=0.0)
    share = 5 / 48
    assert tied.margin_mu == pytest.approx(pre.margin_mu * share)
    assert tied.margin_sigma == pytest.approx(SIGMA_MARGIN * math.sqrt(share))
    assert 0.5 < tied.p_home_win < pre.p_home_win
    assert tied.total_mu > 200 + 15


def test_live_update_in_overtime() -> None:
    # Overtime minutes count against a 48-minute game, not the minutes played so far
    pre = pregame(features(home_gp=0, away_gp=0))  # margin 4, total 220
    assert pre is not None
    elapsed, left = game_minutes(5, 3.0)
    assert (elapsed, left) == pytest.approx((50.0, 3.0))
    out = live_update(pre, home_pts=104, away_pts=102, elapsed=elapsed, left=left)
    assert out.margin_mu == pytest.approx(2 + 4 * 3 / 48)
    assert out.margin_sigma == pytest.approx(SIGMA_MARGIN * math.sqrt(3 / 48))
    weight = 50 / (50 + 24)
    rate = (1 - weight) * 220 / 48 + weight * 206 / 50
    assert out.total_mu == pytest.approx(206 + rate * 3)


def test_parse_live_scoreboard() -> None:
    payload = json.loads((FIXTURES / "scoreboardv3_live.json").read_text())
    games = parse_scoreboard(payload)
    mia = games[(MIA, BKN)]
    assert (mia.status, mia.period, mia.home_pts, mia.away_pts) == ("in_progress", 2, 65, 59)
    assert mia.clock == pytest.approx(1 + 27 / 60)
    assert mia.label == "2nd Qtr"
    halftime = games[(BOS, CHA)]
    assert (halftime.label, halftime.clock) == ("Halftime", 0.0)
    assert games[(LAC, DEN)].status == "scheduled"


def test_parse_final_scoreboard_with_overtime() -> None:
    payload = json.loads((FIXTURES / "scoreboardv3_final.json").read_text())
    okc = next(g for g in parse_scoreboard(payload).values() if g.period == 5)
    assert (okc.status, okc.home_pts, okc.away_pts) == ("final", 114, 112)
    assert okc.regulation_periods == 4


def test_parse_empty_scoreboard() -> None:
    assert parse_scoreboard({"scoreboard": {"games": []}}) == {}
    assert parse_scoreboard({}) == {}


def espn(name: str) -> dict[str, Any]:
    return json.loads((ESPN_FIXTURES / name).read_text())


def test_parse_live_espn_scoreboard() -> None:
    # Recorded 2026-10-14 22:55 ET: DEN @ LAC in the 1st, six games final
    games = parse_espn_scoreboard(espn("scoreboard_live.json"))
    assert len(games) == 7
    den = games[(LAC, DEN)]
    assert (den.status, den.label, den.period, den.home_pts, den.away_pts) == (
        "in_progress", "1st Qtr", 1, 6, 15)
    assert den.clock == pytest.approx(5 + 21 / 60)
    assert den.regulation_periods == 4
    mia = games[(MIA, BKN)]
    assert (mia.status, mia.label, mia.home_pts, mia.away_pts) == ("final", "Final", 144, 128)


def test_parse_espn_final_in_overtime() -> None:
    # Recorded 2026-01-07: UTAH @ OKC went to overtime
    okc = parse_espn_scoreboard(espn("scoreboard_final_ot.json"))[(OKC, UTA)]
    assert (okc.status, okc.label, okc.period, okc.home_pts, okc.away_pts) == (
        "final", "Final/OT", 5, 129, 125)


def test_parse_espn_end_of_quarter() -> None:
    # Recorded 2026-10-14 23:08 ET: DEN @ LAC tied after one
    den = parse_espn_scoreboard(espn("scoreboard_end_period.json"))[(LAC, DEN)]
    assert (den.status, den.label, den.period, den.clock) == (
        "in_progress", "End of 1st Qtr", 1, 0.0)
    assert (den.home_pts, den.away_pts) == (24, 24)


def espn_status(period: int, clock: float, name: str, state: str = "in",
                completed: bool = False) -> LiveGame:
    # The live DEN @ LAC event with its status replaced
    payload = espn("scoreboard_live.json")
    event = copy.deepcopy(next(e for e in payload["events"] if e["id"] == "401918011"))
    event["competitions"][0]["status"] = {
        "clock": clock, "period": period,
        "type": {"name": name, "state": state, "completed": completed, "shortDetail": "TBD"},
    }
    return parse_espn_scoreboard({"events": [event]})[(LAC, DEN)]


@pytest.mark.parametrize(("period", "clock", "name", "label"), [
    (2, 0.0, "STATUS_HALFTIME", "Halftime"),
    (3, 0.0, "STATUS_END_PERIOD", "End of 3rd Qtr"),
    (4, 0.0, "STATUS_END_PERIOD", "End of 4th Qtr"),
    (5, 154.0, "STATUS_IN_PROGRESS", "OT"),
    (6, 0.0, "STATUS_END_PERIOD", "End of 2OT"),
])
def test_espn_labels_read_like_the_nba_scoreboard(
    period: int, clock: float, name: str, label: str,
) -> None:
    game = espn_status(period, clock, name)
    assert (game.status, game.label, game.period) == ("in_progress", label, period)
    assert game.clock == pytest.approx(clock / 60)


def test_espn_postponed_game_is_not_final() -> None:
    game = espn_status(0, 0.0, "STATUS_POSTPONED", state="post")
    assert game.status == "scheduled"


def test_espn_double_overtime_final() -> None:
    game = espn_status(6, 0.0, "STATUS_FINAL", state="post", completed=True)
    assert (game.status, game.label) == ("final", "Final/2OT")


def test_espn_skips_a_club_outside_the_nba() -> None:
    payload = espn("scoreboard_live.json")
    payload["events"][0]["competitions"][0]["competitors"][0]["team"]["displayName"] = "Real Madrid"
    assert len(parse_espn_scoreboard(payload)) == 6
    assert parse_espn_scoreboard({}) == {}


DAY = date(2026, 10, 14)
GAME = LiveGame("in_progress", "1st Qtr", 1, 5.35, 4, 6, 15)


class Source:
    def __init__(self, games: dict[GameKey, LiveGame] | Exception) -> None:
        self.games = games
        self.calls = 0

    def __call__(self, day: date) -> dict[GameKey, LiveGame]:
        self.calls += 1
        if isinstance(self.games, Exception):
            raise self.games
        return self.games


def test_first_live_uses_the_primary_feed_alone() -> None:
    primary, fallback = Source({(LAC, DEN): GAME}), Source({})
    assert first_live(primary, fallback)(DAY) == {(LAC, DEN): GAME}
    assert fallback.calls == 0


def test_first_live_falls_back_on_a_failed_or_empty_feed() -> None:
    games = {(LAC, DEN): GAME}
    assert first_live(Source(httpx.ConnectTimeout("espn")), Source(games))(DAY) == games
    assert first_live(Source({}), Source(games))(DAY) == games


def test_first_live_raises_only_when_no_feed_answers() -> None:
    assert first_live(Source({}), Source(RuntimeError("blocked")))(DAY) == {}
    with pytest.raises(RuntimeError, match="blocked"):
        first_live(Source(httpx.ConnectTimeout("espn")), Source(RuntimeError("blocked")))(DAY)
