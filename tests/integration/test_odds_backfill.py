from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import httpx
import pandas as pd
import pytest
import respx

from avaris.config import GuardSettings, OddsSettings
from avaris.db import connect, upsert
from avaris.ingest.odds_api import API_BASE, CreditGuard, OddsApiClient
from avaris.ingest.odds_backfill import (
    PlannedCall,
    assign_kinds,
    days_without_injury_reports,
    estimate_plan,
    match_events,
    parse_historical,
    plan_backfill,
    run_backfill,
    snapshot_rows,
)
from avaris.ingest.odds_slots import Slot
from tests.odds_payloads import event, historical

CFG = OddsSettings()
DAY = date(2022, 1, 15)
MIL, TOR, SAS, LAC = 1610612749, 1610612761, 1610612759, 1610612746
G1_TIP = datetime(2022, 1, 15, 23, 30)  # TOR@MIL 6:30 pm ET
G2_TIP = datetime(2022, 1, 16, 1, 0)  # LAC@SAS 8:00 pm ET
SNAPSHOT_LAG = timedelta(minutes=3)


def game_row(gid: str, home: int, away: int, tip: datetime, season_type: str = "regular",
             day: date = DAY) -> dict[str, Any]:
    return {
        "game_id": gid, "season": "2021-22", "season_type": season_type, "game_date_et": day,
        "tip_off_utc": tip, "home_team_id": home, "away_team_id": away, "status": "final",
        "neutral_site": False,
    }


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    con = connect(tmp_path / "a.duckdb")
    upsert(con, "games", pd.DataFrame([
        game_row("g1", MIL, TOR, G1_TIP),
        game_row("g2", SAS, LAC, G2_TIP),
        game_row("p1", MIL, TOR, datetime(2021, 10, 5, 0, 0), "preseason", date(2021, 10, 4)),
    ]))
    upsert(con, "injury_report_files", pd.DataFrame([{
        "slot_ts": datetime(2022, 1, 15, 22, 30), "report_ts": datetime(2022, 1, 15, 22, 30),
        "url": "u", "status": "ok", "n_entries": 1, "fetched_at": datetime(2022, 1, 20),
    }]))
    return con


def day_events() -> list[dict[str, Any]]:
    return [
        event("ev1", "Milwaukee Bucks", "Toronto Raptors", G1_TIP, spread=-6.5),
        event("ev2", "San Antonio Spurs", "Los Angeles Clippers", G2_TIP, spread=3.5),
        event("ev3", "Springfield Isotopes", "Toronto Raptors", G2_TIP),
    ]


@pytest.fixture
def odds_api() -> Iterator[respx.MockRouter]:
    # Each historical request returns the snapshot 3 minutes before the requested date
    def respond(request: httpx.Request) -> httpx.Response:
        requested = datetime.strptime(request.url.params["date"], "%Y-%m-%dT%H:%M:%SZ")
        headers = {"x-requests-last": "30", "x-requests-used": "0",
                   "x-requests-remaining": "5000000"}
        return httpx.Response(
            200, json=historical(requested - SNAPSHOT_LAG, day_events()), headers=headers
        )

    with respx.mock(base_url=API_BASE, assert_all_called=False) as router:
        router.get("/v4/sports").mock(return_value=httpx.Response(200, json=[], headers={
            "x-requests-last": "0", "x-requests-used": "0", "x-requests-remaining": "5000000",
        }))
        router.get("/v4/historical/sports/basketball_nba/odds").mock(side_effect=respond)
        yield router


def make_client(con: duckdb.DuckDBPyConnection, tmp_path: Path, per_run: int = 10_000,
                key: str | None = "k") -> OddsApiClient:
    guard = CreditGuard(con, GuardSettings(max_credits_per_run=per_run,
                                           monthly_credit_budget=5_000_000), run_id="run-1")
    return OddsApiClient(key, guard, tmp_path / "cache", sport="basketball_nba",
                         regions=["us"], markets=["h2h", "spreads", "totals"], retry_wait_s=0.0)


