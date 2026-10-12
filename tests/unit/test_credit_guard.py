from pathlib import Path

import duckdb
import pytest

from avaris.config import GuardSettings
from avaris.db import connect
from avaris.ingest.odds_api import CreditGuard, CreditRefused


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    return connect(tmp_path / "a.duckdb")


def guard(con: duckdb.DuckDBPyConnection, **limits: object) -> CreditGuard:
    g = CreditGuard(con, GuardSettings(**limits), run_id="run-1")  # type: ignore[arg-type]
    g.prime(used=100, remaining=400)
    return g


def ledger(con: duckdb.DuckDBPyConnection) -> list[tuple[object, ...]]:
    return con.execute(
        "select purpose, est_cost, status, message from api_usage order by id"
    ).fetchall()


def test_unprimed_guard_refuses_paid_calls(con: duckdb.DuckDBPyConnection) -> None:
    g = CreditGuard(con, GuardSettings(), run_id="r")
    with pytest.raises(CreditRefused, match="not primed"):
        g.authorize("/v4/historical/x", {}, cost=30, purpose="backfill")
    # Free calls never need priming
    g.authorize("/v4/sports", {}, cost=0, purpose="prime")


def test_allows_call_within_limits(con: duckdb.DuckDBPyConnection) -> None:
    guard(con).authorize("/v4/sports/x/odds", {"markets": "h2h"}, cost=3, purpose="decision")
    assert ledger(con) == []  # authorized calls are logged once they complete


@pytest.mark.parametrize(
    ("limits", "cost", "reason"),
    [
        ({"max_credits_per_run": 6}, 9, "per-run cap"),
        ({"monthly_credit_budget": 102, "max_credits_per_run": 50}, 3, "monthly budget"),
        ({"min_remaining_reserve": 398, "monthly_credit_budget": 10_000}, 3, "reserve"),
        (
            {"usd_per_credit": 0.5, "max_monthly_usd": 51.0, "monthly_credit_budget": 10_000},
            3,
            "monthly USD",
        ),
    ],
)
def test_refusal_cases_are_logged(
    con: duckdb.DuckDBPyConnection, limits: dict[str, object], cost: int, reason: str
) -> None:
    g = guard(con, **limits)
    with pytest.raises(CreditRefused, match=reason):
        g.authorize("/v4/sports/x/odds", {"markets": "h2h"}, cost=cost, purpose="decision")
    rows = ledger(con)
    assert len(rows) == 1
    assert rows[0][:3] == ("decision", cost, "refused")
    assert reason in str(rows[0][3])


def test_run_spend_accumulates_toward_the_per_run_cap(con: duckdb.DuckDBPyConnection) -> None:
    g = guard(con, max_credits_per_run=6)
    g.authorize("/a", {}, cost=3, purpose="decision")
    g.record("/a", {}, "decision", est_cost=3, headers={"x-requests-last": "3",
             "x-requests-used": "103", "x-requests-remaining": "397"}, status="ok")
    g.authorize("/a", {}, cost=3, purpose="decision")
    g.record("/a", {}, "decision", est_cost=3, headers={"x-requests-last": "3",
             "x-requests-used": "106", "x-requests-remaining": "394"}, status="ok")
    with pytest.raises(CreditRefused, match="per-run cap"):
        g.authorize("/a", {}, cost=3, purpose="decision")
    assert g.used == 106 and g.remaining == 394 and g.run_spent == 6


def test_headroom_refuses_open_before_close_before_decision(
    con: duckdb.DuckDBPyConnection,
) -> None:
    # used=100 of a 140 budget: 40 left; open needs 30 spare, close 15, decision 0
    g = guard(con, monthly_credit_budget=140, max_credits_per_run=100)
    g.authorize("/a", {}, cost=3, purpose="open")
    g.used = 115
    with pytest.raises(CreditRefused, match="monthly budget"):
        g.authorize("/a", {}, cost=3, purpose="open")
    g.authorize("/a", {}, cost=3, purpose="close")
    g.used = 130
    with pytest.raises(CreditRefused):
        g.authorize("/a", {}, cost=3, purpose="close")
    g.authorize("/a", {}, cost=3, purpose="decision")


def test_ledger_row_never_contains_the_api_key(con: duckdb.DuckDBPyConnection) -> None:
    g = guard(con)
    g.record("/a", {"apiKey": "SECRET123", "markets": "h2h"}, "prime", est_cost=0,
             headers={}, status="ok")
    params = con.execute("select params from api_usage").fetchone()
    assert params is not None
    assert "SECRET123" not in str(params[0])
    assert "h2h" in str(params[0])


def test_zero_cost_is_free_only_for_priming(con: duckdb.DuckDBPyConnection) -> None:
    g = guard(con)
    g.authorize("/v4/sports", {}, cost=0, purpose="prime")
    with pytest.raises(CreditRefused, match="no cost estimate"):
        g.authorize("/v4/historical/x", {}, cost=0, purpose="open")
