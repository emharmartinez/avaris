# The traditional model's endpoint: pregame lines from features, live lines from an injected
# scoreboard (no network)
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient

from avaris.api.main import create_app
from avaris.config import Settings
from avaris.ingest.scoreboard import GameKey, LiveGame, first_live, parse_scoreboard
from avaris.traditional.pregame import SIGMA_MARGIN
from tests.fixtures.live import D1, D2, scoreboard_payload
from tests.fixtures.synthetic import BKN, BOS
from tests.integration.test_api import NOON_D2, env, get, live_db  # noqa: F401

BOS_AT_BKN = "0022100048"
TIPPED = datetime(2021, 11, 28, 0, 30)  # 19:30 ET on D2: the D2 games tipped at 19:00 ET
TEAMS = {"home_team": BKN, "away_team": BOS}
LIVE = scoreboard_payload({"game_id": BOS_AT_BKN, **TEAMS, "period": 2, "clock": "PT05M00.00S",
                           "home": 50, "away": 45})


class Feed:
    def __init__(self, payload: dict[str, Any] | Exception = LIVE) -> None:
        self.payload = payload
        self.days: list[date] = []

    def __call__(self, day: date) -> dict[GameKey, LiveGame]:
        self.days.append(day)
        if isinstance(self.payload, Exception):
            raise self.payload
        return parse_scoreboard(self.payload)


Env = tuple[duckdb.DuckDBPyConnection, Settings]


@pytest.fixture
def make_client(env: Env) -> Iterator[Callable[..., TestClient]]:  # noqa: F811
    con, settings = env
    opened: list[TestClient] = []

    def make(feed: Callable[[date], dict[GameKey, LiveGame]], now: datetime = NOON_D2,
             monotonic: Callable[[], float] = lambda: 0.0) -> TestClient:
        app = create_app(settings, con=con, daily_on_startup=False, clock=lambda: now,
                         live_scoreboard=feed, monotonic=monotonic)
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        opened.append(client.__enter__())
        return client

    yield make
    for client in opened:
        client.__exit__(None, None, None)


