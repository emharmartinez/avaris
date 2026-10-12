from datetime import date

import pandas as pd

from avaris.ingest.nba_stats import parse_player_log, parse_roster, parse_team_log
from tests.conftest import load_stats_fixture, records_by

PHX = 1610612756
ORL = 1610612753


def team_log(name: str) -> pd.DataFrame:
    return parse_team_log(load_stats_fixture("leaguegamelog", name), name[:7])


def test_team_log_home_away_and_opponent() -> None:
    log = records_by(team_log("2019-20_Regular-Season_T"), "game_id", "team_id")
    phx = log[("0021900573", PHX)]
    orl = log[("0021900573", ORL)]
    assert phx["is_home"]
    assert not orl["is_home"]
    assert phx["opp_team_id"] == ORL
    assert orl["opp_team_id"] == PHX
    assert (phx["pts"], orl["pts"]) == (98, 94)
    assert phx["wl"] == "W"
    assert phx["game_date_et"] == date(2020, 1, 10)
    assert phx["season"] == "2019-20"
    assert phx["season_type"] == "regular"


def test_team_log_stat_columns() -> None:
    row = team_log("2019-20_Regular-Season_T").iloc[0]
    for col in ("minutes", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "reb",
                "ast", "stl", "blk", "tov", "pf", "plus_minus"):
        assert col in row.index, col
    assert row["minutes"] >= 240


def test_season_type_comes_from_game_id() -> None:
    log = team_log("2025-26_IST_T")
    by_game = dict(zip(log["game_id"], log["season_type"], strict=False))
    assert by_game["0062500001"] == "cup_final"
    assert by_game["0022501201"] == "regular"


def test_player_log() -> None:
    payload = load_stats_fixture("leaguegamelog", "2019-20_Regular-Season_P")
    log = parse_player_log(payload, "2019-20")
    assert {"game_id", "player_id", "team_id", "player_name", "minutes", "pts"} <= set(log.columns)
    assert log.set_index(["game_id", "player_id"]).index.is_unique
    assert (log["minutes"] >= 0).all()
    assert log["player_id"].dtype.kind == "i"


def test_player_minutes_accept_clock_strings() -> None:
    payload = load_stats_fixture("leaguegamelog", "2019-20_Regular-Season_P")
    result = payload["resultSets"][0]
    result["rowSet"][0][result["headers"].index("MIN")] = "34:30"
    assert parse_player_log(payload, "2019-20")["minutes"].iloc[0] == 34.5


def test_roster_uses_requested_team() -> None:
    payload = load_stats_fixture("commonteamroster", "2025-26")
    roster = parse_roster(payload, "2025-26", 1610612759)
    assert len(roster) == 4
    assert (roster["team_id"] == 1610612759).all()
    assert (roster["season"] == "2025-26").all()
    assert {"player_id", "player_name", "position", "how_acquired"} <= set(roster.columns)


def test_unplayed_games_are_dropped_from_team_log() -> None:
    # The cancelled 2013 BOS-IND game is listed with 0 minutes and no W/L
    payload = load_stats_fixture("leaguegamelog", "2019-20_Regular-Season_T")
    result = payload["resultSets"][0]
    headers = result["headers"]
    for template in result["rowSet"][:2]:
        row = list(template)
        row[headers.index("GAME_ID")] = "0021901999"
        row[headers.index("WL")] = None
        row[headers.index("MIN")] = 0
        result["rowSet"].append(row)
    log = parse_team_log(payload, "2019-20")
    assert "0021901999" not in set(log["game_id"])
    assert len(log) == len(result["rowSet"]) - 2
