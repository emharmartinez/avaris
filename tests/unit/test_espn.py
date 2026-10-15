import json
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from avaris.ingest.espn import ESPN_SCOREBOARD_URL, EspnClient, is_out, parse_espn_injuries
from avaris.ingest.stats_client import Throttle

FIXTURE = Path(__file__).parents[1] / "fixtures" / "espn" / "injuries.json"
NYK, TOR, LAC = 1610612752, 1610612761, 1610612746
TIP = datetime(2026, 10, 13, 23, 30)  # Tuesday 7:30 pm ET, naive UTC
WINDOW = 36.0


def payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text())


def test_parse_maps_teams_and_reads_every_entry() -> None:
    df = parse_espn_injuries(payload())
    assert list(df.columns) == ["team_id", "player_name", "status", "comment", "entry_ts"]
    assert len(df) == 10
    assert set(df["team_id"]) == {NYK, TOR, LAC}
    brunson = df[df["player_name"] == "Jalen Brunson"].iloc[0]
    assert brunson["team_id"] == NYK
    assert brunson["status"] == "Day-To-Day"
    assert "won't suit up" in brunson["comment"]
    assert brunson["entry_ts"] == datetime(2026, 10, 13, 2, 20)


def test_parse_skips_an_unknown_team() -> None:
    # A non-NBA club on the list must not cost every game its adjustment
    odd = payload()
    odd["injuries"][0]["displayName"] = "Shanghai Sharks"  # type: ignore[index]
    df = parse_espn_injuries(odd)
    assert len(df) == 9 and LAC not in set(df["team_id"])


def test_parse_of_an_empty_list() -> None:
    df = parse_espn_injuries({"injuries": []})
    assert df.empty and list(df.columns) == [
        "team_id", "player_name", "status", "comment", "entry_ts"]


def recent(hours: float = 20) -> datetime:
    return TIP - timedelta(hours=hours)


def test_status_out_counts_at_any_age() -> None:
    assert is_out("Out", "Strus (foot) is out indefinitely.", recent(24 * 20), TIP, WINDOW)
    assert is_out("Out", None, None, TIP, WINDOW)


@pytest.mark.parametrize("note", [
    "He won't play Tuesday against Toronto for rest purposes.",
    "Brunson (rest) won't suit up for Tuesday's preseason game in Toronto.",
    "Jemison (undisclosed) has been ruled out for Tuesday's preseason meeting.",
    "Brunson won\u2019t play Tuesday.",
    "The Knicks said he will rest Tuesday.",
    "He will not play in the preseason finale.",
    "Brunson will sit out Tuesday's game.",
    "Brunson will miss Tuesday's exhibition.",
    "Doncic will be rested for Tuesday's preseason game against the Warriors.",
    "Doncic is expected to be rested Tuesday.",
    "Doncic is set to be held out Tuesday.",
    "Thiero (undisclosed) is out for Tuesday's preseason game against the Warriors.",
    # Phrasings seen on ESPN's list in October 2026 that the first patterns missed
    "VanVleet (rest) isn't expected to play in Tuesday's preseason game against the Mavericks.",
    "Green isn't expected to face San Antonio, Duane Rankin reports.",
    "Gillespie is not expected to suit up Tuesday.",
    "Booker is not playing in Tuesday's preseason game against the Spurs due to rest.",
    "Brooks is unlikely to suit up for Tuesday's preseason meeting with San Antonio.",
    "Larsson (illness) is doubtful for Tuesday's preseason game against the Nets.",
    "Jakucionis (coach's decision) is inactive for Tuesday's preseason game against Charlotte.",
    "Okoro (undisclosed) will be unavailable for Tuesday's preseason game.",
    "Murray won't travel with the team for Tuesday's game.",
])
def test_a_rest_note_counts_inside_the_window(note: str) -> None:
    assert is_out("Day-To-Day", note, recent(), TIP, WINDOW)


@pytest.mark.parametrize(("note", "days"), [
    ("Smith will miss a couple weeks with a strained right calf.", 14),
    ("Fall was diagnosed with a left hip strain Thursday and will miss at least two weeks.", 14),
    ("Claxton tweaked his hamstring and will be re-evaluated in two weeks.", 14),
    ("The Grizzlies announced Friday that Stewart (ankle) will miss at least 2 weeks.", 14),
    ("Nurkic will miss at least the next four weeks due to a partial plantar plate tear.", 28),
    ("Raynaud will be re-evaluated in approximately two weeks.", 14),
    ("He is expected to be sidelined four to six weeks.", 28),
    ("Sharpe suffered a torn meniscus and is expected to miss six months.", 180),
])
def test_a_note_ruling_a_player_out_for_a_span_counts_for_that_span(
    note: str, days: int
) -> None:
    # Past the 36 h window, and whatever weekday the announcement names
    posted = TIP - timedelta(days=days) + timedelta(hours=1)
    assert is_out("Day-To-Day", note, posted, TIP, WINDOW)
    assert not is_out("Day-To-Day", note, posted - timedelta(hours=2), TIP, WINDOW)


@pytest.mark.parametrize("note", [
    "The Hornets announced Monday that White suffered a left calf strain during training "
    "camp and will not play during the preseason.",
    "Williams will miss the preseason after suffering a right hamstring injury.",
    "Veesaar was diagnosed with a torn right ACL and is expected to miss the 2026-27 season.",
    "Oweh underwent surgery Wednesday and will miss the entirety of the 2026-27 season.",
    "Furphy will miss the remainder of the season.",
    "Hukporti has sustained a season-ending ruptured right Achilles tendon.",
    "Beal (knee) will not be ready for the start of the regular season.",
    "Ingram won't be ready for the start of the season due to a partially torn Achilles.",
])
def test_a_note_ruling_a_player_out_for_the_preseason_or_season_counts(note: str) -> None:
    assert is_out("Day-To-Day", note, recent(24 * 30), TIP, WINDOW)