def by_id(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {g["game_id"]: g for g in body["games"]}


def test_pregame_lines_before_tip_fetch_nothing(make_client: Callable[..., TestClient]) -> None:
    feed = Feed()
    body = get(make_client(feed), "/api/traditional")
    assert body["date"] == D2.isoformat() and body["is_today"] is True
    assert feed.days == [] and body["live_error"] is None
    assert len(body["games"]) == 2
    for g in body["games"]:
        assert g["status"] == "scheduled" and g["score"] is None and g["live"] is None
        pre = g["pregame"]
        assert 0 < pre["p_home_win"] < 1
        assert pre["margin"]["sigma"] == SIGMA_MARGIN
        for target in ("margin", "total"):
            assert pre[target]["lo"] < pre[target]["mu"] < pre[target]["hi"]
        assert {"elo_margin", "eff_margin", "weight", "home_b2b"} <= set(pre["inputs"])
        assert g["home"]["abbreviation"] and g["tip_off_utc"].endswith("Z")


def test_past_date_shows_finals_with_pregame_lines(
    make_client: Callable[..., TestClient],
) -> None:
    feed = Feed()
    body = get(make_client(feed), f"/api/traditional?date={D1.isoformat()}")
    assert body["is_today"] is False and feed.days == []
    for g in body["games"]:
        assert g["status"] == "final"
        assert g["score"] == {"home_pts": 110, "away_pts": 100}
        assert g["pregame"] is not None and g["live"] is None


def test_live_game_updates_from_the_scoreboard(make_client: Callable[..., TestClient]) -> None:
    feed = Feed()
    body = get(make_client(feed, now=TIPPED), "/api/traditional")
    assert feed.days == [D2]
    assert body["live_at"].endswith("Z") and body["live_error"] is None
    game = by_id(body)[BOS_AT_BKN]
    assert game["status"] == "in_progress"
    assert game["score"] == {"home_pts": 50, "away_pts": 45}
    live = game["live"]
    assert (live["period"], live["clock"], live["label"]) == (2, "5:00", "2nd Qtr")
    assert live["minutes_left"] == pytest.approx(29.0)
    pre = game["pregame"]["margin"]["mu"]
    assert live["margin"]["mu"] == pytest.approx(5 + pre * 29 / 48)
    assert live["margin"]["sigma"] < SIGMA_MARGIN
    # The other game is not on the scoreboard: the schedule's status stands
    other = next(g for g in body["games"] if g["game_id"] != BOS_AT_BKN)
    assert other["status"] == "scheduled" and other["live"] is None


def test_final_on_the_scoreboard_before_the_schedule_catches_up(
    make_client: Callable[..., TestClient],
) -> None:
    feed = Feed(scoreboard_payload({"game_id": BOS_AT_BKN, **TEAMS, "status": 3, "label": "Final",
                                    "period": 4, "clock": "", "home": 101, "away": 99}))
    game = by_id(get(make_client(feed, now=TIPPED), "/api/traditional"))[BOS_AT_BKN]
    assert game["status"] == "final" and game["live"] is None
    assert game["score"] == {"home_pts": 101, "away_pts": 99}


def test_scoreboard_is_cached_for_the_ttl(make_client: Callable[..., TestClient]) -> None:
    feed, now = Feed(), [0.0]
    client = make_client(feed, now=TIPPED, monotonic=lambda: now[0])
    get(client, "/api/traditional")
    now[0] = 4.0
    get(client, "/api/traditional")
    assert len(feed.days) == 1
    now[0] = 6.0
    get(client, "/api/traditional")
    assert len(feed.days) == 2


def test_feed_failure_keeps_the_pregame_lines(make_client: Callable[..., TestClient]) -> None:
    feed = Feed(RuntimeError("blocked"))
    body = get(make_client(feed, now=TIPPED), "/api/traditional")
    assert body["live_error"] and body["live_at"] is None
    game = by_id(body)[BOS_AT_BKN]
    assert game["status"] == "scheduled" and game["live"] is None
    assert game["pregame"] is not None


def test_a_failed_primary_feed_falls_back(make_client: Callable[..., TestClient]) -> None:
    # ESPN down: stats.nba.com's scoreboard still gives the live line
    espn, stats = Feed(RuntimeError("espn down")), Feed()
    client = make_client(first_live(espn, stats), now=TIPPED)
    body = get(client, "/api/traditional")
    assert espn.days == stats.days == [D2] and body["live_error"] is None
    assert by_id(body)[BOS_AT_BKN]["live"]["label"] == "2nd Qtr"


def test_in_progress_schedule_status_fetches_before_the_listed_tip(
    env: Env,  # noqa: F811
    make_client: Callable[..., TestClient],
) -> None:
    env[0].execute("update games set status = 'in_progress' where game_id = ?", [BOS_AT_BKN])
    feed = Feed()
    body = get(make_client(feed), "/api/traditional")
    assert feed.days == [D2]
    assert by_id(body)[BOS_AT_BKN]["live"] is not None


def test_a_late_game_stays_live_past_midnight_et(
    make_client: Callable[..., TestClient],
) -> None:
    feed = Feed()
    after_midnight = datetime(2021, 11, 28, 5, 30)  # 00:30 ET on the day after D2
    body = get(make_client(feed, now=after_midnight), "/api/traditional")
    assert body["date"] == D2.isoformat() and body["is_today"] is True
    assert feed.days == [D2]
    assert by_id(body)[BOS_AT_BKN]["live"] is not None


def test_a_game_without_features_has_no_lines(
    env: Env,  # noqa: F811
    make_client: Callable[..., TestClient],
) -> None:
    env[0].execute("delete from features where game_id = ?", [BOS_AT_BKN])
    game = by_id(get(make_client(Feed(), now=TIPPED), "/api/traditional"))[BOS_AT_BKN]
    assert game["pregame"] is None and game["live"] is None
    assert game["status"] == "in_progress"
    assert game["score"] == {"home_pts": 50, "away_pts": 45}


def test_a_day_without_games(make_client: Callable[..., TestClient]) -> None:
    day = D2 + timedelta(days=30)
    body = get(make_client(Feed()), f"/api/traditional?date={day.isoformat()}")
    assert body == {"date": day.isoformat(), "is_today": False, "live_at": None,
                    "live_error": None, "games": []}
