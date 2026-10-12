from typing import Any

import pandas as pd

from avaris.seasons import season_type_from_game_id

STAT_COLUMNS = {
    "PTS": "pts", "FGM": "fgm", "FGA": "fga", "FG3M": "fg3m", "FG3A": "fg3a", "FTM": "ftm",
    "FTA": "fta", "OREB": "oreb", "DREB": "dreb", "REB": "reb", "AST": "ast", "STL": "stl",
    "BLK": "blk", "TOV": "tov", "PF": "pf",
}

TEAM_GAME_COLUMNS = [
    "game_id", "team_id", "opp_team_id", "is_home", "season", "season_type", "game_date_et",
    "wl", "minutes", *STAT_COLUMNS.values(), "plus_minus",
]
PLAYER_GAME_COLUMNS = [
    "game_id", "player_id", "team_id", "player_name", "season", "season_type", "game_date_et",
    "minutes", *STAT_COLUMNS.values(), "plus_minus",
]
ROSTER_COLUMNS = ["season", "team_id", "player_id", "player_name", "position", "how_acquired"]


def result_frame(payload: dict[str, Any], index: int = 0) -> pd.DataFrame:
    result = payload["resultSets"][index]
    return pd.DataFrame(result["rowSet"], columns=result["headers"])


def _minutes(value: Any) -> float | None:
    # Older responses report minutes as "MM:SS"
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str):
        mins, _, secs = value.partition(":")
        return int(mins) + (int(secs) / 60 if secs else 0)
    return float(value)


def _common(raw: pd.DataFrame, season: str) -> pd.DataFrame:
    df = pd.DataFrame({
        "game_id": raw["GAME_ID"].astype(str),
        "team_id": raw["TEAM_ID"].astype(int),
        "season": season,
        "season_type": raw["GAME_ID"].map(season_type_from_game_id),
        "game_date_et": pd.to_datetime(raw["GAME_DATE"]).dt.date,
        "minutes": raw["MIN"].map(_minutes).astype("Float64"),
    })
    for src, dst in STAT_COLUMNS.items():
        df[dst] = raw[src].astype("Int64")
    df["plus_minus"] = raw["PLUS_MINUS"].astype("Float64")
    return df


def parse_team_log(payload: dict[str, Any], season: str) -> pd.DataFrame:
    raw = result_frame(payload)
    if not raw.empty:
        # Cancelled games (BOS-IND, Apr 2013) are listed with no result and 0 minutes
        raw = raw[raw["WL"].notna()].reset_index(drop=True)
    if raw.empty:
        return pd.DataFrame(columns=TEAM_GAME_COLUMNS)
    df = _common(raw, season)
    df["is_home"] = raw["MATCHUP"].str.contains(" vs. ", regex=False)
    df["wl"] = raw["WL"]
    opponents = df[["game_id", "team_id"]].rename(columns={"team_id": "opp_team_id"})
    df = df.merge(opponents, on="game_id", how="left")
    df = df[df["team_id"] != df["opp_team_id"]]
    df["opp_team_id"] = df["opp_team_id"].astype("Int64")
    return df[TEAM_GAME_COLUMNS].reset_index(drop=True)


def parse_player_log(payload: dict[str, Any], season: str) -> pd.DataFrame:
    raw = result_frame(payload)
    if raw.empty:
        return pd.DataFrame(columns=PLAYER_GAME_COLUMNS)
    df = _common(raw, season)
    df["player_id"] = raw["PLAYER_ID"].astype(int)
    df["player_name"] = raw["PLAYER_NAME"]
    return df[PLAYER_GAME_COLUMNS]


def parse_roster(payload: dict[str, Any], season: str, team_id: int) -> pd.DataFrame:
    raw = result_frame(payload)
    if raw.empty:
        return pd.DataFrame(columns=ROSTER_COLUMNS)
    return pd.DataFrame({
        "season": season,
        "team_id": team_id,
        "player_id": raw["PLAYER_ID"].astype(int),
        "player_name": raw["PLAYER"],
        "position": raw.get("POSITION"),
        "how_acquired": raw.get("HOW_ACQUIRED"),
    })[ROSTER_COLUMNS]
