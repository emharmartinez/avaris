# The API as the PWA's host: static export, dev-only loopback CORS, JSON 404s under /api,
# idle shutdown and the stop button
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from avaris.api.main import create_app
from avaris.config import PathsSettings, ServerSettings, Settings
from avaris.db import connect

NOW = datetime(2021, 11, 27, 3, 30)  # 22:30 ET on 2021-11-26


def make_web(root: Path) -> Path:
    web = root / "out"
    (web / "game").mkdir(parents=True)
    (web / "index.html").write_text("<html>today</html>")
    (web / "game" / "index.html").write_text("<html>game</html>")
    (web / "404.html").write_text("<html>not found</html>")
    (web / "sw.js").write_text("self.addEventListener('fetch', () => {})")
    (web / "_next" / "static" / "chunks").mkdir(parents=True)
    (web / "_next" / "static" / "chunks" / "a1b2.js").write_text("// chunk")
    return web


def make_client(tmp_path: Path, **server: object) -> Iterator[TestClient]:
    settings = Settings(paths=PathsSettings(db_path=tmp_path / "a.duckdb"),
                        server=ServerSettings.model_validate(server))
    con = connect(settings.paths.db_path)
    app = create_app(settings, con=con, daily_on_startup=False, clock=lambda: NOW)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        yield client
    con.close()


@pytest.fixture
def web_client(tmp_path: Path) -> Iterator[TestClient]:
    yield from make_client(tmp_path, web_dir=make_web(tmp_path))


@pytest.fixture
def dev_client(tmp_path: Path) -> Iterator[TestClient]:
    yield from make_client(tmp_path, dev_cors=True, web_dir=tmp_path / "missing")


@pytest.fixture
def plain_client(tmp_path: Path) -> Iterator[TestClient]:
    yield from make_client(tmp_path, web_dir=tmp_path / "missing")


def test_health_reports_today_by_the_app_clock(plain_client: TestClient) -> None:
    body = plain_client.get("/api/health").json()
    assert body["today"] == "2021-11-26"
    assert body["now"] == "2021-11-27T03:30:00Z"


def test_serves_the_static_export(web_client: TestClient) -> None:
    assert web_client.get("/").text == "<html>today</html>"
    assert web_client.get("/game/?id=0022100001").text == "<html>game</html>"
    assert web_client.get("/game", follow_redirects=False).status_code in (307, 308)
    missing = web_client.get("/nope/")
    assert missing.status_code == 404 and missing.text == "<html>not found</html>"
    assert web_client.get("/sw.js").status_code == 200
    assert web_client.get("/api/health").json()["status"] == "ok"


def test_pages_revalidate_and_hashed_assets_are_immutable(web_client: TestClient) -> None:
    # A heuristically cached page from an older build asks for chunks that no longer exist
    for path in ("/", "/game/?id=0022100001", "/sw.js", "/nope/", "/_next/static/chunks/gone.js"):
        assert web_client.get(path).headers["cache-control"] == "no-cache", path
    chunk = web_client.get("/_next/static/chunks/a1b2.js")
    assert chunk.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "cache-control" not in web_client.get("/api/health").headers


def test_unknown_api_paths_are_json_404s(web_client: TestClient) -> None:
    for method in ("GET", "POST"):
        response = web_client.request(method, "/api/nope")
        assert response.status_code == 404
        assert response.headers["content-type"] == "application/json"


def test_no_static_mount_without_an_export(plain_client: TestClient) -> None:
    assert plain_client.get("/").status_code == 404


@pytest.mark.parametrize("origin", [
    "http://localhost:3000", "http://127.0.0.1:3000", "http://[::1]:3000", "http://localhost",
])
def test_dev_cors_allows_loopback_origins(dev_client: TestClient, origin: str) -> None:
    got = dev_client.get("/api/health", headers={"Origin": origin})
    assert got.headers["access-control-allow-origin"] == origin
    preflight = dev_client.options("/api/jobs/daily", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize(("path", "method"), [("/api/bankroll", "PUT"), ("/api/bets/1", "DELETE")])
def test_dev_cors_allows_bet_writes(dev_client: TestClient, path: str, method: str) -> None:
    preflight = dev_client.options(path, headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": "content-type",
    })
    assert preflight.status_code == 200
    assert method in preflight.headers["access-control-allow-methods"]


@pytest.mark.parametrize("origin", [
    "http://evil.example", "http://localhost.evil.example:3000", "http://127.0.0.1.nip.io",
    "null",
])
def test_dev_cors_refuses_other_origins(dev_client: TestClient, origin: str) -> None:
    got = dev_client.get("/api/health", headers={"Origin": origin})
    assert "access-control-allow-origin" not in got.headers
    preflight = dev_client.options("/api/jobs/daily", headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
    })
    assert "access-control-allow-origin" not in preflight.headers


def test_no_cors_headers_unless_dev(plain_client: TestClient) -> None:
    got = plain_client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    assert "access-control-allow-origin" not in got.headers


def test_every_response_refuses_framing_and_sniffing(web_client: TestClient) -> None:
    for url in ("/", "/api/health", "/api/nope"):
        headers = web_client.get(url).headers
        assert headers["x-frame-options"] == "DENY"
        assert headers["content-security-policy"] == "frame-ancestors 'none'"
        assert headers["x-content-type-options"] == "nosniff"


