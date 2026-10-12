from datetime import date, datetime

import pandas as pd
import pytest

from avaris.ingest.nba_schedule import parse_schedule
from avaris.ingest.teams import Venues
from tests.conftest import load_stats_fixture, records_by


@pytest.fixture(scope="module")
def venues() -> Venues:
    return Venues.load()


def parse(season: str, venues: Venues) -> pd.DataFrame:
    return parse_schedule(load_stats_fixture("scheduleleaguev2", season), season, venues).set_index(
        "game_id"
    )


def test_all_star_games_are_dropped(venues: Venues) -> None:
    games = parse("2019-20", venues)
    assert "0031900001" not in games.index
    assert len(games) == 6


def test_season_types(venues: Venues) -> None:
    games = parse("2019-20", venues)
    assert games.loc["0021900573", "season_type"] == "regular"
    assert games.loc["0041900111", "season_type"] == "playoffs"
    assert games.loc["0051900111", "season_type"] == "play_in"
    cup = parse("2025-26", venues)
    assert cup.loc["0012500008", "season_type"] == "preseason"
    assert cup.loc["0062500001", "season_type"] == "cup_final"
    assert (games["season"] == "2019-20").all()


def test_tip_off_is_naive_utc_and_game_date_is_et(venues: Venues) -> None:
    games = parse("2019-20", venues)
    # 7 pm MST / 9 pm EST Jan 10 = 02:00 UTC Jan 11
    assert games.loc["0021900573", "tip_off_utc"] == datetime(2020, 1, 11, 2, 0)
    assert games.loc["0021900573", "game_date_et"] == date(2020, 1, 10)
    # 10:30 pm EDT tip lands on the next UTC day but the same ET day
    assert games.loc["0021900002", "tip_off_utc"] == datetime(2019, 10, 23, 2, 30)
    assert games.loc["0021900002", "game_date_et"] == date(2019, 10, 22)


def test_teams_scores_status_and_venue(venues: Venues) -> None:
    game = records_by(parse("2019-20", venues).reset_index(), "game_id")["0021900573"]
    assert game["home_team_id"] == 1610612756
    assert game["away_team_id"] == 1610612753
    assert (game["home_pts"], game["away_pts"]) == (98, 94)
    assert game["status"] == "final"
    assert game["venue"] == "Talking Stick Resort Arena"
    assert game["venue_city"] == "Phoenix"


def test_neutral_sites(venues: Venues) -> None:
    games = parse("2019-20", venues)
    assert not games.loc["0021900573", "neutral_site"]
    assert games.loc["0021900669", "neutral_site"]  # Paris
    assert games.loc["0021901232", "neutral_site"]  # bubble seeding
    assert games.loc["0041900111", "neutral_site"]  # bubble playoffs
    assert games.loc["0051900111", "neutral_site"]  # bubble play-in
    recent = parse("2025-26", venues)
    assert not recent.loc["0022500798", "neutral_site"]  # Spurs in Austin
    assert recent.loc["0062500001", "neutral_site"]  # Cup final in Las Vegas


def test_tbd_placeholders_are_skipped_and_scheduled_games_have_no_score(venues: Venues) -> None:
    games = parse("2026-27", venues)
    assert "0022601201" not in games.index
    upcoming = records_by(games.reset_index(), "game_id")["0022600001"]
    assert upcoming["status"] == "scheduled"
    assert pd.isna(upcoming["home_pts"])
    assert upcoming["tip_off_utc"] is not None


def test_midnight_et_means_unknown_tip_off(venues: Venues) -> None:
    payload = load_stats_fixture("scheduleleaguev2", "2019-20")
    game = payload["leagueSchedule"]["gameDates"][0]["games"][0]
    game["gameDateTimeEst"] = game["gameDateEst"]  # T00:00:00Z
    games = parse_schedule(payload, "2019-20", venues).set_index("game_id")
    row = games.loc[game["gameId"]]
    assert pd.isna(row["tip_off_utc"])
    assert row["game_date_et"] == date.fromisoformat(game["gameDateEst"][:10])
