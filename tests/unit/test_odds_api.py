import logging
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import httpx
import pytest
import respx

from avaris.config import GuardSettings
from avaris.db import connect
from avaris.ingest.odds_api import (
    API_BASE,
    CreditGuard,
    CreditRefused,
    LedgerMismatch,
    OddsApiClient,
    OddsApiError,
    load_api_key,
)
from avaris.ingest.odds_status import reconcile_run

KEY = "SECRET-KEY-123"
SNAPSHOT = datetime(2022, 1, 15, 22, 30)
WINDOW = (datetime(2022, 1, 15, 5, 0), datetime(2022, 1, 16, 5, 0))
USAGE = {"x-requests-used": "100", "x-requests-remaining": "4999900"}


def event(markets: list[str]) -> dict[str, Any]:
    outcomes = {
        "h2h": [
            {"name": "Milwaukee Bucks", "price": 1.5},
            {"name": "Toronto Raptors", "price": 2.7},
        ],
        "spreads": [
            {"name": "Milwaukee Bucks", "price": 1.91, "point": -6.5},
            {"name": "Toronto Raptors", "price": 1.91, "point": 6.5},
        ],
        "totals": [
            {"name": "Over", "price": 1.91, "point": 221.5},
            {"name": "Under", "price": 1.91, "point": 221.5},
        ],
    }
    return {
        "id": "ev1", "sport_key": "basketball_nba", "commence_time": "2022-01-15T23:30:00Z",
        "home_team": "Milwaukee Bucks", "away_team": "Toronto Raptors",
        "bookmakers": [{
            "key": "fanduel", "title": "FanDuel", "last_update": "2022-01-15T22:25:00Z",
            "markets": [{"key": m, "outcomes": outcomes[m]} for m in markets],
        }],
    }


def historical(data: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "timestamp": "2022-01-15T22:25:00Z", "previous_timestamp": "2022-01-15T22:15:00Z",
        "next_timestamp": "2022-01-15T22:35:00Z", "data": data,
    }


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    return connect(tmp_path / "a.duckdb")


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=API_BASE, assert_all_called=False) as router:
        router.get("/v4/sports").mock(return_value=httpx.Response(
            200, json=[{"key": "basketball_nba"}], headers={**USAGE, "x-requests-last": "0"}
        ))
        yield router


def make_client(con: duckdb.DuckDBPyConnection, tmp_path: Path, **limits: Any) -> OddsApiClient:
    guard_limits = {"max_credits_per_run": 1000, "monthly_credit_budget": 5_000_000, **limits}
    guard = CreditGuard(con, GuardSettings(**guard_limits), run_id="run-1")
    return OddsApiClient(
        KEY, guard, tmp_path / "cache", sport="basketball_nba", regions=["us"],
        markets=["h2h", "spreads", "totals"], retry_wait_s=0.0,
    )


def mock_historical(api: respx.MockRouter, payload: dict[str, Any], last: str) -> respx.Route:
    return api.get("/v4/historical/sports/basketball_nba/odds").mock(
        return_value=httpx.Response(200, json=payload, headers={**USAGE, "x-requests-last": last})
    )


def ledger(con: duckdb.DuckDBPyConnection) -> list[tuple[Any, ...]]:
    return con.execute(
        "select endpoint, purpose, est_cost, actual_cost, status from api_usage order by id"
    ).fetchall()


def test_prime_reads_usage_from_the_free_sports_call(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, api: respx.MockRouter
) -> None:
    client = make_client(con, tmp_path)
    client.prime()
    assert client.guard.used == 100
    assert client.guard.remaining == 4999900
    assert ledger(con) == [("/v4/sports", "prime", 0, 0, "ok")]


def test_historical_call_is_guarded_logged_and_cached(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, api: respx.MockRouter
) -> None:
    route = mock_historical(api, historical([event(["h2h", "spreads", "totals"])]), "30")
    client = make_client(con, tmp_path)
    client.prime()
    payload = client.historical_odds(SNAPSHOT, "decision", *WINDOW)
    assert payload["data"][0]["id"] == "ev1"
    params = route.calls.last.request.url.params
    assert params["date"] == "2022-01-15T22:30:00Z"
    assert params["markets"] == "h2h,spreads,totals"
    assert params["oddsFormat"] == "decimal"
    assert params["commenceTimeFrom"] == "2022-01-15T05:00:00Z"
    assert ledger(con)[-1] == (
        "/v4/historical/sports/basketball_nba/odds", "decision", 30, 30, "ok"
    )
    assert client.guard.run_spent == 30

    # Second request is served from the cache: no call, no ledger row, no credits
    assert client.is_cached(SNAPSHOT, *WINDOW)
    again = client.historical_odds(SNAPSHOT, "decision", *WINDOW)
    assert again == payload
    assert route.call_count == 1
    assert len(ledger(con)) == 2


