import json
import math
from pathlib import Path
from typing import Any

import pytest
from scipy.stats import norm

from avaris.ingest.scoreboard import parse_scoreboard
from avaris.traditional.live import clock_minutes, game_minutes, live_update
from avaris.traditional.pregame import (
    B2B_PTS,
    SIGMA_MARGIN,
    SIGMA_TOTAL,
    pregame,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "scoreboard"


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


def test_missing_elo_or_league_total_gives_no_prediction() -> None:
    assert pregame(features(elo_margin=None)) is None
    assert pregame(features(league_total=math.nan)) is None


@pytest.mark.parametrize(("text", "minutes"), [
    ("PT05M23.00S", 5 + 23 / 60), ("PT00M00.00S", 0.0), ("PT12M00.00S", 12.0),
    ("5:23", 5 + 23 / 60), ("", None), ("  ", None),
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
    tied = live_update(pre, home_pts=100, away_pts=100, elapsed=48.0, left=0.0)
    assert ahead.p_home_win > 0.99
    assert ahead.total_mu == pytest.approx(198.0)
    assert tied.p_home_win == pytest.approx(0.5)


def test_parse_live_scoreboard() -> None:
    payload = json.loads((FIXTURES / "scoreboardv3_live.json").read_text())
    games = parse_scoreboard(payload)
    mia = games["0012600003"]
    assert (mia.status, mia.period, mia.home_pts, mia.away_pts) == ("in_progress", 2, 65, 59)
    assert mia.clock == "PT01M27.00S"
    assert mia.label == "2nd Qtr"
    assert games["0012600017"].label == "Halftime"
    assert games["0012600064"].status == "scheduled"


def test_parse_final_scoreboard_with_overtime() -> None:
    payload = json.loads((FIXTURES / "scoreboardv3_final.json").read_text())
    okc = parse_scoreboard(payload)["0012600047"]
    assert (okc.status, okc.period, okc.home_pts, okc.away_pts) == ("final", 5, 114, 112)
    assert okc.regulation_periods == 4


def test_parse_empty_scoreboard() -> None:
    assert parse_scoreboard({"scoreboard": {"games": []}}) == {}
    assert parse_scoreboard({}) == {}
