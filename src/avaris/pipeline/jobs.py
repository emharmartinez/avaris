import json
import threading
import traceback
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import duckdb

from avaris.config import Settings
from avaris.features.build import build_features
from avaris.models.dataset import with_targets
from avaris.models.ladder import TARGETS
from avaris.seasons import et_date

Progress = Callable[[str], None]
# A job body: a cursor of the server's read-write connection, the request params and a
# progress callback; returns a one-line result message
JobRunner = Callable[[duckdb.DuckDBPyConnection, dict[str, Any], Progress], str]
Clock = Callable[[], datetime]
LOG_LINES = 200  # log tail kept per job


def utc_now() -> datetime:
    # Naive UTC, like every stored timestamp
    return datetime.now(UTC).replace(tzinfo=None)


class JobBusy(Exception):
    def __init__(self, job_id: str, kind: str) -> None:
        super().__init__(f"job {job_id} ({kind}) is running")
        self.job_id = job_id
        self.kind = kind


class JobsClosed(JobBusy):
    # The server is stopping: no new job may start
    def __init__(self) -> None:
        Exception.__init__(self, "the server is stopping")
        self.job_id = "stopping"
        self.kind = "?"


@dataclass
class Job:
    job_id: str
    kind: str
    params: dict[str, Any]
    created_at: datetime
    status: str = "running"
    finished_at: datetime | None = None
    message: str | None = None
    log: list[str] = field(default_factory=list)
    thread: threading.Thread | None = None

    def public(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id, "kind": self.kind, "status": self.status,
            "params": self.params, "created_at": self.created_at,
            "finished_at": self.finished_at, "message": self.message, "log": list(self.log),
        }


class JobManager:
    # One job at a time in a background thread (DuckDB has one writer); jobs are recorded
    # in the jobs table
    def __init__(
        self, con: duckdb.DuckDBPyConnection, runners: Mapping[str, JobRunner],
        clock: Clock = utc_now,
    ) -> None:
        self.con = con
        self.runners = dict(runners)
        self.clock = clock
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}  # this process's jobs, by ID
        self._current: Job | None = None
        self._closed = False
        with con.cursor() as cur:
            cur.execute(
                "update jobs set status = 'failed', finished_at = ?, "
                "message = 'interrupted (server stopped)' where status = 'running'",
                [clock()],
            )

    @property
    def current(self) -> Job | None:
        return self._current

    def submit(self, kind: str, params: dict[str, Any]) -> Job:
        if kind not in self.runners:
            raise ValueError(f"unknown job kind {kind!r}")
        if self._closed:
            raise JobsClosed()
        if not self._lock.acquire(blocking=False):
            if self._closed:
                raise JobsClosed()
            running = self._current  # None while a finished job releases the lock
            raise JobBusy(running.job_id if running else "finishing",
                          running.kind if running else "?")
        try:
            job = Job(uuid.uuid4().hex[:12], kind, params, self.clock())
            with self.con.cursor() as cur:
                cur.execute(
                    "insert into jobs (job_id, kind, status, params, created_at) "
                    "values (?, ?, 'running', ?, ?)",
                    [job.job_id, kind, json.dumps(params, default=str), job.created_at],
                )
            self._jobs[job.job_id] = job
            self._current = job
            job.thread = threading.Thread(target=self._run, args=(job,), daemon=True,
                                          name=f"avaris-job-{kind}")
            job.thread.start()
        except BaseException:
            self._current = None
            self._lock.release()
            raise
        return job

    def close(self) -> bool:
        # Before the server stops: take the job lock for good, so nothing starts between the
        # decision to stop and the exit. False while a job runs
        if not self._lock.acquire(blocking=False):
            return False
        self._closed = True
        return True

    def _run(self, job: Job) -> None:
        def progress(line: str) -> None:
            job.log.extend(line.splitlines() or [""])
            del job.log[:-LOG_LINES]

        try:
            with self.con.cursor() as cur:
                job.message = self.runners[job.kind](cur, job.params, progress)
            job.status = "succeeded"
        except BaseException as exc:
            job.status = "failed"
            job.message = f"{type(exc).__name__}: {exc}"
            progress(traceback.format_exc().rstrip())
            if not isinstance(exc, Exception):
                raise
        finally:
            job.finished_at = self.clock()
            try:
                with self.con.cursor() as cur:
                    cur.execute(
                        "update jobs set status = ?, finished_at = ?, message = ?, log = ? "
                        "where job_id = ?",
                        [job.status, job.finished_at, job.message, "\n".join(job.log),
                         job.job_id],
                    )
            finally:
                self._current = None
                self._lock.release()

    def wait(self, job_id: str, timeout: float | None = None) -> dict[str, Any]:
        job = self._jobs[job_id]
        if job.thread is not None:
            job.thread.join(timeout)
        return job.public()

    def get(self, job_id: str) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        if job is not None:
            return job.public()
        with self.con.cursor() as cur:
            rows = _rows(cur.execute("select * from jobs where job_id = ?", [job_id]))
        return rows[0] if rows else None

    def recent(self, limit: int) -> list[dict[str, Any]]:
        with self.con.cursor() as cur:
            ids = [r[0] for r in cur.execute(
                "select job_id from jobs order by created_at desc, job_id limit ?", [limit]
            ).fetchall()]
        return [job for job_id in ids if (job := self.get(job_id)) is not None]


def _rows(cur: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    names = [d[0] for d in cur.description or []]
    out = []
    for values in cur.fetchall():
        row = dict(zip(names, values, strict=True))
        row["params"] = json.loads(row["params"]) if row["params"] else {}
        row["log"] = row["log"].split("\n") if row["log"] else []
        out.append(row)
    return out


def default_runners(settings: Settings, clock: Clock = utc_now) -> dict[str, JobRunner]:
    # daily: {offline}; score: {}; train: {through, target}
    from avaris.pipeline.daily import run_daily, source_refresher
    from avaris.pipeline.score import score_predictions
    from avaris.pipeline.train import train

    def daily(cur: duckdb.DuckDBPyConnection, params: dict[str, Any], progress: Progress) -> str:
        refresh = None if params.get("offline") else source_refresher(settings)
        s = run_daily(cur, settings, now=clock(), refresh=refresh, progress=progress)
        for warning in s.warnings:
            progress(f"WARNING {warning}")
        return (f"{s.provisional} provisional, {s.final} final, {s.unchanged} unchanged, "
                f"{s.scored} scored" + (f", retrained ({len(s.retrained)})" if s.retrained
                                         else ""))

    def score(cur: duckdb.DuckDBPyConnection, params: dict[str, Any], progress: Progress) -> str:
        return f"{score_predictions(cur, clock())} scored"

    def train_job(
        cur: duckdb.DuckDBPyConnection, params: dict[str, Any], progress: Progress
    ) -> str:
        now = clock()
        through = date.fromisoformat(params["through"]) if params.get("through") else et_date(now)
        targets = tuple(params.get("target") or TARGETS)
        data = with_targets(build_features(cur).features, cur)
        lines = []
        for r in train(data, settings.models, through, targets, now=now):
            status = "promoted" if r.decision.promoted else "candidate (" + "; ".join(
                r.decision.reasons) + ")"
            lines.append(f"{r.target}: run {r.run_id}, {r.meta['rung']}, {r.meta['n_rows']} "
                         f"rows, OOF {r.meta['oof_metric']:.4f}: {status}")
            progress(lines[-1])
        return f"trained {len(lines)} target(s)"

    return {"daily": daily, "score": score, "train": train_job}
