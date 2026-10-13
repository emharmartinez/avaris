import threading
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest

from avaris.db import connect
from avaris.pipeline.jobs import JobBusy, JobManager, Progress

NOW = datetime(2026, 10, 12, 16, 0)


@pytest.fixture
def con(tmp_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    con = connect(tmp_path / "a.duckdb")
    yield con
    con.close()


class Gate:
    # A job runner that blocks until released
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.params: dict[str, Any] = {}

    def __call__(
        self, cur: duckdb.DuckDBPyConnection, params: dict[str, Any], progress: Progress
    ) -> str:
        self.params = params
        progress("working")
        self.started.set()
        assert self.release.wait(5)
        cur.execute("select 1")
        return "done"


def fail(cur: duckdb.DuckDBPyConnection, params: dict[str, Any], progress: Progress) -> str:
    progress("about to fail")
    raise RuntimeError("boom")


def manager(con: duckdb.DuckDBPyConnection, **runners: Any) -> JobManager:
    return JobManager(con, runners, clock=lambda: NOW)


def test_job_runs_in_the_background_and_is_recorded(con: duckdb.DuckDBPyConnection) -> None:
    gate = Gate()
    jobs = manager(con, daily=gate)
    job = jobs.submit("daily", {"offline": True})
    assert gate.started.wait(5)
    running = jobs.get(job.job_id)
    assert running is not None
    assert running["status"] == "running" and running["log"] == ["working"]
    gate.release.set()
    jobs.wait(job.job_id)
    done = jobs.get(job.job_id)
    assert done is not None
    assert done["status"] == "succeeded" and done["message"] == "done"
    assert done["log"] == ["working"] and done["params"] == {"offline": True}
    assert gate.params == {"offline": True}
    row = con.execute("select kind, status, message from jobs").fetchall()
    assert row == [("daily", "succeeded", "done")]


def test_a_second_job_is_refused_while_one_runs(con: duckdb.DuckDBPyConnection) -> None:
    gate = Gate()
    jobs = manager(con, daily=gate, score=gate)
    first = jobs.submit("daily", {})
    assert gate.started.wait(5)
    with pytest.raises(JobBusy) as busy:
        jobs.submit("score", {})
    assert busy.value.job_id == first.job_id
    gate.release.set()
    jobs.wait(first.job_id)
    gate.release.clear()
    gate.started.clear()
    second = jobs.submit("score", {})
    gate.release.set()
    jobs.wait(second.job_id)
    assert jobs.get(second.job_id)["status"] == "succeeded"  # type: ignore[index]


def test_a_failed_job_releases_the_lock(con: duckdb.DuckDBPyConnection) -> None:
    jobs = manager(con, train=fail, score=lambda *_: "ok")
    job = jobs.submit("train", {})
    jobs.wait(job.job_id)
    failed = jobs.get(job.job_id)
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["message"] == "RuntimeError: boom"
    assert failed["log"][0] == "about to fail"
    assert jobs.wait(jobs.submit("score", {}).job_id)["status"] == "succeeded"


def test_unknown_kind_is_refused(con: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(ValueError):
        manager(con, daily=lambda *_: "ok").submit("ingest", {})


def test_jobs_left_running_are_marked_interrupted(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        "insert into jobs (job_id, kind, status, created_at) values ('old', 'daily', "
        "'running', ?)", [NOW]
    )
    jobs = manager(con, daily=lambda *_: "ok")
    old = jobs.get("old")
    assert old is not None
    assert old["status"] == "failed" and old["message"] == "interrupted (server stopped)"
    assert jobs.get("missing") is None
    assert [j["job_id"] for j in jobs.recent(5)] == ["old"]


def test_close_refuses_new_jobs_once_none_runs(con: duckdb.DuckDBPyConnection) -> None:
    # Stopping the server closes the manager first, so no job can start in between
    gate = Gate()
    jobs = manager(con, daily=gate)
    first = jobs.submit("daily", {})
    assert gate.started.wait(5)
    assert jobs.close() is False  # a job runs: not closed
    gate.release.set()
    jobs.wait(first.job_id)
    assert jobs.close() is True
    with pytest.raises(JobBusy, match="stopping"):
        jobs.submit("daily", {})