def test_parse_historical_reads_snapshot_events_and_outcomes() -> None:
    snap = datetime(2022, 1, 15, 22, 27)
    parsed = parse_historical(historical(snap, day_events()))
    assert parsed.snapshot_ts == snap
    assert list(parsed.events["event_id"]) == ["ev1", "ev2", "ev3"]
    assert parsed.events.iloc[0]["commence_time_utc"] == G1_TIP
    ev1 = parsed.outcomes[parsed.outcomes["event_id"] == "ev1"]
    assert len(ev1) == 2 * 3 * 2  # 2 books x 3 markets x 2 outcomes
    spread = ev1[(ev1["market"] == "spreads") & (ev1["name"] == "Milwaukee Bucks")]
    assert set(spread["line"]) == {-6.5}


def test_match_events_by_teams_and_commence_time(con: duckdb.DuckDBPyConnection) -> None:
    preseason = event("ev4", "Milwaukee Bucks", "Toronto Raptors", datetime(2021, 10, 5, 0, 5))
    late = event("ev5", "San Antonio Spurs", "Toronto Raptors", G1_TIP)
    parsed = parse_historical(historical(G1_TIP, [*day_events(), preseason, late]))
    matched = match_events(con, parsed.events, CFG.match_window_min).set_index("event_id")
    assert matched.loc["ev1", "game_id"] == "g1"
    assert matched.loc["ev2", "game_id"] == "g2"  # "Los Angeles Clippers" alias
    assert matched.loc["ev3", "match_status"] == "unknown_team"
    assert matched.loc["ev4", "match_status"] == "preseason"
    assert matched.loc["ev5", "match_status"] == "no_game"  # no such pairing
    assert pd.isna(matched.loc["ev5", "game_id"])


def test_swapped_home_and_away_still_matches_and_sides_follow_the_game(
    con: duckdb.DuckDBPyConnection,
) -> None:
    # Neutral-site games can list the other team as home
    swapped = event("ev9", "Toronto Raptors", "Milwaukee Bucks", G1_TIP, spread=6.5)
    parsed = parse_historical(historical(datetime(2022, 1, 15, 22, 0), [swapped]))
    matched = match_events(con, parsed.events, CFG.match_window_min)
    assert matched.iloc[0]["game_id"] == "g1"
    rows = snapshot_rows(parsed, matched, {"g1": "decision"})
    home_spread = rows[(rows["market"] == "spreads") & (rows["side"] == "home")]
    assert set(home_spread["line"]) == {-6.5}  # Milwaukee, the NBA home team


def test_snapshot_rows_drop_started_games_and_unmatched_events(
    con: duckdb.DuckDBPyConnection,
) -> None:
    parsed = parse_historical(historical(G1_TIP + timedelta(minutes=5), day_events()))
    matched = match_events(con, parsed.events, CFG.match_window_min)
    rows = snapshot_rows(parsed, matched, {"g2": "close"})
    assert set(rows["game_id"]) == {"g2"}  # g1 has tipped; ev3 is unmatched
    assert set(rows["kind"]) == {"close"}
    assert set(rows["side"]) == {"home", "away", "over", "under"}
    assert len(rows) == 12


def test_assign_kinds_close_needs_the_actual_snapshot_inside_the_window() -> None:
    roles = [Slot(datetime(2022, 1, 15, 23, 28), "close", ("g1",)),
             Slot(datetime(2022, 1, 15, 23, 28), "decision", ("g2",))]
    tips = {"g1": G1_TIP, "g2": G2_TIP}
    assert assign_kinds(roles, datetime(2022, 1, 15, 23, 25), tips, 45) == {
        "g1": "close", "g2": "decision",
    }
    # A snapshot older than 45 min before tip is not a closing line
    assert assign_kinds(roles, datetime(2022, 1, 15, 22, 40), tips, 45)["g1"] == "other"


