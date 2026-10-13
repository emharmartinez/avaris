import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any

import duckdb
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import Scope

from avaris.api.deps import LOOPBACK_HOSTS, Cursor, Jobs, json_value
from avaris.api.lifecycle import IdleWatch, Monotonic
from avaris.api.routes import (
    backtests,
    games,
    injuries,
    jobs,
    performance,
    predictions,
    server,
    teams,
)
from avaris.config import Settings
from avaris.db import connect
from avaris.pipeline.jobs import Clock, JobManager, JobRunner, default_runners, utc_now
from avaris.seasons import et_date

# Local-only: no traces, metrics or logs leave the process
TELEMETRY_OFF: Any = {"tracing": False, "metrics": False, "logs": False, "auto_configure": False}
# `next dev` on another loopback port; anchored so localhost.evil.example does not match
LOOPBACK_ORIGIN = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:[0-9]+)?$"
# Pages revalidate on every load: a page cached from an older build asks for chunks the
# rebuild deleted. Build assets under _next/static/ have hashed names, so never change
PAGE_CACHE = "no-cache"
ASSET_CACHE = "public, max-age=31536000, immutable"
log = logging.getLogger("uvicorn.error")


class WebFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        # A missing chunk's 404 page must not be cached for a year
        immutable = path.startswith("_next/static/") and response.status_code in (200, 304)
        response.headers["Cache-Control"] = ASSET_CACHE if immutable else PAGE_CACHE
        return response


# No page may frame the app (a framed Refresh button could be clickjacked); setdefault keeps
# the charts' stricter CSP
SECURITY_HEADERS = {
    "Content-Security-Policy": "frame-ancestors 'none'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
}


def create_app(
    settings: Settings,
    con: duckdb.DuckDBPyConnection | None = None,
    daily_on_startup: bool | None = None,
    clock: Clock = utc_now,
    runners: Mapping[str, JobRunner] | None = None,
    shutdown: Callable[[], None] | None = None,
    monotonic: Monotonic = time.monotonic,
    idle_check_s: float = 15.0,
) -> FastAPI:
    # The app owns the one read-write DuckDB connection unless given one; requests read
    # through cursors, jobs write in a background thread. `shutdown` stops the server (set by
    # `avaris serve`): the Stop server button, and idle shutdown once no request has come in
    # for `idle_shutdown_min` (the open app polls /api/health every minute)
    on_startup = settings.server.daily_on_startup if daily_on_startup is None else daily_on_startup
    idle_min = settings.server.idle_shutdown_min
    idle = IdleWatch(idle_min * 60, monotonic)

    async def watch_idle(app: FastAPI, stop: Callable[[], None]) -> None:
        while True:
            await asyncio.sleep(idle_check_s)
            if idle.expired(busy=app.state.jobs.current is not None):
                log.info("No requests for %g min: stopping (idle_shutdown_min)", idle_min)
                stop()
                return

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = con is None
        connection = connect(settings.paths.db_path) if con is None else con
        app.state.con = connection
        app.state.settings = settings
        app.state.clock = clock
        app.state.jobs = JobManager(connection, runners or default_runners(settings, clock),
                                    clock)
        app.state.shutdown = shutdown
        if on_startup:
            app.state.jobs.submit("daily", {})
        watcher = (asyncio.create_task(watch_idle(app, shutdown))
                   if shutdown is not None and idle_min > 0 else None)
        yield
        if watcher is not None:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
        # A job still running keeps the connection; the process exit releases it
        if owned and app.state.jobs.current is None:
            connection.close()

    app = FastAPI(title="Avaris", lifespan=lifespan, telemetry=TELEMETRY_OFF)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        idle.touch()  # any request, page or API, keeps the server up
        response: Response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    if settings.server.dev_cors:
        # Dev only: job posts from loopback origins are already allowed (not_cross_site)
        app.add_middleware(CORSMiddleware, allow_origin_regex=LOOPBACK_ORIGIN,
                           allow_methods=["GET", "POST"], allow_headers=["content-type"])
    # Added last, so it runs first (preflights included). DNS rebinding: a remote page
    # resolved to 127.0.0.1 still sends its own host name
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(LOOPBACK_HOSTS))
    for module in (predictions, games, teams, performance, backtests, injuries, jobs, server):
        app.include_router(module.router)

    @app.get("/api/health")
    def health(cur: Cursor, jobs: Jobs) -> dict[str, Any]:
        row = cur.execute("select max(version) from schema_version").fetchone()
        current = jobs.current
        job = {k: json_value(v) for k, v in current.public().items()} if current else None
        now = app.state.clock()
        return {"status": "ok", "schema_version": row[0] if row else None,
                "now": json_value(now), "today": et_date(now).isoformat(), "job": job}

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                   include_in_schema=False)
    def unknown_api(path: str) -> None:
        # Before the static mount, so an API typo is a JSON 404 rather than the 404 page
        raise HTTPException(404, f"no endpoint /api/{path}")

    if settings.server.web_dir.is_dir():
        # The PWA's static export (trailingSlash: /game/ is game/index.html; 404.html)
        app.mount("/", WebFiles(directory=settings.server.web_dir, html=True), name="web")
    return app
