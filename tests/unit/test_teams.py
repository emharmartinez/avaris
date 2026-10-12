from zoneinfo import ZoneInfo

from avaris.ingest.teams import Venues, load_teams

LAL = 1610612747
LAC = 1610612746
SAS = 1610612759
TOR = 1610612761
CHA = 1610612766


def test_thirty_teams_with_unique_ids_and_tricodes() -> None:
    teams = load_teams()
    assert len(teams) == 30
    assert teams["team_id"].is_unique
    assert teams["tricode"].is_unique
    assert set(teams["team_id"]) == set(range(1610612737, 1610612767))


def test_every_team_has_a_home_arena() -> None:
    venues = Venues.load()
    for team_id in load_teams()["team_id"]:
        assert venues.home_arenas(int(team_id)), team_id


def test_venue_coordinates_and_timezones_are_valid() -> None:
    venues = Venues.load()
    for row in venues.all_rows():
        assert -90 <= row.lat <= 90
        assert -180 <= row.lon <= 180
        ZoneInfo(row.tz)


def test_home_arena_is_not_neutral() -> None:
    venues = Venues.load()
    assert not venues.is_neutral("Crypto.com Arena", LAL, flagged=False)
    assert not venues.is_neutral("Crypto.com Arena", LAC, flagged=False)
    assert not venues.is_neutral("Moody Center", SAS, flagged=False)
    assert not venues.is_neutral("Amalie Arena", TOR, flagged=False)


def test_bubble_and_international_games_are_neutral() -> None:
    venues = Venues.load()
    assert venues.is_neutral("AdventHealth Arena", LAL, flagged=False)
    assert venues.is_neutral("AccorHotels Arena", CHA, flagged=False)
    assert venues.is_neutral("T-Mobile Arena", LAL, flagged=False)


def test_schedule_flag_wins() -> None:
    assert Venues.load().is_neutral("Crypto.com Arena", LAL, flagged=True)


def test_another_teams_arena_is_neutral() -> None:
    assert Venues.load().is_neutral("TD Garden", LAL, flagged=False)


def test_lookup_finds_home_and_neutral_venues() -> None:
    venues = Venues.load()
    home = venues.lookup("Moody Center", SAS)
    assert home is not None
    assert home.city == "Austin"
    neutral = venues.lookup("HP Field House", LAL)
    assert neutral is not None
    assert neutral.kind == "bubble"
    assert venues.lookup("Rupp Arena", SAS) is None


def test_blank_venue_is_not_neutral_unless_flagged() -> None:
    venues = Venues.load()
    assert not venues.is_neutral("", LAL, flagged=False)
    assert venues.is_neutral("", LAL, flagged=True)
