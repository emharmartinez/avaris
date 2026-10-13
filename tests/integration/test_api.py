import shutil
import threading
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest
from fastapi.testclient import TestClient

from avaris.api.main import create_app
from avaris.config import Settings
from avaris.db import connect
from avaris.pipeline.daily import run_daily
from avaris.pipeline.score import score_predictions
from tests.fixtures.live import D1, D2, models_settings, train_before_d1
from tests.fixtures.synthetic import ATL, BOS

NOON_D2 = datetime(2021, 11, 27, 17, 0)  # D1 games final (catch-up), D2 provisional


@pytest.fixture(scope="module")
def live_db(
    synthetic_db_template: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, Path]:
    root = tmp_path_factory.mktemp("api")
    db = root / "league.duckdb"
    shutil.copy(synthetic_db_template, db)
    train_before_d1(db, root / "artifacts")
    settings = Settings(models=models_settings(root / "artifacts"))
    con = connect(db)
    run_daily(con, settings, now=NOON_D2, refresh=None)
    con.execute("update games set home_pts = 110, away_pts = 100, status = 'final' "
                "where game_date_et = ?", [D1])
    score_predictions(con, NOON_D2)
    con.close()
    report = root / "artifacts" / "reports" / "evaluation_2020-21_2024-25"
    report.mkdir(parents=True)
    (report / "report.md").write_text("# Evaluation 2020-21 to 2024-25\n\nBody\n")
    (report / "reliability_home_win.svg").write_text("<svg></svg>\n")
    return db, root / "artifacts"


@pytest.fixture
def env(live_db: tuple[Path, Path], tmp_path: Path) -> Iterator[tuple[duckdb.DuckDBPyConnection,
                                                                       Settings]]:
    db, artifacts = live_db
    shutil.copy(db, tmp_path / "league.duckdb")
    shutil.copytree(artifacts, tmp_path / "artifacts")
    con = connect(tmp_path / "league.duckdb")
    yield con, Settings(models=models_settings(tmp_path / "artifacts"))
    con.close()


@pytest.fixture
def client(env: tuple[duckdb.DuckDBPyConnection, Settings]) -> Iterator[TestClient]:
    con, settings = env
    app = create_app(settings, con=con, daily_on_startup=False, clock=lambda: NOON_D2)
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        yield c


def get(client: TestClient, url: str) -> Any:
    response = client.get(url)
    assert response.status_code == 200, response.text
    return response.json()


def test_health(client: TestClient) -> None:
    body = get(client, "/api/health")
    assert body["status"] == "ok" and body["schema_version"] == 7 and body["job"] is None


def test_predictions_today(client: TestClient) -> None:
    body = get(client, "/api/predictions/today")
    assert body["date"] == D2.isoformat()
    games = body["games"]
    assert len(games) == 2
    for g in games:
        assert g["home"]["abbreviation"] and g["away"]["name"]
        assert g["tip_off_utc"].endswith("Z")
        p = g["prediction"]
        assert p["status"] == "provisional"
        assert 0 < p["p_home_win"] < 1
        for target in ("margin", "total"):
            assert p[target]["lo"] < p[target]["mu"] < p[target]["hi"]
            assert p[target]["sigma"] > 0
        assert set(p["top_drivers"]) == {"home_win", "margin", "total"}
        assert len(p["top_drivers"]["margin"]) == 3
        assert set(p["injury_impact"]) == {"home", "away"}
        assert p["decision_ts"].endswith("Z")


def test_predictions_by_date(client: TestClient) -> None:
    body = get(client, f"/api/predictions?date={D1.isoformat()}")
    assert [g["prediction"]["status"] for g in body["games"]] == ["final", "final"]
    assert all(g["result"] == {"home_pts": 110, "away_pts": 100} for g in body["games"])
    assert client.get("/api/predictions?date=yesterday").status_code == 422
    assert get(client, "/api/predictions?date=2030-01-01")["games"] == []


def test_game_detail(client: TestClient) -> None:
    game_id = get(client, f"/api/predictions?date={D1.isoformat()}")["games"][0]["game_id"]
    body = get(client, f"/api/games/{game_id}")
    assert body["game_id"] == game_id
    drivers = body["prediction"]["drivers"]
    assert set(drivers["margin"]["families"]) >= {"elo", "form", "availability"}
    assert body["prediction"]["injuries"]["home"]["full_strength"] > 0
    assert body["score"]["margin"] == 10
    assert isinstance(body["injury_report"], list)
    for side in ("home", "away"):
        trend = body["ratings"][side]
        assert trend and trend[-1]["as_of_ts"] <= body["prediction"]["decision_ts"]
        assert {"elo", "net", "pace"} <= set(trend[-1])


def test_game_detail_unknown(client: TestClient) -> None:
    assert client.get("/api/games/0029999999").status_code == 404
    assert client.get("/api/games/..%2Fetc").status_code in (404, 422)


