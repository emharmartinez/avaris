from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from avaris.api.main import create_app
from avaris.config import Settings
from avaris.db import connect
from tests.fixtures.live import D1, D2

NOW = datetime(2021, 11, 27, 17, 0)  # D1 final 110-100, D2 still to play


@pytest.fixture
def games(synthetic_db: Path) -> Iterator[tuple[TestClient, list[str], list[str]]]:
    con = connect(synthetic_db)
    con.execute("update games set home_pts = 110, away_pts = 100, status = 'final' "
                "where game_date_et = ?", [D1])
    ids = {d: [r[0] for r in con.execute(
        "select game_id from games where game_date_et = ? order by game_id", [d]).fetchall()]
        for d in (D1, D2)}
    app = create_app(Settings(), con=con, daily_on_startup=False, clock=lambda: NOW)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client, ids[D1], ids[D2]
    con.close()


def place(client: TestClient, **body: Any) -> dict[str, Any]:
    response = client.post("/api/bets", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def bankroll(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/bankroll")
    assert response.status_code == 200, response.text
    return response.json()


def test_no_bankroll_until_one_is_set(games: tuple[TestClient, list[str], list[str]]) -> None:
    client, _, _ = games
    body = bankroll(client)
    assert body["starting"] is None and body["unit"] is None and body["bets"] == []
    response = client.put("/api/bankroll", json={"starting": 1000, "unit_pct": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["starting"] == 1000 and body["current"] == 1000 and body["unit"] == 10
    assert bankroll(client)["unit_pct"] == 1


@pytest.mark.parametrize("payload", [
    {"starting": 0, "unit_pct": 1}, {"starting": 1000, "unit_pct": 0},
    {"starting": 1000, "unit_pct": 101}, {"starting": 1000}, {"starting": 1000, "unit_pct": 1,
                                                              "extra": 1},
])
def test_bankroll_is_validated(
    games: tuple[TestClient, list[str], list[str]], payload: dict[str, Any]
) -> None:
    client, _, _ = games
    assert client.put("/api/bankroll", json=payload).status_code == 422


def test_bets_settle_from_final_scores_into_the_bankroll(
    games: tuple[TestClient, list[str], list[str]],
) -> None:
    client, d1, d2 = games
    client.put("/api/bankroll", json={"starting": 1000, "unit_pct": 1})
    won = place(client, game_id=d1[0], market="moneyline", side="home", odds=1.8, stake=10)
    assert won["result"] == "won" and won["profit"] == pytest.approx(8)
    assert won["placed_at"] == "2021-11-27T17:00:00Z"
    assert won["game"]["home"]["abbreviation"] and won["game"]["status"] == "final"
    place(client, game_id=d1[1], market="spread", side="away", line=9.5, odds=2.0, stake=20)
    place(client, game_id=d1[1], market="total", side="over", line=210, odds=1.9, stake=5)
    pending = place(client, game_id=d2[0], market="total", side="under", line=221.5, odds=1.9,
                    stake=30)
    assert pending["result"] == "pending" and pending["profit"] is None

    body = bankroll(client)
    assert body["bets"][0]["bet_id"] == pending["bet_id"]  # newest first
    assert [b["result"] for b in body["bets"]] == ["pending", "push", "lost", "won"]
    assert body["profit"] == pytest.approx(8 - 20)
    assert body["current"] == pytest.approx(988)
    assert body["unit"] == pytest.approx(9.88)
    assert body["in_play"] == 30
    assert body["record"] == {"won": 1, "lost": 1, "push": 1, "pending": 1}


@pytest.mark.parametrize("payload", [
    {"market": "moneyline", "side": "over", "odds": 2, "stake": 10},
    {"market": "total", "side": "home", "line": 210, "odds": 2, "stake": 10},
    {"market": "spread", "side": "home", "odds": 2, "stake": 10},
    {"market": "total", "side": "over", "odds": 2, "stake": 10},
    {"market": "total", "side": "over", "line": 0, "odds": 2, "stake": 10},
    {"market": "moneyline", "side": "home", "line": -3, "odds": 2, "stake": 10},
    {"market": "moneyline", "side": "home", "odds": 1, "stake": 10},
    {"market": "moneyline", "side": "home", "odds": 2, "stake": 0},
    {"market": "parlay", "side": "home", "odds": 2, "stake": 10},
])
def test_bets_are_validated(
    games: tuple[TestClient, list[str], list[str]], payload: dict[str, Any]
) -> None:
    client, d1, _ = games
    assert client.post("/api/bets", json={"game_id": d1[0], **payload}).status_code == 422
    assert bankroll(client)["bets"] == []


def test_a_bet_needs_a_known_game(games: tuple[TestClient, list[str], list[str]]) -> None:
    client, _, _ = games
    body = {"market": "moneyline", "side": "home", "odds": 2, "stake": 10}
    assert client.post("/api/bets", json={"game_id": "0029999999", **body}).status_code == 404
    assert client.post("/api/bets", json={"game_id": "../x", **body}).status_code == 422


def test_delete_a_bet(games: tuple[TestClient, list[str], list[str]]) -> None:
    client, d1, _ = games
    bet = place(client, game_id=d1[0], market="moneyline", side="away", odds=2.2, stake=10)
    assert client.delete(f"/api/bets/{bet['bet_id']}").status_code == 204
    assert bankroll(client)["bets"] == []
    assert client.delete(f"/api/bets/{bet['bet_id']}").status_code == 404


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},
    {"Sec-Fetch-Site": "cross-site"},
])
def test_cross_site_writes_are_refused(
    games: tuple[TestClient, list[str], list[str]], headers: dict[str, str]
) -> None:
    client, d1, _ = games
    bet = {"game_id": d1[0], "market": "moneyline", "side": "home", "odds": 2, "stake": 10}
    assert client.post("/api/bets", json=bet, headers=headers).status_code == 403
    assert client.put("/api/bankroll", json={"starting": 1, "unit_pct": 1},
                      headers=headers).status_code == 403
    placed = place(client, **bet)
    assert client.delete(f"/api/bets/{placed['bet_id']}", headers=headers).status_code == 403
    assert len(bankroll(client)["bets"]) == 1
