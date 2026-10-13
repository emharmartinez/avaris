from collections.abc import Iterator
from pathlib import Path
from typing import Any

import duckdb
import httpx
import pytest
import respx
from typer.testing import CliRunner

from avaris import cli
from avaris.cli import app

runner = CliRunner()
SERVER = "http://127.0.0.1:8123"


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # The database is held by a running server
    def locked(*_args: Any, **_kwargs: Any) -> None:
        raise duckdb.IOException("Could not set lock on file")

    monkeypatch.setattr(cli, "connect", locked)
    monkeypatch.setattr(cli, "POLL_S", 0.0)
    path = tmp_path / "config.toml"
    path.write_text(f'[paths]\ndb_path = "{tmp_path / "a.duckdb"}"\n[server]\nport = 8123\n')
    return path


@pytest.fixture
def server() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=SERVER, assert_all_called=False) as router:
        yield router


def job(status: str, log: list[str], message: str | None = None) -> dict[str, Any]:
    return {"job_id": "j1", "kind": "daily", "status": status, "params": {"offline": True},
            "log": log, "message": message}


def test_locked_db_submits_the_job_to_the_server(
    config: Path, server: respx.MockRouter
) -> None:
    submit = server.post("/api/jobs/daily").mock(
        return_value=httpx.Response(202, json=job("running", [])))
    server.get("/api/jobs/j1").mock(side_effect=[
        httpx.Response(200, json=job("running", ["features: 10 games"])),
        httpx.Response(200, json=job("succeeded", ["features: 10 games", "predictions"],
                                     "2 provisional")),
    ])
    result = runner.invoke(app, ["--config", str(config), "daily", "--offline"])
    assert result.exit_code == 0, result.output
    assert submit.calls[0].request.content == b'{"offline":true}'
    assert result.output.count("features: 10 games") == 1
    assert "2 provisional" in result.output


def test_a_failed_server_job_exits_1(config: Path, server: respx.MockRouter) -> None:
    server.post("/api/jobs/score").mock(return_value=httpx.Response(202, json=job("running", [])))
    server.get("/api/jobs/j1").mock(
        return_value=httpx.Response(200, json=job("failed", ["boom"], "RuntimeError: boom")))
    result = runner.invoke(app, ["--config", str(config), "score"])
    assert result.exit_code == 1
    assert "RuntimeError: boom" in result.output


def test_busy_server_exits_1(config: Path, server: respx.MockRouter) -> None:
    server.post("/api/jobs/train").mock(
        return_value=httpx.Response(409, json={"detail": "job j0 (daily) is running"}))
    result = runner.invoke(app, ["--config", str(config), "train", "--through", "2026-10-12"])
    assert result.exit_code == 1
    assert "job j0 (daily) is running" in result.output


def test_locked_db_and_no_server_exits_1(config: Path, server: respx.MockRouter) -> None:
    server.post("/api/jobs/daily").mock(side_effect=httpx.ConnectError("refused"))
    result = runner.invoke(app, ["--config", str(config), "daily"])
    assert result.exit_code == 1
    assert "no Avaris server answers" in result.output


def test_a_failing_status_poll_exits_1(config: Path, server: respx.MockRouter) -> None:
    server.post("/api/jobs/score").mock(return_value=httpx.Response(202, json=job("running", [])))
    server.get("/api/jobs/j1").mock(return_value=httpx.Response(500, text="oops"))
    result = runner.invoke(app, ["--config", str(config), "score"])
    assert result.exit_code == 1
    assert "500" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def fake_uvicorn(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    # `serve` builds a uvicorn.Server; record its config instead of serving
    import uvicorn

    served: dict[str, Any] = {}

    class FakeServer:
        def __init__(self, config: dict[str, Any]) -> None:
            served.update(config)
            self.should_exit = False

        def run(self) -> None:
            served["server"] = self

    monkeypatch.setattr(uvicorn, "Config", lambda app, **kw: {"api": app, **kw})
    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    return served


@pytest.mark.parametrize(("args", "cors"), [(["--dev"], True), ([], False)])
def test_serve_dev_turns_on_loopback_cors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str], cors: bool
) -> None:
    served = fake_uvicorn(monkeypatch)
    path = tmp_path / "config.toml"
    path.write_text(f'[paths]\ndb_path = "{tmp_path / "a.duckdb"}"\n')
    result = runner.invoke(app, ["--config", str(path), "serve", "--no-daily", *args])
    assert result.exit_code == 0, result.output
    names = [m.cls.__name__ for m in served["api"].user_middleware]  # type: ignore[attr-defined]
    assert ("CORSMiddleware" in names) is cors
    assert served["host"] == "127.0.0.1"


def test_serve_warns_when_the_web_export_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_uvicorn(monkeypatch)
    path = tmp_path / "config.toml"
    path.write_text(f'[paths]\ndb_path = "{tmp_path / "a.duckdb"}"\n'
                    f'[server]\nweb_dir = "{tmp_path / "out"}"\n')
    result = runner.invoke(app, ["--config", str(path), "serve", "--no-daily"])
    assert result.exit_code == 0, result.output
    assert "npm run build" in result.output


def test_serve_wires_the_stop_callback_and_idle_minutes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import avaris.api.main as api_main

    served = fake_uvicorn(monkeypatch)
    built: dict[str, Any] = {}
    real_create_app = api_main.create_app

    def create_app(settings: Any, **kwargs: Any) -> Any:
        built.update(settings=settings, **kwargs)
        return real_create_app(settings, **kwargs)

    monkeypatch.setattr(api_main, "create_app", create_app)
    path = tmp_path / "config.toml"
    path.write_text(f'[paths]\ndb_path = "{tmp_path / "a.duckdb"}"\n')
    result = runner.invoke(app, ["--config", str(path), "serve", "--no-daily", "--idle-min", "2"])
    assert result.exit_code == 0, result.output
    assert built["settings"].server.idle_shutdown_min == 2
    built["shutdown"]()  # the Stop button or idle shutdown
    assert served["server"].should_exit is True
