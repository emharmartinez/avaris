import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from scipy.stats import norm

# A rule-based model, no fitting (ADR-024): Elo blended with season-to-date efficiency
# ratings, a fixed home court, back-to-back and injury penalty, and fixed spreads
HOME_COURT_PTS = 2.5
NO_FANS_FACTOR = 0.5  # 2020-21, as in Elo
B2B_PTS = 1.5
# Points of margin per Game Score point a team misses beyond its usual: a star (about 20)
# newly out costs about 3 points
INJURY_PTS = 0.15
PRIOR_GAMES = 10.0  # games at which ratings get half their full weight
MAX_RATINGS_WEIGHT = 0.5  # share of the margin the ratings can take from Elo
# Residual std on the 2015-16 to 2019-20 regular season (12.65, 19.26), to the nearest 0.5
SIGMA_MARGIN = 12.5
SIGMA_TOTAL = 19.5


@dataclass(frozen=True)
class Line:
    p_home_win: float
    margin_mu: float
    margin_sigma: float
    total_mu: float
    total_sigma: float
    inputs: dict[str, Any] = field(default_factory=dict)


def _value(row: Mapping[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)


def win_probability(margin_mu: float, margin_sigma: float) -> float:
    # P(margin > 0); a settled margin (sigma 0) is a win, a loss or a coin flip on a tie
    if margin_sigma <= 0:
        return 0.5 if margin_mu == 0 else float(margin_mu > 0)
    return float(norm.cdf(margin_mu / margin_sigma))


def _efficiency(row: Mapping[str, Any], league_total: float) -> tuple[float, float] | None:
    # Points per 100 = own ORtg + opponent DRtg - league rating; pace adds the same way
    names = [f"{side}_{stat}_std" for side in ("home", "away") for stat in ("ortg", "drtg", "pace")]
    values = [_value(row, name) for name in names]
    league_pace = _value(row, "league_pace")
    if league_pace is None or any(v is None for v in values):
        return None
    h_ortg, h_drtg, h_pace, a_ortg, a_drtg, a_pace = (float(v or 0.0) for v in values)
    league_rtg = 100 * league_total / (2 * league_pace)
    home_per_100 = h_ortg + a_drtg - league_rtg
    away_per_100 = a_ortg + h_drtg - league_rtg
    pace = h_pace + a_pace - league_pace
    home_court = HOME_COURT_PTS * int(row["home_court"]) * (
        NO_FANS_FACTOR if int(row["no_fans"]) else 1.0)
    return pace * (home_per_100 - away_per_100) / 100 + home_court, pace * (
        home_per_100 + away_per_100) / 100


def _injury(row: Mapping[str, Any]) -> tuple[float, float, str] | None:
    # Value each team misses beyond its usual (already in its ratings): the decision report,
    # else (preseason) ESPN's list, which has no usual. None unless both teams are known
    for source in ("report", "espn"):
        lost = [_value(row, f"{side}_lost_{source}") for side in ("home", "away")]
        if None not in lost:
            usual = [(_value(row, f"{side}_lost_usual") if source == "report" else None) or 0.0
                     for side in ("home", "away")]
            return float(lost[0] or 0.0) - usual[0], float(lost[1] or 0.0) - usual[1], source
    return None


def pregame(row: Mapping[str, Any]) -> Line | None:
    # `row` is a features row, point-in-time at decision_ts (ADR-015)
    elo_margin, league_total = _value(row, "elo_margin"), _value(row, "league_total")
    if elo_margin is None or league_total is None:
        return None
    games = min(int(row.get("home_gp") or 0), int(row.get("away_gp") or 0))
    efficiency = _efficiency(row, league_total) if games > 0 else None
    share = games / (games + PRIOR_GAMES) if efficiency is not None else 0.0
    weight = MAX_RATINGS_WEIGHT * share
    eff_margin, eff_total = efficiency or (None, None)
    rest = B2B_PTS * (int(row.get("away_b2b") or 0) - int(row.get("home_b2b") or 0))
    injury = _injury(row)
    home_lost, away_lost, source = injury or (None, None, None)
    injury_pts = 0.0 if injury is None else INJURY_PTS * (injury[1] - injury[0])
    margin = (1 - weight) * elo_margin + weight * (eff_margin or 0.0) + rest + injury_pts
    total = (1 - share) * league_total + share * (eff_total or 0.0)
    inputs = {
        "elo_margin": elo_margin, "eff_margin": eff_margin, "eff_total": eff_total,
        "league_total": league_total, "weight": weight,
        "home_gp": int(row.get("home_gp") or 0), "away_gp": int(row.get("away_gp") or 0),
        "home_b2b": int(row.get("home_b2b") or 0), "away_b2b": int(row.get("away_b2b") or 0),
        "injury": injury_pts, "injury_source": source,
        "home_lost": home_lost, "away_lost": away_lost,
    }
    return Line(win_probability(margin, SIGMA_MARGIN), margin, SIGMA_MARGIN, total,
                SIGMA_TOTAL, inputs)
