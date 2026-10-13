# The API as the PWA's host: static export, dev-only loopback CORS, JSON 404s under /api
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

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
