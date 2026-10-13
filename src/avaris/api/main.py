from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import duckdb
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from avaris.api.deps import LOOPBACK_HOSTS, Cursor, Jobs, json_value
from avaris.api.routes import backtests, games, injuries, jobs, performance, predictions, teams
from avaris.config import Settings
from avaris.db import connect
from avaris.pipeline.jobs import Clock, JobManager, JobRunner, default_runners, utc_now
from avaris.seasons import et_date

# Local-only: no traces, metrics or logs leave the process
TELEMETRY_OFF: Any = {"tracing": False, "metrics": False, "logs": False, "auto_configure": False}
# `next dev` on another loopback port; anchored so localhost.evil.example does not match
LOOPBACK_ORIGIN = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:[0-9]+)?$"


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
    if settings.server.dev_cors:
        # Dev only: job posts from loopback origins are already allowed (not_cross_site)
        app.add_middleware(CORSMiddleware, allow_origin_regex=LOOPBACK_ORIGIN,
                           allow_methods=["GET", "POST"], allow_headers=["content-type"])
    for module in (predictions, games, teams, performance, backtests, injuries, jobs):
        app.include_router(module.router)

    @app.get("/api/health")
    def health(cur: Cursor, jobs: Jobs) -> dict[str, Any]:
        row = cur.execute("select max(version) from schema_version").fetchone()
        current = jobs.current
        job = {k: json_value(v) for k, v in current.public().items()} if current else None
        return {"status": "ok", "schema_version": row[0] if row else None,
                "today": et_date(app.state.clock()).isoformat(), "job": job}

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                   include_in_schema=False)
    def unknown_api(path: str) -> None:
        # Before the static mount, so an API typo is a JSON 404 rather than the 404 page
        raise HTTPException(404, f"no endpoint /api/{path}")

    if settings.server.web_dir.is_dir():
        # The PWA's static export (trailingSlash: /game/ is game/index.html; 404.html)
        app.mount("/", StaticFiles(directory=settings.server.web_dir, html=True), name="web")
    return app
