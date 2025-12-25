"""API endpoints for disc operations.

These endpoints interact with the daemon via:
1. WebSocket queries for real-time disc status
2. Task queue (scan tasks written to queued/, results in complete/)
"""

import asyncio
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
from amphigory.api import disc_repository
from amphigory.websocket import manager

router = APIRouter(prefix="/api/disc", tags=["disc"])


# Current scan result for the inserted disc (cleared on eject)
_current_scan: Optional[dict] = None


def get_current_scan() -> Optional[dict]:
    """Get the current cached scan result."""
    return _current_scan


def set_current_scan(scan_result: dict) -> None:
    """Cache a scan result."""
    global _current_scan
    _current_scan = scan_result


def clear_current_scan() -> None:
    """Clear the cached scan result (called on disc eject)."""
    global _current_scan
    _current_scan = None


def get_tasks_dir() -> Path:
    """Get the tasks directory from environment."""
    data_dir = Path(os.environ.get("AMPHIGORY_DATA", "/data"))
    return data_dir / "tasks"


async def _get_current_fingerprint() -> Optional[str]:
    """Get fingerprint of currently inserted disc by querying daemon."""
    for daemon_id in _daemons.keys():
        try:
            drive_data = await manager.request_from_daemon(
                daemon_id, "get_drive_status", {}, timeout=5.0
            )
            if drive_data.get("state") in ["disc_inserted", "scanning", "scanned", "ripping"]:
                return drive_data.get("fingerprint")
        except (KeyError, asyncio.TimeoutError):
            pass
    return None


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
    """Check current disc status by querying connected daemons via WebSocket."""
    # Query each daemon for disc status
    for daemon_id in _daemons.keys():
        try:
            drive_data = await manager.request_from_daemon(
                daemon_id, "get_drive_status", {}, timeout=5.0
            )
            if drive_data.get("state") in ["disc_inserted", "scanning", "scanned", "ripping"]:
                return DiscStatusResponse(
                    has_disc=True,
                    device_path=drive_data.get("device"),
                    volume_name=drive_data.get("disc_volume"),
                    daemon_id=daemon_id,
                )
        except (KeyError, asyncio.TimeoutError):
            # Daemon not available or timed out - try next one
            pass

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


@router.get("/current-scan")
async def get_cached_scan(request: Request):
    """Get the currently cached scan result, if any."""
    if _current_scan is None:
        raise HTTPException(status_code=404, detail="No scan cached")
    return _current_scan


@router.get("/scan-result")
async def get_scan_result(request: Request, task_id: Optional[str] = None) -> ScanResultResponse:
    """Get scan result.

    If task_id is provided, returns that specific task's result (or 404 if not complete).
    If task_id is not provided, returns the most recent scan result.

    Also saves scan results to database if fingerprint is available.
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

        # Cache the result
        scan_data = {
            "disc_name": result["disc_name"],
            "disc_type": result["disc_type"],
            "tracks": result.get("tracks", []),
        }
        set_current_scan(scan_data)

        # Save to database if we have a fingerprint
        fingerprint = await _get_current_fingerprint()
        if fingerprint:
            await disc_repository.save_disc_scan(fingerprint, scan_data)

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

    # Cache the result
    scan_data = {
        "disc_name": result["disc_name"],
        "disc_type": result["disc_type"],
        "tracks": result.get("tracks", []),
    }
    set_current_scan(scan_data)

    # Save to database if we have a fingerprint
    fingerprint = await _get_current_fingerprint()
    if fingerprint:
        await disc_repository.save_disc_scan(fingerprint, scan_data)

    return ScanResultResponse(
        disc_name=result["disc_name"],
        disc_type=result["disc_type"],
        tracks=result.get("tracks", []),
    )


@router.get("/lookup-fingerprint")
async def lookup_fingerprint(fingerprint: Optional[str] = None):
    """Look up disc information by fingerprint.

    If fingerprint is not provided, uses the currently inserted disc's fingerprint.

    Returns:
        Disc info with title, cached scan data, etc., or 404 if not found.
    """
    fp = fingerprint
    if not fp:
        # Use current disc's fingerprint
        fp = await _get_current_fingerprint()

    if not fp:
        raise HTTPException(
            status_code=404,
            detail="No fingerprint available"
        )

    disc_info = await disc_repository.get_disc_by_fingerprint(fp)
    if not disc_info:
        raise HTTPException(
            status_code=404,
            detail="Disc not found in database"
        )

    # Parse scan_data if it exists
    if disc_info.get("scan_data"):
        disc_info["scan_data"] = json.loads(disc_info["scan_data"])

    return disc_info


@router.get("/status-html", response_class=HTMLResponse)
async def get_disc_status_html(request: Request):
    """Return disc status as HTML fragment for HTMX."""
    # Query each daemon for disc status
    for daemon_id in _daemons.keys():
        try:
            drive_data = await manager.request_from_daemon(
                daemon_id, "get_drive_status", {}, timeout=5.0
            )
            if drive_data.get("state") in ["disc_inserted", "scanning", "scanned", "ripping"]:
                scan = get_current_scan()
                disc_volume = drive_data.get("disc_volume") or "Unknown"
                disc_device = drive_data.get("device") or ""

                # Check if disc has a fingerprint and if it's known in the database
                fingerprint = drive_data.get("fingerprint")
                known_disc_info = None
                if fingerprint:
                    known_disc_info = await disc_repository.get_disc_by_fingerprint(fingerprint)

                if scan:
                    track_count = len(scan.get("tracks", []))
                    known_disc_html = ""
                    if known_disc_info:
                        known_disc_html = f'<p class="status-detail">Known disc: {known_disc_info["title"]}</p>'

                    return f'''
                <div class="disc-detected">
                    <p class="status-message status-success">Disc detected: {disc_volume}</p>
                    <p class="status-detail">{daemon_id} {disc_device}</p>
                    {known_disc_html}
                    <p class="status-detail">{track_count} tracks scanned</p>
                    <a href="/disc" class="btn btn-primary">Review Tracks</a>
                </div>
                '''
                else:
                    # No scan yet - show scan button
                    known_disc_html = ""
                    if known_disc_info:
                        known_disc_html = f'<p class="status-detail">Known disc: {known_disc_info["title"]}</p>'

                    return f'''
                <div class="disc-detected">
                    <p class="status-message status-success">Disc detected: {disc_volume}</p>
                    <p class="status-detail">{daemon_id} {disc_device}</p>
                    {known_disc_html}
                    <button hx-post="/api/disc/scan" hx-target="#disc-info" class="btn btn-primary">
                        Scan Disc
                    </button>
                </div>
                '''
        except (KeyError, asyncio.TimeoutError):
            # Daemon not available or timed out - try next one
            pass

    return '<p class="status-message">No disc detected</p>'
