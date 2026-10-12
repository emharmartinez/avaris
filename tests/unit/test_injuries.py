from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from avaris.db import connect, upsert
from avaris.ingest.injuries import (
    floor_to_report_slot,
    normalize_name,
    parse_report,
    report_filename,
    resolve_entries,
    target_slots,
)
from avaris.seasons import ET

FIXTURES = Path(__file__).parents[1] / "fixtures" / "injuries"
HOURLY_PDF = FIXTURES / "Injury-Report_2022-01-15_05PM.pdf"
QUARTER_PDF = FIXTURES / "Injury-Report_2026-01-20_05_30PM.pdf"


def et(*args: int) -> datetime:
    return datetime(*args, tzinfo=ET)


@pytest.mark.parametrize(
    ("ts", "slot"),
    [
        (et(2022, 1, 15, 18, 0), et(2022, 1, 15, 17, 30)),
        (et(2022, 1, 15, 18, 29), et(2022, 1, 15, 17, 30)),
        (et(2022, 1, 15, 18, 30), et(2022, 1, 15, 18, 30)),
        (et(2026, 1, 20, 18, 0), et(2026, 1, 20, 18, 0)),
        (et(2026, 1, 20, 17, 59), et(2026, 1, 20, 17, 45)),
    ],
)
def test_floor_to_report_slot(ts: datetime, slot: datetime) -> None:
    # Hourly reports at :30 until 2025-12-21, every 15 minutes from 2025-12-22
    assert floor_to_report_slot(ts) == slot


@pytest.mark.parametrize(
    ("slot", "name"),
    [
        (et(2022, 1, 15, 17, 30), "Injury-Report_2022-01-15_05PM.pdf"),
        (et(2022, 1, 15, 11, 30), "Injury-Report_2022-01-15_11AM.pdf"),
        (et(2022, 1, 15, 12, 30), "Injury-Report_2022-01-15_12PM.pdf"),
        (et(2026, 1, 20, 17, 30), "Injury-Report_2026-01-20_05_30PM.pdf"),
        (et(2026, 1, 20, 18, 0), "Injury-Report_2026-01-20_06_00PM.pdf"),
    ],
)
def test_report_filename(slot: datetime, name: str) -> None:
    assert report_filename(slot) == name


def test_target_slots_cover_each_tip_plus_early_afternoon() -> None:
    tips = [datetime(2022, 1, 16, 0, 0), datetime(2022, 1, 16, 3, 0), datetime(2022, 1, 16, 0, 0)]
    assert target_slots(tips, date(2022, 1, 15)) == [
        et(2022, 1, 15, 13, 30),
        et(2022, 1, 15, 17, 30),
        et(2022, 1, 15, 20, 30),
    ]


def test_parse_hourly_report() -> None:
    report = parse_report(HOURLY_PDF.read_bytes())
    assert report.report_ts == datetime(2022, 1, 15, 22, 30)  # 5:30 pm EST in UTC
    df = report.entries
    assert len(df) == 123
    assert (df["status"] == "not_submitted").sum() == 5
    assert set(df["status"]) <= {"out", "doubtful", "questionable", "probable", "available",
                                 "not_submitted"}
    holiday = df[df["player_name"] == "Holiday, Jrue"].iloc[0]
    assert holiday["status"] == "out"
    assert holiday["team_name"] == "Milwaukee Bucks"
    assert holiday["matchup"] == "TOR@MIL"
    assert holiday["game_date_et"] == date(2022, 1, 15)
    not_submitted = df[df["status"] == "not_submitted"]
    assert (not_submitted["player_name"] == "").all()
    assert set(not_submitted["game_date_et"]) == {date(2022, 1, 16)}


def test_parse_quarter_hour_report() -> None:
    report = parse_report(QUARTER_PDF.read_bytes())
    assert report.report_ts == datetime(2026, 1, 20, 22, 30)
    assert len(report.entries) == 113


def test_parse_rejects_non_report() -> None:
    with pytest.raises(ValueError, match="header"):
        parse_report(b"%PDF-1.4 not a report")


@pytest.mark.parametrize(
    ("printed", "stats"),
    [
        ("Trent Jr., Gary", "Gary Trent Jr."),
        ("Doncic, Luka", "Luka Dončić"),
        ("Porzingis, Kristaps", "Kristaps Porziņģis"),
        ("Gilgeous-Alexander, Shai", "Shai Gilgeous-Alexander"),
        ("Tucker, P.J.", "P.J. Tucker"),
        ("Jackson III, Jaren", "Jaren Jackson Jr."),
    ],
)
def test_normalize_name_matches_stats_spelling(printed: str, stats: str) -> None:
    # Accents, punctuation and suffixes (Jr., III) are dropped
    assert normalize_name(printed) == normalize_name(stats)


