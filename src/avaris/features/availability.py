from collections.abc import Mapping
from dataclasses import dataclass

AVAIL_HALF_LIFE = 10.0  # games
OFF_ROSTER_MISSES = 10  # straight team games missed without an injury-report entry
# Absence weight by injury-report status at decision_ts
REPORT_ABSENCE = {"out": 1.0, "doubtful": 1.0, "questionable": 0.5}


def game_score(row: Mapping[str, float]) -> float:
    return (
        row["pts"] + 0.4 * row["fgm"] - 0.7 * row["fga"] - 0.4 * (row["fta"] - row["ftm"])
        + 0.7 * row["oreb"] + 0.3 * row["dreb"] + row["stl"] + 0.7 * row["ast"]
        + 0.7 * row["blk"] - 0.4 * row["pf"] - row["tov"]
    )


@dataclass
class _Player:
    season: str
    team_id: int
    sum_score: float = 0.0  # decay-weighted Game Score, minutes and games this season
    sum_min: float = 0.0
    sum_w: float = 0.0
    misses: int = 0
    prev_rate: float = 0.0  # last season's rate and expected minutes
    prev_minutes: float = 0.0

    def rate(self) -> tuple[float, float]:
        if self.sum_min <= 0:
            return 0.0, 0.0
        return self.sum_score / self.sum_min, self.sum_min / self.sum_w


class PlayerTracker:
    # Per-minute Game Score (decay-weighted) and expected minutes per player, and each
    # team's current player set: a player belongs to the team he last played for this
    # season until he misses OFF_ROSTER_MISSES straight games with no report entry
    def __init__(self) -> None:
        self.decay = 0.5 ** (1 / AVAIL_HALF_LIFE)
        self._players: dict[int, _Player] = {}

    def rate(self, player_id: int, season: str) -> tuple[float, float]:
        # This season's rate, else last season's, else zero
        p = self._players.get(player_id)
        if p is None:
            return 0.0, 0.0
        if p.season > season:
            return 0.0, 0.0
        return p.rate() if p.sum_min > 0 else (p.prev_rate, p.prev_minutes)

    def members(self, team_id: int, season: str, listed: set[int]) -> set[int]:
        return {
            pid for pid, p in self._players.items()
            if p.season == season and p.team_id == team_id
            and (p.misses < OFF_ROSTER_MISSES or pid in listed)
        }

    def add_game(
        self, season: str, team_id: int, played: Mapping[int, tuple[float, float]]
    ) -> None:
        # played: player_id -> (minutes, Game Score) for players with minutes > 0
        for pid in self.members(team_id, season, listed=set()) - played.keys():
            self._players[pid].misses += 1
        for pid, (minutes, score) in played.items():
            p = self._players.get(pid)
            if p is None:
                p = self._players[pid] = _Player(season, team_id)
            elif p.season != season:
                if p.sum_min > 0:
                    p.prev_rate, p.prev_minutes = p.rate()
                p.season, p.sum_score, p.sum_min, p.sum_w = season, 0.0, 0.0, 0.0
            p.team_id = team_id
            p.misses = 0
            p.sum_score = self.decay * p.sum_score + score
            p.sum_min = self.decay * p.sum_min + minutes
            p.sum_w = self.decay * p.sum_w + 1
