import math
from collections.abc import Iterator, Sequence
from datetime import date, datetime
from typing import Annotated, Any

import duckdb
from fastapi import Depends, Request

from avaris.config import Settings
from avaris.ingest.teams import load_teams
from avaris.pipeline.jobs import Clock, JobManager


def _cursor(request: Request) -> Iterator[duckdb.DuckDBPyConnection]:
    # One cursor per request on the server's read-write connection (DuckDB has one writer)
    cur = request.app.state.con.cursor()
    try:
        yield cur
    finally:
        cur.close()


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _jobs(request: Request) -> JobManager:
    return request.app.state.jobs


def _clock(request: Request) -> Clock:
    return request.app.state.clock


Cursor = Annotated[duckdb.DuckDBPyConnection, Depends(_cursor)]
AppSettings = Annotated[Settings, Depends(_settings)]
Jobs = Annotated[JobManager, Depends(_jobs)]
AppClock = Annotated[Clock, Depends(_clock)]


def json_value(value: Any) -> Any:
    # Timestamps are naive UTC: ISO with a Z; dates as ISO; NaN as null
    if isinstance(value, datetime):
        return value.isoformat() + "Z"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def rows(
    cur: duckdb.DuckDBPyConnection, sql: str, params: Sequence[Any] = ()
) -> list[dict[str, Any]]:
    result = cur.execute(sql, list(params))
    names = [d[0] for d in result.description or []]
    return [
        {name: json_value(v) for name, v in zip(names, values, strict=True)}
        for values in result.fetchall()
    ]


def team_index() -> dict[int, dict[str, Any]]:
    return {
        int(t["team_id"]): {
            "team_id": int(t["team_id"]), "abbreviation": str(t["tricode"]),
            "name": f"{t['city']} {t['nickname']}",
        }
        for t in load_teams().to_dict("records")
    }


TEAMS = team_index()


def team(team_id: int) -> dict[str, Any]:
    return TEAMS.get(team_id, {"team_id": team_id, "abbreviation": None, "name": None})
