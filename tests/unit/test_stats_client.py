from pathlib import Path

import httpx
import pytest
import respx

from avaris.ingest.stats_client import (
    BASE_URL,
    EmptyResponseError,
    RawCache,
    StatsClient,
    Throttle,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


ROWS = {"resultSets": [{"name": "LeagueGameLog", "headers": ["A"], "rowSet": [[1]]}]}


def make_client(tmp_path: Path, clock: FakeClock | None = None, attempts: int = 3) -> StatsClient:
    clock = clock or FakeClock()
    return StatsClient(
        cache=RawCache(tmp_path / "cache"),
        throttle=Throttle(1.0, clock=clock.monotonic, sleep=clock.sleep),
        timeout_s=5.0,
        max_attempts=attempts,
        retry_wait_s=0.0,
    )


def test_throttle_spaces_calls() -> None:
    clock = FakeClock()
    throttle = Throttle(1.0, clock=clock.monotonic, sleep=clock.sleep)
    throttle.wait()
    assert clock.sleeps == []
    clock.now += 0.25
    throttle.wait()
    assert clock.sleeps == [pytest.approx(0.75)]
    clock.now += 5
    throttle.wait()
    assert len(clock.sleeps) == 1


def test_cache_roundtrip_and_key_ignores_param_order(tmp_path: Path) -> None:
    cache = RawCache(tmp_path)
    cache.put("leaguegamelog", {"Season": "2019-20", "PlayerOrTeam": "T"}, {"a": 1})
    assert cache.get("leaguegamelog", {"PlayerOrTeam": "T", "Season": "2019-20"}) == {"a": 1}
    assert cache.get("leaguegamelog", {"PlayerOrTeam": "P", "Season": "2019-20"}) is None


def test_live_cache_writes_are_never_read_back(tmp_path: Path) -> None:
    cache = RawCache(tmp_path)
    cache.put("scheduleleaguev2", {"Season": "2026-27"}, {"x": 1}, final=False)
    assert cache.get("scheduleleaguev2", {"Season": "2026-27"}) is None
    assert any((tmp_path / "live").rglob("*.json.gz"))


@respx.mock
def test_fetch_sends_browser_headers_and_caches(tmp_path: Path) -> None:
    route = respx.get(f"{BASE_URL}/leaguegamelog").mock(
        return_value=httpx.Response(200, json=ROWS)
    )
    client = make_client(tmp_path)
    params = {"Season": "2019-20"}
    assert client.get_json("leaguegamelog", params, final=True) == ROWS
    assert client.get_json("leaguegamelog", params, final=True) == ROWS
    assert route.call_count == 1
    request = route.calls[0].request
    assert request.headers["Referer"] == "https://www.nba.com/"
    assert "Chrome" in request.headers["User-Agent"]
    assert request.url.params["Season"] == "2019-20"


@respx.mock
def test_non_final_requests_always_refetch(tmp_path: Path) -> None:
    route = respx.get(f"{BASE_URL}/scheduleleaguev2").mock(
        return_value=httpx.Response(200, json={"v": 1})
    )
    client = make_client(tmp_path)
    client.get_json("scheduleleaguev2", {"Season": "2026-27"}, final=False)
    client.get_json("scheduleleaguev2", {"Season": "2026-27"}, final=False)
    assert route.call_count == 2


@respx.mock
def test_retries_timeouts_and_5xx(tmp_path: Path) -> None:
    route = respx.get(f"{BASE_URL}/leaguegamelog").mock(
        side_effect=[
            httpx.ReadTimeout("slow"),
            httpx.Response(503),
            httpx.Response(200, json=ROWS),
        ]
    )
    client = make_client(tmp_path, attempts=3)
    assert client.get_json("leaguegamelog", {"Season": "2019-20"}, final=True) == ROWS
    assert route.call_count == 3


@respx.mock
def test_gives_up_after_max_attempts(tmp_path: Path) -> None:
    respx.get(f"{BASE_URL}/leaguegamelog").mock(side_effect=httpx.ReadTimeout("slow"))
    client = make_client(tmp_path, attempts=2)
    with pytest.raises(httpx.ReadTimeout):
        client.get_json("leaguegamelog", {"Season": "2019-20"}, final=True)


@respx.mock
def test_does_not_retry_4xx(tmp_path: Path) -> None:
    route = respx.get(f"{BASE_URL}/leaguegamelog").mock(return_value=httpx.Response(400))
    client = make_client(tmp_path, attempts=3)
    with pytest.raises(httpx.HTTPStatusError):
        client.get_json("leaguegamelog", {"Season": "2019-20"}, final=True)
    assert route.call_count == 1


@respx.mock
def test_each_attempt_is_throttled(tmp_path: Path) -> None:
    respx.get(f"{BASE_URL}/leaguegamelog").mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json=ROWS)]
    )
    clock = FakeClock()
    client = make_client(tmp_path, clock=clock)
    client.get_json("leaguegamelog", {"Season": "2019-20"}, final=True)
    assert clock.sleeps == [pytest.approx(1.0)]


@respx.mock
def test_empty_final_payload_is_retried_and_never_cached(tmp_path: Path) -> None:
    empty = {"resultSets": [{"name": "LeagueGameLog", "headers": [], "rowSet": []}]}
    route = respx.get(f"{BASE_URL}/leaguegamelog").mock(
        return_value=httpx.Response(200, json=empty)
    )
    client = make_client(tmp_path, attempts=2)
    with pytest.raises(EmptyResponseError):
        client.get_json("leaguegamelog", {"Season": "2019-20"}, final=True)
    assert route.call_count == 2
    assert client.cache.get("leaguegamelog", {"Season": "2019-20"}) is None


@respx.mock
def test_empty_final_schedule_is_rejected(tmp_path: Path) -> None:
    empty = {"leagueSchedule": {"seasonYear": "2019-20", "gameDates": []}}
    respx.get(f"{BASE_URL}/scheduleleaguev2").mock(return_value=httpx.Response(200, json=empty))
    with pytest.raises(EmptyResponseError):
        make_client(tmp_path, attempts=1).get_json(
            "scheduleleaguev2", {"Season": "2019-20"}, final=True
        )


@respx.mock
def test_empty_live_payload_is_accepted(tmp_path: Path) -> None:
    empty = {"resultSets": [{"name": "LeagueGameLog", "headers": [], "rowSet": []}]}
    respx.get(f"{BASE_URL}/leaguegamelog").mock(return_value=httpx.Response(200, json=empty))
    assert make_client(tmp_path).get_json("leaguegamelog", {"Season": "2026-27"}, final=False)