@pytest.mark.parametrize("note", [
    "He will not play in the preseason finale.",
    "Brunson will miss the season opener.",
    "Hart won't play in the preseason game tonight.",
    "Hart will not play in the preseason contest against Boston.",
    "Hart will not play in the preseason matchup with the Celtics.",
    "Hart won't play in the preseason meeting with Boston.",
])
def test_a_single_game_note_is_not_a_season_span(note: str) -> None:
    assert is_out("Day-To-Day", note, recent(), TIP, WINDOW)
    assert not is_out("Day-To-Day", note, recent(24 * 5), TIP, WINDOW)


def test_a_season_note_ends_with_the_season_it_was_posted_in() -> None:
    # Posted in February 2026: over by the 2026-27 preseason
    note = "Furphy will miss the remainder of the season."
    assert is_out("Day-To-Day", note, datetime(2026, 9, 2), TIP, WINDOW)
    assert not is_out("Day-To-Day", note, datetime(2026, 2, 9, 21, 43), TIP, WINDOW)


def test_a_note_with_a_span_and_a_return_takes_the_span() -> None:
    note = "Beal will miss two weeks but should be ready for the start of the regular season."
    assert is_out("Day-To-Day", note, TIP - timedelta(days=13), TIP, WINDOW)
    assert not is_out("Day-To-Day", note, TIP - timedelta(days=15), TIP, WINDOW)


@pytest.mark.parametrize("note", [
    "Bridges finished with nine points over 22 minutes in Monday's loss.",
    "He did not play Monday due to rest.",
    "Hart sat out Monday's game.",
    "Doncic was rested Monday.",
    "Kaluma (lower body) returned to practice Saturday.",
    "He is expected to play Tuesday.",
    "Bittle hasn't been ruled out for Tuesday.",
    "Bittle has not been ruled out yet.",
    # Recaps posted after a game, and rulings that keep the player in
    "Middleton (rest) was unavailable for Monday's 131-122 preseason loss to Brooklyn.",
    "Okoro (undisclosed) didn't participate in Tuesday's practice.",
    "He isn't expected to miss Tuesday's game.",
    "Sabonis remains questionable for Tuesday's preseason game.",
    "Gueye underwent surgery Tuesday to repair a fractured left foot.",
    "Spurs head coach Mitch Johnson said they will not rush Harris (calf) back to the court.",
    # Affirmative and hedged notes (review of #29)
    "Durant is playing in Tuesday's preseason game against the Spurs.",
    "Thompson is playing through a sore knee.",
    "Doncic will play in the preseason, coach JJ Redick said.",
    "Smith has been cleared to play in the preseason.",
    "Beal is expected to be ready for the start of the regular season.",
    "Ingram should be ready for the start of the season.",
    "Johnson won't miss two weeks after all.",
    "Smith isn't expected to miss a few days.",
    "Gordon could miss a couple weeks.",
    "Williams, who was out for the entire 2025-26 season, is expected to play Tuesday.",
    None,
    "",
])
def test_other_notes_do_not_count(note: str | None) -> None:
    assert not is_out("Day-To-Day", note, recent(), TIP, WINDOW)


def test_a_note_naming_another_day_does_not_count() -> None:
    note = "Gilbert (knee) won't play in Monday's preseason game against the Thunder."
    assert not is_out("Day-To-Day", note, recent(), TIP, WINDOW)
    # A recap of Monday plus a ruling for Tuesday still counts
    note = "Towns ended with 11 points in Monday's loss. He won't play Tuesday for rest."
    assert is_out("Day-To-Day", note, recent(), TIP, WINDOW)


def test_a_rest_note_counts_only_inside_the_window() -> None:
    note = "He won't play for rest purposes."
    assert is_out("Day-To-Day", note, recent(WINDOW), TIP, WINDOW)
    assert not is_out("Day-To-Day", note, recent(WINDOW + 0.1), TIP, WINDOW)
    assert not is_out("Day-To-Day", note, TIP + timedelta(minutes=1), TIP, WINDOW)
    assert not is_out("Day-To-Day", note, None, TIP, WINDOW)


def test_parse_accepts_mixed_date_precision() -> None:
    mixed = payload()
    entries = mixed["injuries"][1]["injuries"]  # type: ignore[index]
    entries[0]["date"] = "2026-10-13T02:47:15Z"
    entries[1]["date"] = None
    df = parse_espn_injuries(mixed)
    assert df["entry_ts"].iloc[1] == datetime(2026, 10, 13, 2, 47, 15)
    assert df["entry_ts"].isna().sum() == 1


def test_scoreboard_asks_for_one_et_date_and_keeps_the_latest_copy(tmp_path: Path) -> None:
    seen: list[httpx.URL] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json={"events": []})

    client = EspnClient(tmp_path, Throttle(0), transport=httpx.MockTransport(answer))
    assert client.get_scoreboard(date(2026, 10, 14)) == {"events": []}
    assert str(seen[0].copy_with(query=None)) == ESPN_SCOREBOARD_URL
    assert seen[0].params["dates"] == "20261014"
    assert (tmp_path / "live" / "espn" / "scoreboard_20261014.json").exists()