def test_plan_uses_injury_decision_times_and_shared_slots(con: duckdb.DuckDBPyConnection) -> None:
    plan = plan_backfill(con, DAY, DAY, CFG)
    assert plan[0].decisions == {"g1": datetime(2022, 1, 15, 22, 30),
                                 "g2": datetime(2022, 1, 15, 22, 30)}
    assert [(c.ts, sorted(s.kind for s in c.roles)) for c in plan] == [
        (datetime(2022, 1, 15, 14, 0), ["open"]),
        (datetime(2022, 1, 15, 22, 30), ["decision"]),  # the 5:30 pm ET report
        (datetime(2022, 1, 15, 23, 28), ["close"]),
        (datetime(2022, 1, 16, 0, 58), ["close"]),
    ]
    assert {c.season for c in plan} == {"2021-22"}


def test_estimate_counts_uncached_calls_offline(
    con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    client = make_client(con, tmp_path, key=None)  # no key needed to estimate
    est = estimate_plan(plan_backfill(con, DAY, DAY, CFG), client)
    assert est.to_dict("records") == [
        {"season": "2021-22", "game_days": 1, "calls": 4, "cached": 0, "credits": 120}
    ]
    assert con.execute("select count(*) from api_usage").fetchone() == (0,)


def test_run_backfill_stores_kinds_and_is_free_to_rerun(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, odds_api: respx.MockRouter
) -> None:
    client = make_client(con, tmp_path)
    client.prime()
    plan = plan_backfill(con, DAY, DAY, CFG)
    summary = run_backfill(con, client, plan, CFG)
    assert summary.calls == 4 and summary.refused is None

    kinds = con.execute(
        "select game_id, snapshot_ts, any_value(kind) from odds_snapshots "
        "group by all order by 1, 2"
    ).fetchall()
    assert kinds == [
        ("g1", datetime(2022, 1, 15, 13, 57), "open"),
        ("g1", datetime(2022, 1, 15, 22, 27), "decision"),
        ("g1", datetime(2022, 1, 15, 23, 25), "close"),
        ("g2", datetime(2022, 1, 15, 13, 57), "open"),
        ("g2", datetime(2022, 1, 15, 22, 27), "decision"),
        ("g2", datetime(2022, 1, 15, 23, 25), "other"),
        ("g2", datetime(2022, 1, 16, 0, 55), "close"),
    ]
    statuses = dict(con.execute("select event_id, match_status from odds_events").fetchall())
    assert statuses == {"ev1": "matched", "ev2": "matched", "ev3": "unknown_team"}
    spent = con.execute(
        "select sum(actual_cost) from api_usage where status = 'ok'"
    ).fetchone()
    assert spent == (120,)

    # Rerun: every snapshot is cached, so no request and no credits
    calls = odds_api.calls.call_count
    rows = con.execute("select count(*) from odds_snapshots").fetchone()
    again = run_backfill(con, client, plan, CFG)
    assert again.cached == 4
    assert odds_api.calls.call_count == calls
    assert con.execute("select count(*) from odds_snapshots").fetchone() == rows


def test_run_backfill_stops_cleanly_when_the_guard_refuses(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, odds_api: respx.MockRouter
) -> None:
    client = make_client(con, tmp_path, per_run=60)
    client.prime()
    summary = run_backfill(con, client, plan_backfill(con, DAY, DAY, CFG), CFG)
    assert summary.calls == 2
    assert summary.refused is not None and "per-run cap" in summary.refused
    statuses = [r[0] for r in con.execute("select status from api_usage order by id").fetchall()]
    assert statuses == ["ok", "ok", "ok", "refused"]


def test_assign_kinds_never_marks_a_snapshot_after_decision_ts_as_decision_or_open() -> None:
    roles = [Slot(datetime(2022, 1, 15, 14, 0), "open", ("g1",)),
             Slot(datetime(2022, 1, 15, 14, 0), "decision", ("g1",))]
    kinds = assign_kinds(roles, datetime(2022, 1, 15, 22, 40), {"g1": G1_TIP}, 45,
                         decisions={"g1": datetime(2022, 1, 15, 22, 30)})
    assert kinds == {"g1": "other"}


def test_match_events_tags_postponed_games(con: duckdb.DuckDBPyConnection) -> None:
    # Listed at the original time; the game was replayed weeks later
    upsert(con, "games", pd.DataFrame([game_row("g9", SAS, TOR, datetime(2022, 2, 20, 1, 0),
                                                day=date(2022, 2, 19))]))
    ev = event("ev9", "San Antonio Spurs", "Toronto Raptors", datetime(2022, 1, 16, 1, 0))
    matched = match_events(con, parse_historical(historical(G1_TIP, [ev])).events, 120)
    assert matched.iloc[0]["match_status"] == "postponed"
    assert pd.isna(matched.iloc[0]["game_id"])


def test_plan_reads_late_reports_after_midnight_utc(con: duckdb.DuckDBPyConnection) -> None:
    # A 10 pm ET tip: its decision report is 8:30 pm ET, i.e. 01:30 UTC the next day
    upsert(con, "games", pd.DataFrame([game_row("g3", 1610612744, 1610612743,
                                                datetime(2022, 1, 16, 3, 0))]))
    upsert(con, "injury_report_files", pd.DataFrame([{
        "slot_ts": datetime(2022, 1, 16, 1, 30), "report_ts": datetime(2022, 1, 16, 1, 30),
        "url": "u", "status": "ok", "n_entries": 1, "fetched_at": datetime(2022, 1, 20),
    }]))
    decisions = [(c.ts, r.game_ids) for c in plan_backfill(con, DAY, DAY, CFG)
                 for r in c.roles if r.kind == "decision"]
    assert (datetime(2022, 1, 16, 1, 30), ("g3",)) in decisions


def test_days_without_injury_reports(con: duckdb.DuckDBPyConnection) -> None:
    upsert(con, "games", pd.DataFrame([game_row("g7", MIL, TOR, datetime(2022, 1, 20, 0, 0),
                                                day=date(2022, 1, 19))]))
    plan = plan_backfill(con, DAY, date(2022, 1, 19), CFG)
    assert days_without_injury_reports(plan, first_season="2021-22") == [date(2022, 1, 19)]
    assert days_without_injury_reports(plan, first_season="2022-23") == []


def test_same_snapshot_from_two_calls_keeps_the_stronger_kind(
    con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    # Both requests floor to the 22:20 snapshot: g1's decision must survive the second call,
    # which only knows g2's role
    snap = datetime(2022, 1, 15, 22, 20)
    tips = {"g1": G1_TIP, "g2": G2_TIP}
    calls = [
        PlannedCall("2021-22", DAY, datetime(2022, 1, 15, 22, 25),
                    (Slot(datetime(2022, 1, 15, 22, 25), "decision", ("g1",)),), tips, {}),
        PlannedCall("2021-22", DAY, datetime(2022, 1, 15, 22, 28),
                    (Slot(datetime(2022, 1, 15, 22, 28), "open", ("g2",)),), tips, {}),
    ]
    headers = {"x-requests-last": "30", "x-requests-used": "0", "x-requests-remaining": "5000000"}
    with respx.mock(base_url=API_BASE, assert_all_called=False) as router:
        router.get("/v4/sports").mock(return_value=httpx.Response(200, json=[], headers=headers))
        router.get("/v4/historical/sports/basketball_nba/odds").mock(
            return_value=httpx.Response(200, json=historical(snap, day_events()), headers=headers)
        )
        client = make_client(con, tmp_path)
        client.prime()
        run_backfill(con, client, calls, CFG)
    kinds = dict(con.execute(
        "select game_id, any_value(kind) from odds_snapshots group by game_id"
    ).fetchall())
    assert kinds == {"g1": "decision", "g2": "open"}
