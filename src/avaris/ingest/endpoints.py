from datetime import date

# stats.nba.com SeasonType values pulled per season; IST is only used for the Cup final ("006")
LOG_SEASON_TYPES = ("Regular Season", "Playoffs", "PlayIn", "IST")
# Preseason player logs go to their own table, never player_games (ADR-022)
PRESEASON_LOG_TYPE = "Pre Season"
FIRST_PLAY_IN_SEASON = "2019-20"  # the 2020 bubble had one play-in game
FIRST_CUP_SEASON = "2023-24"

SCHEDULE = "scheduleleaguev2"
GAME_LOG = "leaguegamelog"
ROSTER = "commonteamroster"


def schedule_params(season: str) -> dict[str, str]:
    return {"LeagueID": "00", "Season": season}


def game_log_params(
    season: str, season_type: str, player_or_team: str, date_from: date | None = None
) -> dict[str, str]:
    return {
        "Counter": "0",
        "DateFrom": date_from.strftime("%m/%d/%Y") if date_from else "",
        "DateTo": "",
        "Direction": "ASC",
        "LeagueID": "00",
        "PlayerOrTeam": player_or_team,
        "Season": season,
        "SeasonType": season_type,
        "Sorter": "DATE",
    }


def roster_params(season: str, team_id: int) -> dict[str, str]:
    return {"LeagueID": "00", "Season": season, "TeamID": str(team_id)}


def log_season_types(season: str) -> list[str]:
    types = ["Regular Season", "Playoffs"]
    if season >= FIRST_PLAY_IN_SEASON:
        types.append("PlayIn")
    if season >= FIRST_CUP_SEASON:
        types.append("IST")
    return types