def test_cache_files_never_contain_the_key(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, api: respx.MockRouter
) -> None:
    mock_historical(api, historical([event(["h2h"])]), "10")
    client = make_client(con, tmp_path)
    client.prime()
    client.historical_odds(SNAPSHOT, "open", *WINDOW)
    paths = [str(p) for p in (tmp_path / "cache").rglob("*")]
    assert paths
    assert not any(KEY in p for p in paths)


def test_empty_data_costs_nothing(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, api: respx.MockRouter
) -> None:
    mock_historical(api, historical([]), "0")
    client = make_client(con, tmp_path)
    client.prime()
    client.historical_odds(SNAPSHOT, "open", *WINDOW)
    assert ledger(con)[-1][-2:] == (0, "ok")


def test_charge_for_returned_markets_only_reconciles(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, api: respx.MockRouter
) -> None:
    mock_historical(api, historical([event(["h2h", "spreads"])]), "20")
    client = make_client(con, tmp_path)
    client.prime()
    client.historical_odds(SNAPSHOT, "open", *WINDOW)
    assert ledger(con)[-1][-2:] == (20, "ok")


def test_cost_mismatch_stops_the_run(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, api: respx.MockRouter
) -> None:
    mock_historical(api, historical([event(["h2h", "spreads", "totals"])]), "40")
    client = make_client(con, tmp_path)
    client.prime()
    with pytest.raises(LedgerMismatch):
        client.historical_odds(SNAPSHOT, "open", *WINDOW)
    assert ledger(con)[-1][-2:] == (40, "mismatch")
    # A mismatched response is not cached, so it is never used silently
    assert not client.is_cached(SNAPSHOT, *WINDOW)


def test_refused_call_never_reaches_the_api(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, api: respx.MockRouter
) -> None:
    route = mock_historical(api, historical([]), "0")
    client = make_client(con, tmp_path, max_credits_per_run=6)
    client.prime()
    with pytest.raises(CreditRefused):
        client.historical_odds(SNAPSHOT, "open", *WINDOW)
    assert route.call_count == 0
    assert ledger(con)[-1][-1] == "refused"


def test_http_errors_hide_the_key(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, api: respx.MockRouter
) -> None:
    api.get("/v4/historical/sports/basketball_nba/odds").mock(
        return_value=httpx.Response(401, json={"message": "Invalid api key"}, headers=USAGE)
    )
    client = make_client(con, tmp_path)
    client.prime()
    with pytest.raises(OddsApiError) as info:
        client.historical_odds(SNAPSHOT, "open", *WINDOW)
    assert "401" in str(info.value)
    assert KEY not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__
    assert ledger(con)[-1][-1] == "error"


def test_transport_errors_hide_the_key(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, api: respx.MockRouter
) -> None:
    api.get("/v4/historical/sports/basketball_nba/odds").mock(
        side_effect=httpx.ConnectError(f"boom https://x/?apiKey={KEY}")
    )
    client = make_client(con, tmp_path)
    client.prime()
    with pytest.raises(OddsApiError) as info:
        client.historical_odds(SNAPSHOT, "open", *WINDOW)
    assert KEY not in str(info.value)


