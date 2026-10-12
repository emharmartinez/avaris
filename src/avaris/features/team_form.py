from collections import deque
from collections.abc import Mapping

FORM_HALF_LIFE = 10.0  # games
LAST_N = 10
CARRY_KEEP = 0.3  # share of last season's EW weight kept at a new season
PRIOR_GAMES = 5.0  # league-average games blended in at a new season


def possessions(team: Mapping[str, float], opp: Mapping[str, float]) -> float:
    def one(row: Mapping[str, float]) -> float:
        return row["fga"] + 0.44 * row["fta"] - row["oreb"] + row["tov"]

    return (one(team) + one(opp)) / 2


def game_ratings(
    team: Mapping[str, float], opp: Mapping[str, float]
) -> tuple[float, float, float]:
    # Offensive and defensive rating per 100 possessions, and pace per 48 minutes
    poss = possessions(team, opp)
    pace = poss * 48 / (team["minutes"] / 5)
    return 100 * team["pts"] / poss, 100 * opp["pts"] / poss, pace


class EwMean:
    def __init__(self, half_life: float) -> None:
        self.decay = 0.5 ** (1 / half_life)
        self.sum_x = 0.0
        self.sum_w = 0.0

    def add(self, x: float) -> None:
        self.sum_x = self.decay * self.sum_x + x
        self.sum_w = self.decay * self.sum_w + 1

    @property
    def value(self) -> float | None:
        return self.sum_x / self.sum_w if self.sum_w > 0 else None

    def regressed(self, keep: float, prior: float, prior_weight: float) -> "EwMean":
        out = EwMean(1.0)
        out.decay = self.decay
        out.sum_x = keep * self.sum_x + prior_weight * prior
        out.sum_w = keep * self.sum_w + prior_weight
        return out


class TeamForm:
    # Exponentially weighted ORtg, DRtg and pace (carried across seasons with regression
    # toward the league), plus this season's last-N net rating and games played
    def __init__(self) -> None:
        self.season = ""
        self.ortg = EwMean(FORM_HALF_LIFE)
        self.drtg = EwMean(FORM_HALF_LIFE)
        self.pace = EwMean(FORM_HALF_LIFE)
        self.last_net: deque[float] = deque(maxlen=LAST_N)
        self.gp = 0

    def _state(
        self, season: str, league_rtg: float | None, league_pace: float | None
    ) -> tuple[EwMean, EwMean, EwMean, deque[float], int]:
        if not self.season or self.season >= season:
            return self.ortg, self.drtg, self.pace, self.last_net, self.gp

        def regress(ew: EwMean, prior: float | None) -> EwMean:
            if prior is None:
                return ew.regressed(1.0, 0.0, 0.0)
            return ew.regressed(CARRY_KEEP, prior, PRIOR_GAMES)

        return (
            regress(self.ortg, league_rtg),
            regress(self.drtg, league_rtg),
            regress(self.pace, league_pace),
            deque(maxlen=LAST_N),
            0,
        )

    def add(
        self,
        season: str,
        ortg: float,
        drtg: float,
        pace: float,
        league_rtg: float | None = None,
        league_pace: float | None = None,
    ) -> None:
        self.ortg, self.drtg, self.pace, self.last_net, self.gp = self._state(
            season, league_rtg, league_pace
        )
        self.season = season
        self.ortg.add(ortg)
        self.drtg.add(drtg)
        self.pace.add(pace)
        self.last_net.append(ortg - drtg)
        self.gp += 1

    def snapshot(
        self, season: str, league_rtg: float | None, league_pace: float | None
    ) -> dict[str, float | None]:
        ortg, drtg, pace, last_net, gp = self._state(season, league_rtg, league_pace)
        o, d = ortg.value, drtg.value
        return {
            "ortg": o,
            "drtg": d,
            "net": o - d if o is not None and d is not None else None,
            "pace": pace.value,
            "net_l10": sum(last_net) / len(last_net) if last_net else None,
            "gp": gp,
        }
