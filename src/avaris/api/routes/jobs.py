from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from avaris.api.deps import Jobs, json_value
from avaris.pipeline.jobs import JobBusy

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offline: bool | None = None  # daily: skip the source refresh
    through: date | None = None  # train: cutoff (default: today ET)
    target: list[Literal["home_win", "margin", "total"]] | None = None  # train


def _public(job: dict[str, Any]) -> dict[str, Any]:
    return {k: json_value(v) for k, v in job.items()}


@router.post("/{kind}", status_code=202)
def submit(
    jobs: Jobs, kind: Literal["daily", "score", "train"],
    params: Annotated[JobParams | None, Body()] = None,
) -> dict[str, Any]:
    values = params.model_dump(mode="json", exclude_none=True) if params else {}
    try:
        job = jobs.submit(kind, values)
    except JobBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    return _public(job.public())


@router.get("")
def recent(jobs: Jobs, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[dict[str, Any]]:
    return [_public(j) for j in jobs.recent(limit)]


@router.get("/{job_id}")
def status(jobs: Jobs, job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"no job {job_id}")
    return _public(job)