def test_httpx_request_logging_is_silenced(con: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    # httpx logs every request URL (with the apiKey query param) at INFO
    make_client(con, tmp_path)
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


def test_missing_key_fails_before_any_call(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, api: respx.MockRouter
) -> None:
    guard = CreditGuard(con, GuardSettings(), run_id="r")
    client = OddsApiClient(None, guard, tmp_path / "cache", sport="basketball_nba",
                           regions=["us"], markets=["h2h"])
    with pytest.raises(OddsApiError, match="ODDS_API_KEY"):
        client.prime()


def test_load_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    env = tmp_path / ".env.local"
    assert load_api_key(env) is None
    env.write_text('# comment\nOTHER=1\nODDS_API_KEY="abc123"\n')
    assert load_api_key(env) == "abc123"
    monkeypatch.setenv("ODDS_API_KEY", "from-env")
    assert load_api_key(env) == "from-env"


def test_retry_after_transport_error_reprimes_and_counts_the_hidden_charge(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, api: respx.MockRouter
) -> None:
    # The server may charge a request whose response never arrived: the retry must see it
    sports_used = iter(["100", "130", "160"])
    api.get("/v4/sports").mock(side_effect=lambda _r: httpx.Response(
        200, json=[], headers={"x-requests-used": next(sports_used),
                               "x-requests-remaining": "4999000", "x-requests-last": "0"}
    ))
    api.get("/v4/historical/sports/basketball_nba/odds").mock(side_effect=[
        httpx.ReadTimeout("timed out"),
        httpx.Response(200, json=historical([event(["h2h", "spreads", "totals"])]), headers={
            "x-requests-last": "30", "x-requests-used": "160",
            "x-requests-remaining": "4998940",
        }),
    ])
    client = make_client(con, tmp_path, max_credits_per_run=60)
    client.prime()
    client.historical_odds(SNAPSHOT, "open", *WINDOW)
    assert client.guard.run_spent == 60  # the lost response's 30 credits are counted
    # The ledger attributes the hidden charge to the failed attempt, so the run reconciles
    assert reconcile_run(con, "run-1") == (60, 60)


def test_retry_is_refused_when_the_hidden_charge_hits_the_cap(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, api: respx.MockRouter
) -> None:
    sports_used = iter(["100", "130"])
    api.get("/v4/sports").mock(side_effect=lambda _r: httpx.Response(
        200, json=[], headers={"x-requests-used": next(sports_used),
                               "x-requests-remaining": "4999000", "x-requests-last": "0"}
    ))
    route = api.get("/v4/historical/sports/basketball_nba/odds").mock(
        side_effect=httpx.ReadTimeout("timed out")
    )
    client = make_client(con, tmp_path, max_credits_per_run=30)
    client.prime()
    with pytest.raises(CreditRefused, match="per-run cap"):
        client.historical_odds(SNAPSHOT, "open", *WINDOW)
    assert route.call_count == 1


def test_key_is_scrubbed_before_the_error_body_is_truncated(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, api: respx.MockRouter
) -> None:
    body = "x" * 190 + " " + KEY  # the 200-char cut falls inside the key
    api.get("/v4/historical/sports/basketball_nba/odds").mock(
        return_value=httpx.Response(401, text=body, headers=USAGE)
    )
    client = make_client(con, tmp_path)
    client.prime()
    with pytest.raises(OddsApiError) as info:
        client.historical_odds(SNAPSHOT, "open", *WINDOW)
    assert KEY[:6] not in str(info.value)
    message = con.execute("select message from api_usage order by id desc limit 1").fetchone()
    assert message is not None and KEY[:6] not in str(message[0])


def test_undecodable_body_is_an_odds_api_error(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, api: respx.MockRouter
) -> None:
    api.get("/v4/historical/sports/basketball_nba/odds").mock(
        return_value=httpx.Response(200, text="<html>not json</html>",
                                    headers={**USAGE, "x-requests-last": "30"})
    )
    client = make_client(con, tmp_path)
    client.prime()
    with pytest.raises(OddsApiError, match="not JSON"):
        client.historical_odds(SNAPSHOT, "open", *WINDOW)


def test_server_error_is_retried_and_each_attempt_is_logged(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, api: respx.MockRouter
) -> None:
    api.get("/v4/historical/sports/basketball_nba/odds").mock(side_effect=[
        httpx.Response(503, text="busy", headers={**USAGE, "x-requests-last": "0"}),
        httpx.Response(200, json=historical([event(["h2h", "spreads", "totals"])]),
                       headers={**USAGE, "x-requests-last": "30"}),
    ])
    client = make_client(con, tmp_path)
    client.prime()
    client.historical_odds(SNAPSHOT, "open", *WINDOW)
    assert [r[-1] for r in ledger(con)] == ["ok", "error", "ok"]


def test_live_odds_costs_markets_times_regions(
    con: duckdb.DuckDBPyConnection, tmp_path: Path, api: respx.MockRouter
) -> None:
    route = api.get("/v4/sports/basketball_nba/odds").mock(return_value=httpx.Response(
        200, json=[event(["h2h"])], headers={**USAGE, "x-requests-last": "3"}
    ))
    client = make_client(con, tmp_path)
    client.prime()
    assert client.live_odds("decision")[0]["id"] == "ev1"
    assert route.calls.last.request.url.params["markets"] == "h2h,spreads,totals"
    assert ledger(con)[-1] == ("/v4/sports/basketball_nba/odds", "decision", 3, 3, "ok")
