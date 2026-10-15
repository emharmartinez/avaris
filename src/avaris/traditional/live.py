import math
import re

from avaris.traditional.pregame import Line, win_probability

# In-game update of the pregame line (ADR-024): the lead plus the pregame margin over the
# minutes left, with the spread shrinking as sqrt(minutes left) (Stern's Brownian motion)
GAME_MINUTES = 48.0
QUARTER_MINUTES = 12.0
OVERTIME_MINUTES = 5.0
MIN_LEFT = 0.5  # the spread never shrinks below 30 s worth of play
PACE_PRIOR_MINUTES = 24.0  # minutes played at which the observed scoring rate gets half weight

ISO_CLOCK = re.compile(r"^PT(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$")
PLAIN_CLOCK = re.compile(r"^(\d+):(\d+(?:\.\d+)?)$")


def clock_minutes(text: str | None) -> float | None:
    # Minutes left in the period: scoreboardv3 sends PT05M23.00S, empty when not running
    text = (text or "").strip()
    match = ISO_CLOCK.match(text) or PLAIN_CLOCK.match(text)
    if not text or match is None:
        return None
    minutes, seconds = match.groups()
    return float(minutes or 0) + float(seconds or 0) / 60


def format_clock(minutes: float | None) -> str | None:
    if minutes is None:
        return None
    seconds = math.ceil(round(minutes * 60, 3))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _period_minutes(period: int, regulation_periods: int) -> float:
    return QUARTER_MINUTES if period <= regulation_periods else OVERTIME_MINUTES


def game_minutes(
    period: int, clock: float | None, regulation_periods: int = 4
) -> tuple[float, float]:
    # (minutes played, minutes left); before the tip the whole game is left
    if period < 1:
        return 0.0, GAME_MINUTES
    in_period = _period_minutes(period, regulation_periods)
    left_in_period = in_period if clock is None else min(clock, in_period)
    played = sum(_period_minutes(p, regulation_periods) for p in range(1, period + 1))
    played -= left_in_period
    later = sum(QUARTER_MINUTES for _ in range(period + 1, regulation_periods + 1))
    return played, left_in_period + later


def live_update(pre: Line, home_pts: int, away_pts: int, elapsed: float, left: float) -> Line:
    share_left = left / GAME_MINUTES
    shrink = math.sqrt(max(left, MIN_LEFT) / GAME_MINUTES)
    margin_mu = home_pts - away_pts + pre.margin_mu * share_left
    margin_sigma = pre.margin_sigma * shrink
    # Settled at the buzzer: a lead wins outright, a tie goes to overtime
    p_home_win = win_probability(margin_mu, margin_sigma if left > 0 else 0.0)
    observed = (home_pts + away_pts) / elapsed if elapsed > 0 else 0.0
    weight = elapsed / (elapsed + PACE_PRIOR_MINUTES)
    rate = (1 - weight) * pre.total_mu / GAME_MINUTES + weight * observed
    total_mu = home_pts + away_pts + rate * left
    return Line(p_home_win, margin_mu, margin_sigma, total_mu, pre.total_sigma * shrink)
