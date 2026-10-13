from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import duckdb
from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware

from avaris.api.deps import LOOPBACK_HOSTS, Cursor, Jobs, json_value
from avaris.api.routes import backtests, games, injuries, jobs, performance, predictions, teams
from avaris.config import Settings
from avaris.db import connect
from avaris.pipeline.jobs import Clock, JobManager, JobRunner, default_runners, utc_now

# Local-only: no traces, metrics or logs leave the process
TELEMETRY_OFF: Any = {"tracing": False, "metrics": False, "logs": False, "auto_configure": False}


def create_app(
    settings: Settings,
    con: duckdb.DuckDBPyConnection | None = None,
    daily_on_startup: bool | None = None,
    clock: Clock = utc_now,
    runners: Mapping[str, JobRunner] | None = None,
) -> FastAPI:
    # The app owns the one read-write DuckDB connection unless given one; requests read
    # through cursors, jobs write in a background thread
    on_startup = settings.server.daily_on_startup if daily_on_startup is None else daily_on_startup

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = con is None
        connection = connect(settings.paths.db_path) if con is None else con
        app.state.con = connection
        app.state.settings = settings
        app.state.clock = clock
        app.state.jobs = JobManager(connection, runners or default_runners(settings, clock),
                                    clock)
        if on_startup:
            app.state.jobs.submit("daily", {})
        yield
        # A job still running keeps the connection; the process exit releases it
        if owned and app.state.jobs.current is None:
            connection.close()

    app = FastAPI(title="Avaris", lifespan=lifespan, telemetry=TELEMETRY_OFF)
    # DNS rebinding: a remote page resolved to 127.0.0.1 still sends its own host name
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(LOOPBACK_HOSTS))
    for module in (predictions, games, teams, performance, backtests, injuries, jobs):
        app.include_router(module.router)

    @app.get("/api/health")
    def health(cur: Cursor, jobs: Jobs) -> dict[str, Any]:
        row = cur.execute("select max(version) from schema_version").fetchone()
        current = jobs.current
        job = {k: json_value(v) for k, v in current.public().items()} if current else None
        return {"status": "ok", "schema_version": row[0] if row else None, "job": job}

    return app
