import re
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException
from fastapi import Path as PathParam
from fastapi.responses import FileResponse

from avaris.api.deps import AppSettings

router = APIRouter(prefix="/api/backtests", tags=["backtests"])

REPORT = "report.md"
Name = Annotated[str, PathParam(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
Chart = Annotated[str, PathParam(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*\.svg$")]
# Charts are our own SVG, but are served so that no script in one could ever run
SVG_HEADERS = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"}


def _reports(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        return {}
    return {d.name: d for d in sorted(root.iterdir()) if (d / REPORT).is_file()}


def _report(settings: Any, name: str) -> Path:
    found = _reports(settings.models.reports_dir).get(name)
    if found is None:
        raise HTTPException(404, f"no report {name}")
    return found


def _title(markdown: str, default: str) -> str:
    match = re.search(r"^# (.+)$", markdown, re.MULTILINE)
    return match.group(1).strip() if match else default


@router.get("")
def backtests(settings: AppSettings) -> list[dict[str, str]]:
    return [{"name": name, "title": _title((d / REPORT).read_text(), name)}
            for name, d in _reports(settings.models.reports_dir).items()]


@router.get("/{name}")
def backtest(settings: AppSettings, name: Name) -> dict[str, Any]:
    d = _report(settings, name)
    markdown = (d / REPORT).read_text()
    return {"name": name, "title": _title(markdown, name), "markdown": markdown,
            "charts": sorted(p.name for p in d.glob("*.svg"))}


@router.get("/{name}/charts/{chart}")
def chart(settings: AppSettings, name: Name, chart: Chart) -> FileResponse:
    path = _report(settings, name) / chart
    if not path.is_file():
        raise HTTPException(404, f"no chart {chart}")
    return FileResponse(path, media_type="image/svg+xml", headers=SVG_HEADERS)
