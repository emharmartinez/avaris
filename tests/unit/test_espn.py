import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from avaris.ingest.espn import is_out, parse_espn_injuries

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
])
def test_a_rest_note_counts_inside_the_window(note: str) -> None:
    assert is_out("Day-To-Day", note, recent(), TIP, WINDOW)


@pytest.mark.parametrize("note", [
    "Bridges finished with nine points over 22 minutes in Monday's loss.",
    "He did not play Monday due to rest.",
    "Hart sat out Monday's game.",
    "Doncic was rested Monday.",
    "Kaluma (lower body) returned to practice Saturday.",
    "He is expected to play Tuesday.",
    "Bittle hasn't been ruled out for Tuesday.",
    "Bittle has not been ruled out yet.",
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