def test_dev_cors_preflight_still_checks_the_host(dev_client: TestClient) -> None:
    preflight = dev_client.options("/api/jobs/daily", headers={
        "Host": "evil.example", "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "POST",
    })
    assert preflight.status_code == 400


class Monotonic:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def lifecycle_client(
    tmp_path: Path, shutdown: Callable[[], None] | None, idle_min: float = 1,
    monotonic: Callable[[], float] = time.monotonic, runners: dict[str, Any] | None = None,
) -> tuple[Any, TestClient]:
    settings = Settings(paths=PathsSettings(db_path=tmp_path / "a.duckdb"),
                        server=ServerSettings(web_dir=tmp_path / "missing",
                                              idle_shutdown_min=idle_min))
    app = create_app(settings, con=connect(settings.paths.db_path), daily_on_startup=False,
                     clock=lambda: NOW, shutdown=shutdown, monotonic=monotonic,
                     idle_check_s=0.01, runners=runners)
    return app, TestClient(app, base_url="http://127.0.0.1:8000")


def test_stops_after_the_idle_timeout_without_requests(tmp_path: Path) -> None:
    stopped = threading.Event()
    clock = Monotonic()
    _, client = lifecycle_client(tmp_path, stopped.set, idle_min=1, monotonic=clock)
    with client:
        clock.t = 50
        client.get("/api/health")  # any request resets the countdown
        clock.t = 105
        assert not stopped.wait(0.2)
        clock.t = 110
        assert stopped.wait(2)


def test_cross_site_requests_do_not_keep_the_server_up(tmp_path: Path) -> None:
    # Only the app counts: another site's request to 127.0.0.1 must not reset the countdown
    stopped = threading.Event()
    clock = Monotonic()
    _, client = lifecycle_client(tmp_path, stopped.set, idle_min=1, monotonic=clock)
    with client:
        clock.t = 50
        client.get("/api/health")
        clock.t = 100
        client.get("/api/health", headers={"Sec-Fetch-Site": "cross-site"})
        client.post("/api/server/stop", headers={"Origin": "https://evil.example"})
        clock.t = 110
        assert stopped.wait(2)


def test_idle_shutdown_is_off_at_zero_minutes(tmp_path: Path) -> None:
    stopped = threading.Event()
    clock = Monotonic()
    _, client = lifecycle_client(tmp_path, stopped.set, idle_min=0, monotonic=clock)
    with client:
        clock.t = 10_000
        assert not stopped.wait(0.2)


def test_idle_shutdown_waits_for_a_running_job(tmp_path: Path) -> None:
    stopped, started, release = threading.Event(), threading.Event(), threading.Event()
    clock = Monotonic()

    def slow(*_args: Any) -> str:
        started.set()
        assert release.wait(5)
        return "done"

    app, client = lifecycle_client(tmp_path, stopped.set, idle_min=1, monotonic=clock,
                                   runners={"daily": slow})
    with client:
        job_id = client.post("/api/jobs/daily").json()["job_id"]
        assert started.wait(5)
        clock.t = 1000
        assert not stopped.wait(0.2)
        release.set()
        app.state.jobs.wait(job_id)
        clock.t = 1059  # the countdown restarts once the job is done
        assert not stopped.wait(0.2)
        clock.t = 1061
        assert stopped.wait(2)


def test_the_stop_button_stops_the_server(tmp_path: Path) -> None:
    stopped = threading.Event()
    _, client = lifecycle_client(tmp_path, stopped.set, idle_min=0)
    with client:
        response = client.post("/api/server/stop")
        assert response.status_code == 202
        assert response.json() == {"status": "stopping"}
        assert stopped.wait(2)
        late = client.post("/api/jobs/daily")  # nothing starts while it shuts down
        assert late.status_code == 409
        assert "stopping" in late.json()["detail"]
        assert client.post("/api/server/stop").status_code == 202  # a second click is fine


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},
    {"Sec-Fetch-Site": "cross-site"},
])
def test_a_cross_site_stop_is_refused(tmp_path: Path, headers: dict[str, str]) -> None:
    stopped = threading.Event()
    _, client = lifecycle_client(tmp_path, stopped.set, idle_min=0)
    with client:
        assert client.post("/api/server/stop", headers=headers).status_code == 403
        assert client.get("/api/server/stop").status_code in (404, 405)
    assert not stopped.is_set()


def test_stop_is_refused_while_a_job_runs(tmp_path: Path) -> None:
    stopped, started, release = threading.Event(), threading.Event(), threading.Event()

    def slow(*_args: Any) -> str:
        started.set()
        assert release.wait(5)
        return "done"

    app, client = lifecycle_client(tmp_path, stopped.set, idle_min=0, runners={"daily": slow})
    with client:
        job_id = client.post("/api/jobs/daily").json()["job_id"]
        assert started.wait(5)
        busy = client.post("/api/server/stop")
        assert busy.status_code == 409
        assert "daily" in busy.json()["detail"]
        release.set()
        app.state.jobs.wait(job_id)
    assert not stopped.is_set()


def test_stop_is_unavailable_without_a_server_to_stop(tmp_path: Path) -> None:
    _, client = lifecycle_client(tmp_path, None, idle_min=0)
    with client:
        assert client.post("/api/server/stop").status_code == 503