def _db(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    con = connect(tmp_path / "a.duckdb")
    game = {
        "game_id": "0022100620", "season": "2021-22", "season_type": "regular",
        "game_date_et": date(2022, 1, 15), "tip_off_utc": datetime(2022, 1, 15, 23, 30),
        "home_team_id": 1610612749, "away_team_id": 1610612761, "status": "final",
        "neutral_site": False,
    }
    upsert(con, "games", pd.DataFrame([game]))
    roster = [
        (1610612749, 201950, "Jrue Holiday"),
        (1610612749, 201572, "Brook Lopez"),
        (1610612761, 1630567, "Scottie Barnes"),
        (1610612761, 1629018, "Gary Trent Jr."),
        (1610612761, 203095, "Khem Birch"),
    ]
    upsert(con, "rosters", pd.DataFrame([
        {"season": "2021-22", "team_id": t, "player_id": p, "player_name": n,
         "position": None, "how_acquired": None} for t, p, n in roster
    ]))
    return con


def _entries(*rows: tuple[str, str, str, str]) -> pd.DataFrame:
    return pd.DataFrame([
        {"game_date_et": date(2022, 1, 15), "matchup": m, "team_name": t, "player_name": p,
         "status": s, "reason": "x"} for m, t, p, s in rows
    ])


def test_resolve_entries_maps_game_team_and_player(tmp_path: Path) -> None:
    con = _db(tmp_path)
    entries = _entries(
        ("TOR@MIL", "Milwaukee Bucks", "Holiday, Jrue", "out"),
        ("TOR@MIL", "Toronto Raptors", "Trent Jr., Gary", "questionable"),
        ("TOR@MIL", "Toronto Raptors", "Nobody, Some", "out"),
        ("TOR@MIL", "Toronto Raptors", "", "not_submitted"),
        ("LAC@SAS", "LA Clippers", "George, Paul", "out"),
    )
    out = resolve_entries(con, entries, datetime(2022, 1, 15, 22, 30))
    rows = {r["player_name"]: r for r in out.to_dict("records")}
    assert rows["Holiday, Jrue"]["game_id"] == "0022100620"
    assert rows["Holiday, Jrue"]["team_id"] == 1610612749
    assert rows["Holiday, Jrue"]["player_id"] == 201950
    assert rows["Trent Jr., Gary"]["player_id"] == 1629018
    assert pd.isna(rows["Nobody, Some"]["player_id"])
    assert pd.isna(rows[""]["player_id"])
    # No stored game for LAC@SAS: kept with a null game_id, team still resolved
    assert pd.isna(rows["George, Paul"]["game_id"])
    assert rows["George, Paul"]["team_id"] == 1610612746
    assert (out["report_ts"] == datetime(2022, 1, 15, 22, 30)).all()


def test_resolve_entries_falls_back_to_first_initial_and_last_name(tmp_path: Path) -> None:
    con = _db(tmp_path)
    out = resolve_entries(
        con,
        _entries(("TOR@MIL", "Toronto Raptors", "Birch, K.", "out")),
        datetime(2022, 1, 15, 22, 30),
    )
    assert out.iloc[0]["player_id"] == 203095


def test_resolve_entries_falls_back_to_other_seasons(tmp_path: Path) -> None:
    con = _db(tmp_path)
    upsert(con, "rosters", pd.DataFrame([{
        "season": "2020-21", "team_id": 1610612765, "player_id": 1629045,
        "player_name": "Chris Smith", "position": None, "how_acquired": None,
    }]))
    out = resolve_entries(
        con,
        _entries(("TOR@MIL", "Toronto Raptors", "Smith, Chris", "out")),
        datetime(2022, 1, 15, 22, 30),
    )
    assert out.iloc[0]["player_id"] == 1629045


def test_resolve_entries_handles_an_empty_report(tmp_path: Path) -> None:
    con = _db(tmp_path)
    empty = pd.DataFrame(columns=["game_date_et", "matchup", "team_name", "player_name",
                                  "status", "reason"])
    out = resolve_entries(con, empty, datetime(2022, 1, 15, 22, 30))
    assert out.empty
    assert {"game_id", "team_id", "player_id", "report_ts"} <= set(out.columns)


def test_exact_season_name_beats_a_teammate_with_the_same_initial(tmp_path: Path) -> None:
    con = _db(tmp_path)
    # Kevin Birch (new signing) is in the season data for another team only; Khem Birch is
    # on Toronto. "Birch, Kevin" must not become Khem
    upsert(con, "rosters", pd.DataFrame([{
        "season": "2021-22", "team_id": 1610612749, "player_id": 999, "player_name": "Kevin Birch",
        "position": None, "how_acquired": None,
    }]))
    out = resolve_entries(
        con,
        _entries(("TOR@MIL", "Toronto Raptors", "Birch, Kevin", "out")),
        datetime(2022, 1, 15, 22, 30),
    )
    assert out.iloc[0]["player_id"] == 999
