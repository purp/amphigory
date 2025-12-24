"""API endpoints for disc operations.

These endpoints interact with the daemon via:
1. Daemon-reported disc status (tracked in settings._daemons)
2. Task queue (scan tasks written to queued/, results in complete/)
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from amphigory.api.common import generate_task_id
from amphigory.api.settings import _daemons

router = APIRouter(prefix="/api/disc", tags=["disc"])


def get_tasks_dir() -> Path:
    """Get the tasks directory from environment."""
    data_dir = Path(os.environ.get("AMPHIGORY_DATA", "/data"))
    return data_dir / "tasks"


class DiscStatusResponse(BaseModel):
    """Disc status response."""
    has_disc: bool
    device_path: Optional[str] = None
    disc_type: Optional[str] = None
    volume_name: Optional[str] = None
    track_count: int = 0
    daemon_id: Optional[str] = None


class ScanTaskResponse(BaseModel):
    """Response when initiating a scan."""
    task_id: str
    status: str


class ScanResultResponse(BaseModel):
    """Scan result from completed task."""
    disc_name: str
    disc_type: str
    tracks: list[dict]


@router.get("/status")
async def get_disc_status(request: Request) -> DiscStatusResponse:
    """Check current disc status from connected daemons."""
    # Find first daemon with disc inserted
    for daemon in _daemons.values():
        if daemon.disc_inserted:
            return DiscStatusResponse(
                has_disc=True,
                device_path=daemon.disc_device,
                volume_name=daemon.disc_volume,
                daemon_id=daemon.daemon_id,
            )

    return DiscStatusResponse(has_disc=False)


@router.post("/scan", status_code=status.HTTP_202_ACCEPTED)
async def scan_current_disc(request: Request) -> ScanTaskResponse:
    """Create a scan task for the daemon to process.

    Returns immediately with task_id. Poll /api/disc/scan-result for results.
    """
    tasks_dir = get_tasks_dir()
    (tasks_dir / "queued").mkdir(parents=True, exist_ok=True)

    task_id = generate_task_id("scan")
    task_data = {
        "id": task_id,
        "type": "scan",
        "created_at": datetime.now().isoformat(),
    }

    # Write task file to queued/
    task_file = tasks_dir / "queued" / f"{task_id}.json"
    with open(task_file, "w") as f:
        json.dump(task_data, f, indent=2)

    # Update tasks.json for ordering
    tasks_json = tasks_dir / "tasks.json"
    if tasks_json.exists():
        with open(tasks_json) as f:
            task_order = json.load(f)
    else:
        task_order = []
    task_order.append(task_id)
    with open(tasks_json, "w") as f:
        json.dump(task_order, f, indent=2)

    return ScanTaskResponse(task_id=task_id, status="scanning")


@router.get("/scan-result")
async def get_scan_result(request: Request, task_id: Optional[str] = None) -> ScanResultResponse:
    """Get scan result.

    If task_id is provided, returns that specific task's result (or 404 if not complete).
    If task_id is not provided, returns the most recent scan result.
    """
    tasks_dir = get_tasks_dir()
    complete_dir = tasks_dir / "complete"

    if not complete_dir.exists():
        raise HTTPException(status_code=404, detail="No scan results found")

    # If task_id provided, look for that specific task
    if task_id:
        # Prevent path traversal attacks
        if "/" in task_id or "\\" in task_id or ".." in task_id:
            raise HTTPException(
                status_code=400,
                detail="Invalid task_id format"
            )
        task_file = complete_dir / f"{task_id}.json"
        if not task_file.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Task {task_id} not complete yet"
            )
        with open(task_file) as f:
            data = json.load(f)
        if not data.get("result") or "disc_name" not in data.get("result", {}):
            raise HTTPException(
                status_code=404,
                detail=f"Task {task_id} has no scan result"
            )
        result = data["result"]
        return ScanResultResponse(
            disc_name=result["disc_name"],
            disc_type=result["disc_type"],
            tracks=result.get("tracks", []),
        )

    # No task_id - find the most recent scan result
    scan_results = []
    for result_file in complete_dir.glob("*.json"):
        with open(result_file) as f:
            data = json.load(f)
        # Check if it's a scan result with actual disc data
        if data.get("result") and "disc_name" in data.get("result", {}):
            completed_at = data.get("completed_at", "")
            scan_results.append((completed_at, data))

    if not scan_results:
        raise HTTPException(status_code=404, detail="No scan results found")

    # Sort by completed_at descending, get most recent
    scan_results.sort(key=lambda x: x[0], reverse=True)
    _, latest = scan_results[0]

    result = latest["result"]
    return ScanResultResponse(
        disc_name=result["disc_name"],
        disc_type=result["disc_type"],
        tracks=result.get("tracks", []),
    )


@router.get("/status-html", response_class=HTMLResponse)
async def get_disc_status_html(request: Request):
    """Return disc status as HTML fragment for HTMX."""
    # Find first daemon with disc inserted
    for daemon in _daemons.values():
        if daemon.disc_inserted:
            return f'''
            <div class="disc-detected">
                <p class="status-message status-success">Disc detected: {daemon.disc_volume or "Unknown"}</p>
                <p class="status-detail">{daemon.daemon_id} {daemon.disc_device}</p>
                <button hx-post="/api/disc/scan" hx-target="#disc-info" class="btn btn-primary">
                    Scan Disc
                </button>
            </div>
            '''

    return '<p class="status-message">No disc detected</p>'
