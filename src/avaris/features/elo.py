# 538-style Elo: margin-of-victory multiplier, home advantage, carryover between seasons
ELO_INIT = 1500.0
ELO_MEAN = 1505.0
ELO_K = 20.0
ELO_HCA = 100.0
ELO_CARRYOVER = 0.75
ELO_POINTS_PER_MARGIN = 28.0
NO_FANS_HCA_FACTOR = 0.5  # 2020-21: no or few fans
# Elo updates on these season types only (not preseason, not the NBA Cup final)
ELO_SEASON_TYPES = frozenset({"regular", "play_in", "playoffs"})


def win_prob(diff: float) -> float:
    # diff = home Elo - away Elo + home advantage
    return 1 / (1 + 10 ** (-diff / 400))


def expected_margin(diff: float) -> float:
    return diff / ELO_POINTS_PER_MARGIN


def home_advantage(home_court: int, no_fans: int) -> float:
    return ELO_HCA * home_court * (NO_FANS_HCA_FACTOR if no_fans else 1.0)


def carry_over(elo: float) -> float:
    return ELO_CARRYOVER * elo + (1 - ELO_CARRYOVER) * ELO_MEAN


def mov_multiplier(margin: int, winner_diff: float) -> float:
    return (abs(margin) + 3) ** 0.8 / (7.5 + 0.006 * winner_diff)


class EloRatings:
    def __init__(self) -> None:
        self._ratings: dict[int, tuple[str, float]] = {}  # team -> (season, rating)

    def rating(self, team_id: int, season: str) -> float:
        # A team's first look at a new season sees the carried-over rating
        last_season, elo = self._ratings.get(team_id, (season, ELO_INIT))
        return carry_over(elo) if last_season < season else elo

    def update(
        self, home_id: int, away_id: int, season: str, home_pts: int, away_pts: int, hca: float
    ) -> None:
        home, away = self.rating(home_id, season), self.rating(away_id, season)
        diff = home - away + hca
        margin = home_pts - away_pts
        winner_diff = diff if margin > 0 else -diff
        shift = ELO_K * mov_multiplier(margin, winner_diff) * ((margin > 0) - win_prob(diff))
        self._ratings[home_id] = (season, home + shift)
        self._ratings[away_id] = (season, away - shift)

