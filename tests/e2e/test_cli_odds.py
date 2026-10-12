import re
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd
import pytest
import respx
from typer.testing import CliRunner

from avaris.cli import app
from avaris.db import connect, upsert
from avaris.ingest.odds_api import API_BASE
from tests.odds_payloads import event, historical

runner = CliRunner()
DAY = "2022-01-15"
G1_TIP = datetime(2022, 1, 15, 23, 30)


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        f'[paths]\ndb_path = "{tmp_path / "avaris.duckdb"}"\ncache_dir = "{tmp_path / "cache"}"\n'
    )
    con = connect(tmp_path / "avaris.duckdb")
    upsert(con, "games", pd.DataFrame([{
        "game_id": "g1", "season": "2021-22", "season_type": "regular",
        "game_date_et": date(2022, 1, 15), "tip_off_utc": G1_TIP, "home_team_id": 1610612749,
        "away_team_id": 1610612761, "status": "final", "neutral_site": False,
    }]))
    con.close()
    return path


@pytest.fixture
def odds_api() -> Iterator[respx.MockRouter]:
    used = {"n": 0}

    def usage(cost: int) -> dict[str, str]:
        used["n"] += cost
        return {"x-requests-last": str(cost), "x-requests-used": str(used["n"]),
                "x-requests-remaining": str(5_000_000 - used["n"])}

    def respond(request: httpx.Request) -> httpx.Response:
        requested = datetime.strptime(request.url.params["date"], "%Y-%m-%dT%H:%M:%SZ")
        events = [
            event("ev1", "Milwaukee Bucks", "Toronto Raptors", G1_TIP),
            event("evx", "Springfield Isotopes", "Toronto Raptors", G1_TIP),
        ]
        payload = historical(requested - timedelta(minutes=3), events)
        return httpx.Response(200, json=payload, headers=usage(30))

    with respx.mock(base_url=API_BASE, assert_all_called=False) as router:
        router.get("/v4/sports").mock(side_effect=lambda _r: httpx.Response(
            200, json=[], headers=usage(0)
        ))
        router.get("/v4/historical/sports/basketball_nba/odds").mock(side_effect=respond)
        yield router


def invoke(config: Path, *args: str) -> tuple[int, str]:
    result = runner.invoke(app, ["--config", str(config), "odds", *args])
    return result.exit_code, result.output


@pytest.mark.e2e
def test_estimate_spends_zero_credits_and_needs_no_key(
    config: Path, tmp_path: Path, odds_api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    for extra in (["--estimate"], []):
        code, out = invoke(config, "backfill", "--from", DAY, "--to", DAY, *extra)
        assert code == 0, out
        assert "2021-22" in out
        assert re.search(r"\b90\b", out)  # open, decision and close snapshots x 30 credits
        assert "--confirm" in out
    assert odds_api.calls.call_count == 0
    con = connect(tmp_path / "avaris.duckdb", read_only=True)
    assert con.execute("select count(*) from api_usage").fetchone() == (0,)


@pytest.mark.e2e
def test_confirm_requires_explicit_caps(config: Path, odds_api: respx.MockRouter) -> None:
    code, out = invoke(config, "backfill", "--from", DAY, "--to", DAY, "--confirm")
    assert code == 1
    assert "--max-credits" in out
    assert odds_api.calls.call_count == 0


@pytest.mark.e2e
def test_confirmed_backfill_reconciles_then_status_and_usage(
    config: Path, odds_api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ODDS_API_KEY", "test-key-xyz")
    code, out = invoke(
        config, "backfill", "--from", DAY, "--to", DAY, "--confirm",
        "--max-credits", "1000", "--monthly-budget", "100000", "--allow-missing-injuries",
    )
    assert code == 0, out
    assert "test-key-xyz" not in out
    assert "Ledger reconciled: 90 credits" in out

    code, out = invoke(config, "usage")
    assert code == 0, out
    assert re.search(r"\b90\b", out)

    # One of two events has an unknown team, so the < 1% unmatched check fails
    code, out = invoke(config, "status", "--check")
    assert code == 1
    assert "unmatched" in out


@pytest.mark.e2e
def test_confirm_refuses_days_without_injury_reports(
    config: Path, tmp_path: Path, odds_api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 2021-22 has injury reports, so a day without one means `ingest injuries` has not run
    monkeypatch.setenv("ODDS_API_KEY", "k")
    code, out = invoke(config, "backfill", "--from", DAY, "--to", DAY, "--confirm",
                       "--max-credits", "1000", "--monthly-budget", "100000")
    assert code == 1
    assert "avaris ingest injuries" in out
    assert odds_api.calls.call_count == 0
