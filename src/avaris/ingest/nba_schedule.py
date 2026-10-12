from datetime import date, datetime
from typing import Any

import pandas as pd

from avaris.ingest.teams import Venues
from avaris.seasons import season_type_from_game_id

GAME_COLUMNS = [
    "game_id", "season", "season_type", "game_date_et", "tip_off_utc", "home_team_id",
    "away_team_id", "home_pts", "away_pts", "status", "venue", "venue_city", "neutral_site",
]

STATUS_BY_CODE = {1: "scheduled", 2: "in_progress", 3: "final"}


def _tip_off_utc(game: dict[str, Any]) -> datetime | None:
    # The *Est fields carry a misleading "Z"; a midnight ET time means "not set"
    if game["gameDateTimeEst"].endswith("T00:00:00Z"):
        return None
    return datetime.fromisoformat(game["gameDateTimeUTC"].removesuffix("Z"))


def _score(team: dict[str, Any], status: str) -> int | None:
    return int(team["score"]) if status == "final" and team.get("score") is not None else None


def parse_schedule(payload: dict[str, Any], season: str, venues: Venues) -> pd.DataFrame:
    rows = []
    for game_date in payload["leagueSchedule"]["gameDates"]:
        for game in game_date["games"]:
            season_type = season_type_from_game_id(game["gameId"])
            home, away = game["homeTeam"], game["awayTeam"]
            # Drop All-Star events and Cup/playoff placeholders whose teams are TBD
            if season_type is None or not home["teamId"] or not away["teamId"]:
                continue
            status = STATUS_BY_CODE.get(game["gameStatus"], "scheduled")
            venue = (game.get("arenaName") or "").strip()
            rows.append({
                "game_id": game["gameId"],
                "season": season,
                "season_type": season_type,
                "game_date_et": date.fromisoformat(game["gameDateEst"][:10]),
                "tip_off_utc": _tip_off_utc(game),
                "home_team_id": int(home["teamId"]),
                "away_team_id": int(away["teamId"]),
                "home_pts": _score(home, status),
                "away_pts": _score(away, status),
                "status": status,
                "venue": venue or None,
                "venue_city": (game.get("arenaCity") or "").strip() or None,
                "neutral_site": venues.is_neutral(
                    venue, int(home["teamId"]), bool(game.get("isNeutral"))
                ),
            })
    df = pd.DataFrame(rows, columns=GAME_COLUMNS)
    df["home_pts"] = df["home_pts"].astype("Int64")
    df["away_pts"] = df["away_pts"].astype("Int64")
    # A rescheduled game can appear twice; the last listing is the current one
    return df.drop_duplicates("game_id", keep="last").reset_index(drop=True)