def test_teams(client: TestClient) -> None:
    teams = get(client, "/api/teams")
    assert {t["team_id"] for t in teams} == {ATL, BOS, 1610612751, 1610612743}
    assert all(t["as_of_ts"] <= "2021-11-27T17:00:00Z" for t in teams)
    assert teams == sorted(teams, key=lambda t: -t["elo"])
    history = get(client, f"/api/teams/{ATL}")
    assert history["team"]["abbreviation"] == "ATL"
    assert history["season"] == "2021-22"
    assert len(history["ratings"]) > 10
    assert client.get("/api/teams/1").status_code == 404


def test_performance(client: TestClient) -> None:
    body = get(client, "/api/performance")
    assert body["season"] == "2021-22"
    regular = body["scopes"]["regular"]
    assert regular["n"] == 2
    assert regular["log_loss"] > 0 and 0 <= regular["margin_coverage_80"] <= 1
    assert body["scopes"]["preseason"]["n"] == 0
    assert "2021-22" in body["seasons"]


def test_backtests(client: TestClient) -> None:
    listed = get(client, "/api/backtests")
    assert listed == [{"name": "evaluation_2020-21_2024-25",
                       "title": "Evaluation 2020-21 to 2024-25"}]
    detail = get(client, "/api/backtests/evaluation_2020-21_2024-25")
    assert detail["markdown"].startswith("# Evaluation")
    assert detail["charts"] == ["reliability_home_win.svg"]
    chart = client.get("/api/backtests/evaluation_2020-21_2024-25/charts/reliability_home_win.svg")
    assert chart.status_code == 200
    assert chart.headers["content-type"].startswith("image/svg+xml")
    assert "default-src 'none'" in chart.headers["content-security-policy"]
    assert client.get("/api/backtests/..").status_code == 404
    base = "/api/backtests/evaluation_2020-21_2024-25/charts"
    assert client.get(f"{base}/report.md").status_code == 422
    assert client.get(f"{base}/missing.svg").status_code == 404


def test_injuries(client: TestClient) -> None:
    body = get(client, f"/api/injuries?date={D1.isoformat()}")
    assert len(body["games"]) == 2
    for g in body["games"]:
        assert set(g["impact"]) == {"home", "away"}
        assert isinstance(g["entries"], list)


def test_jobs_run_and_report_status(
    env: tuple[duckdb.DuckDBPyConnection, Settings],
) -> None:
    con, settings = env
    started, release = threading.Event(), threading.Event()

    def slow(*_args: Any) -> str:
        started.set()
        assert release.wait(5)
        return "slow done"

    app = create_app(settings, con=con, daily_on_startup=False, clock=lambda: NOON_D2,
                     runners={"daily": slow, "score": lambda *_: "0 scored",
                              "train": lambda *_: "trained"})
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        accepted = client.post("/api/jobs/daily", json={"offline": True})
        assert accepted.status_code == 202
        job_id = accepted.json()["job_id"]
        assert started.wait(5)
        busy = client.post("/api/jobs/score")
        assert busy.status_code == 409
        assert job_id in busy.json()["detail"]
        assert get(client, "/api/health")["job"]["job_id"] == job_id
        release.set()
        app.state.jobs.wait(job_id)
        status = get(client, f"/api/jobs/{job_id}")
        assert status["status"] == "succeeded" and status["message"] == "slow done"
        assert status["params"] == {"offline": True}
        assert client.post("/api/jobs/ingest").status_code == 422
        assert client.post("/api/jobs/train", json={"through": "not-a-date"}).status_code == 422
        assert client.get("/api/jobs/nope").status_code == 404
        assert [j["job_id"] for j in get(client, "/api/jobs")] == [job_id]


def test_serve_runs_daily_on_startup(env: tuple[duckdb.DuckDBPyConnection, Settings]) -> None:
    con, settings = env
    calls: list[dict[str, Any]] = []

    def daily(_cur: Any, params: dict[str, Any], _progress: Any) -> str:
        calls.append(params)
        return "ok"

    app = create_app(settings, con=con, daily_on_startup=True, clock=lambda: NOON_D2,
                     runners={"daily": daily})
    with TestClient(app, base_url="http://127.0.0.1:8000"):
        job = app.state.jobs.current or app.state.jobs.recent(1)[0]
        app.state.jobs.wait(job["job_id"] if isinstance(job, dict) else job.job_id)
    assert calls == [{}]


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},
    {"Sec-Fetch-Site": "cross-site"},
])
def test_cross_site_job_submission_is_refused(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.post("/api/jobs/score", headers=headers)
    assert response.status_code == 403
    assert client.get("/api/jobs").json() == []


def test_same_site_job_submission_is_accepted(client: TestClient) -> None:
    response = client.post("/api/jobs/score", headers={"Origin": "http://localhost:3000",
                                                       "Sec-Fetch-Site": "same-site"})
    assert response.status_code == 202
    job = client.app.state.jobs.wait(response.json()["job_id"])  # type: ignore[attr-defined]
    assert job["status"] == "succeeded"


def test_foreign_host_header_is_refused(client: TestClient) -> None:
    # DNS rebinding: a remote page resolved to 127.0.0.1 still sends its own host name
    assert client.get("/api/health", headers={"Host": "attacker.example"}).status_code == 400
    assert client.get("/api/health", headers={"Host": "127.0.0.1:8000"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "localhost:8000"}).status_code == 200
