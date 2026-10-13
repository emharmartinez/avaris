from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from avaris.api.deps import Jobs, not_cross_site

router = APIRouter(prefix="/api/server", tags=["server"])


@router.post("/stop", status_code=202, dependencies=[Depends(not_cross_site)])
def stop(request: Request, jobs: Jobs, background: BackgroundTasks) -> dict[str, Any]:
    # The app's Stop server button; a job would be cut off mid-write, so it waits for none
    shutdown = request.app.state.shutdown
    if shutdown is None:
        raise HTTPException(503, "this server cannot be stopped from the app")
    current = jobs.current
    if current is not None:
        raise HTTPException(409, f"job {current.kind} {current.job_id} is running")
    background.add_task(shutdown)  # after the response is sent
    return {"status": "stopping"}
