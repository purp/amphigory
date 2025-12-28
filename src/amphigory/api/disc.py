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
from amphigory.tmdb import search_movies, get_external_ids
import aiosqlite

router = APIRouter(prefix="/api/disc", tags=["disc"])
tracks_router = APIRouter(prefix="/api/tracks", tags=["tracks"])


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


def get_active_scan_task() -> Optional[dict]:
    """Check if there's an active scan task (queued or in_progress).

    Returns the task data if found, None otherwise.
    """
    tasks_dir = get_tasks_dir()

    # Check in_progress first
    in_progress_dir = tasks_dir / "in_progress"
    if in_progress_dir.exists():
        for task_file in in_progress_dir.glob("*-scan.json"):
            with open(task_file) as f:
                return json.load(f)

    # Check queued
    queued_dir = tasks_dir / "queued"
    if queued_dir.exists():
        for task_file in queued_dir.glob("*-scan.json"):
            with open(task_file) as f:
                return json.load(f)

    return None


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
    fingerprint: Optional[str] = None
    disc_id: Optional[int] = None


@router.get("/status")
async def get_disc_status(request: Request) -> DiscStatusResponse:
    """Check current disc status by querying connected daemons via WebSocket."""
    # Query each daemon for disc status
    # Copy keys to avoid RuntimeError if _daemons changes during iteration
    for daemon_id in list(_daemons.keys()):
        try:
            drive_data = await manager.request_from_daemon(
                daemon_id, "get_drive_status", {}, timeout=5.0
            )
            if drive_data.get("state") in ["disc_inserted", "scanning", "scanned", "ripping"]:
                # Get track count from database if fingerprint is available
                track_count = 0
                fingerprint = drive_data.get("fingerprint")
                if fingerprint:
                    track_count = await disc_repository.get_track_count_by_fingerprint(fingerprint)

                return DiscStatusResponse(
                    has_disc=True,
                    device_path=drive_data.get("device"),
                    volume_name=drive_data.get("disc_volume"),
                    daemon_id=daemon_id,
                    track_count=track_count,
                )
        except (KeyError, asyncio.TimeoutError):
            # Daemon not available or timed out - try next one
            pass

    return DiscStatusResponse(has_disc=False)


@router.get("/scan-status")
async def get_scan_status():
    """Check if there's an active scan task.

    Returns task info if scan is queued/in_progress, 404 otherwise.
    """
    active_scan = get_active_scan_task()
    if active_scan:
        return {"task_id": active_scan["id"], "status": "scanning"}
    raise HTTPException(status_code=404, detail="No active scan")


@router.post("/scan", status_code=status.HTTP_202_ACCEPTED)
async def scan_current_disc(request: Request):
    """Create a scan task for the daemon to process.

    Returns immediately with task_id. Poll /api/disc/scan-result for results.

    For HTMX requests (from dashboard), returns HTML and redirects to disc review.
    """
    # Check if there's already an active scan
    active_scan = get_active_scan_task()
    if active_scan:
        task_id = active_scan["id"]
    else:
        # Create new scan task
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

    # Check if this is an HTMX request (from dashboard)
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        # Return HTML that shows scanning status and redirects to disc review page
        # Use 200 status since HTMX may not swap content for other status codes
        return HTMLResponse(
            content=f'''
            <div class="scan-started">
                <div class="spinner" style="margin-right: 0.5rem;"></div>
                <p class="status-message">Scan started, redirecting to Disc Review...</p>
            </div>
            <script>setTimeout(() => window.location.href = "/disc?task_id={task_id}", 1000);</script>
            ''',
            status_code=200,
        )

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
        disc_id = None
        if fingerprint:
            disc_id = await disc_repository.save_disc_scan(fingerprint, scan_data)

        return ScanResultResponse(
            disc_name=result["disc_name"],
            disc_type=result["disc_type"],
            tracks=result.get("tracks", []),
            fingerprint=fingerprint,
            disc_id=disc_id,
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
    disc_id = None
    if fingerprint:
        disc_id = await disc_repository.save_disc_scan(fingerprint, scan_data)

    return ScanResultResponse(
        disc_name=result["disc_name"],
        disc_type=result["disc_type"],
        tracks=result.get("tracks", []),
        fingerprint=fingerprint,
        disc_id=disc_id,
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
    """Return disc status as HTML fragment for HTMX.

    For known discs (fingerprint in DB): Show title from DB, track count, "Review Disc" button
    For unknown discs: Show volume name, "Scan Disc" button with hx-post
    Always show fingerprint prefix (first 7 chars) when available
    """
    # Query each daemon for disc status
    # Copy keys to avoid RuntimeError if _daemons changes during iteration
    for daemon_id in list(_daemons.keys()):
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
                fp_short = fingerprint[:11] if fingerprint else ""
                known_disc_info = None
                track_count = 0

                if fingerprint:
                    known_disc_info = await disc_repository.get_disc_by_fingerprint(fingerprint)
                    if known_disc_info:
                        track_count = await disc_repository.get_track_count_by_fingerprint(fingerprint)

                # Format device short name (rdisk8 instead of /dev/rdisk8)
                device_short = disc_device.replace("/dev/", "") if disc_device else ""
                drive_id = f"{daemon_id}:{device_short}" if device_short else daemon_id

                if known_disc_info:
                    # Known disc: Show title from DB, track count, "Review Disc" button
                    title = known_disc_info["title"]
                    track_info = f", {track_count} tracks" if track_count else ""
                    disc_label = f"{title} ({fp_short}{track_info})" if fp_short else f"{title}{track_info}"

                    return f'''
                <div class="disc-detected">
                    <p class="status-message status-success">Disc detected: {disc_label}</p>
                    <p class="status-detail">{drive_id}</p>
                    <a href="/disc" class="btn btn-primary">Review Disc</a>
                </div>
                '''
                elif scan:
                    # Unknown disc but has cached scan: Show scan info with review button
                    scan_track_count = len(scan.get("tracks", []))
                    track_info = f", {scan_track_count} tracks" if scan_track_count else ""
                    disc_label = f"{disc_volume} ({fp_short}{track_info})" if fp_short else f"{disc_volume}{track_info}"

                    return f'''
                <div class="disc-detected">
                    <p class="status-message status-success">Disc detected: {disc_label}</p>
                    <p class="status-detail">{drive_id}</p>
                    <a href="/disc" class="btn btn-primary">Review Tracks</a>
                </div>
                '''
                else:
                    # Unknown disc, no scan: Show volume name and Scan button
                    disc_label = f"{disc_volume} ({fp_short})" if fp_short else disc_volume

                    return f'''
                <div class="disc-detected">
                    <p class="status-message status-success">Disc detected: {disc_label}</p>
                    <p class="status-detail">{drive_id}</p>
                    <button hx-post="/api/disc/scan" hx-target="#disc-info" class="btn btn-primary">
                        Scan Disc
                    </button>
                </div>
                '''
        except (KeyError, asyncio.TimeoutError):
            # Daemon not available or timed out - try next one
            pass

    return '<p class="status-message">No disc detected</p>'


class UpdateMetadataRequest(BaseModel):
    """Request model for updating disc metadata."""
    fingerprint: str
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    title: Optional[str] = None
    year: Optional[int] = None


@router.post("/metadata")
async def update_disc_metadata(request: UpdateMetadataRequest):
    """Update disc metadata by fingerprint."""
    from amphigory.api.disc_repository import get_db_path
    import aiosqlite

    async with aiosqlite.connect(get_db_path()) as db:
        # Check disc exists
        cursor = await db.execute(
            "SELECT id FROM discs WHERE fingerprint = ?",
            (request.fingerprint,)
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Disc not found")

        # Update metadata
        await db.execute(
            """UPDATE discs
               SET tmdb_id = ?, imdb_id = ?, title = ?, year = ?
               WHERE fingerprint = ?""",
            (request.tmdb_id, request.imdb_id, request.title, request.year, request.fingerprint)
        )
        await db.commit()

    return {"updated": True}


@router.get("/metadata/{fingerprint}")
async def get_disc_metadata(fingerprint: str):
    """Get disc metadata by fingerprint."""
    from amphigory.api.disc_repository import get_db_path
    import aiosqlite

    async with aiosqlite.connect(get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT tmdb_id, imdb_id, title, year FROM discs WHERE fingerprint = ?",
            (fingerprint,)
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Disc not found")

        return {
            "tmdb_id": row["tmdb_id"],
            "imdb_id": row["imdb_id"],
            "title": row["title"],
            "year": row["year"]
        }


@router.get("/search-tmdb")
async def search_tmdb(query: str, year: Optional[int] = None):
    """Search TMDB for movie matches."""
    results = await search_movies(query, year)
    return {"results": results}


@router.get("/tmdb-external-ids/{tmdb_id}")
async def get_tmdb_external_ids(tmdb_id: int):
    """Get external IDs (IMDB, etc.) for a TMDB movie."""
    external_ids = await get_external_ids(tmdb_id)
    if external_ids is None:
        raise HTTPException(
            status_code=404,
            detail="Could not fetch external IDs from TMDB"
        )
    return external_ids


@router.get("/by-fingerprint/{fingerprint}")
async def get_disc_by_fingerprint_endpoint(fingerprint: str):
    """Get disc and tracks by fingerprint.

    Returns:
        Dict with "disc" and "tracks" keys.
    """
    result = await disc_repository.get_disc_with_tracks(fingerprint)
    if not result:
        raise HTTPException(status_code=404, detail="Disc not found")

    # Parse scan_data JSON if present
    if result["disc"].get("scan_data"):
        result["disc"]["scan_data"] = json.loads(result["disc"]["scan_data"])

    # Parse audio_tracks and subtitle_tracks JSON for each track
    for track in result["tracks"]:
        if track.get("audio_tracks"):
            track["audio_tracks"] = json.loads(track["audio_tracks"])
        if track.get("subtitle_tracks"):
            track["subtitle_tracks"] = json.loads(track["subtitle_tracks"])

    return result


class SaveDiscRequest(BaseModel):
    """Request body for saving disc and track edits."""
    disc: dict = {}
    tracks: list[dict] = []


@router.post("/{disc_id}/save")
async def save_disc_and_tracks(disc_id: int, request: SaveDiscRequest):
    """Save disc and track edits to database.

    Updates disc info (title, year, imdb_id) and track info
    (track_name, track_type, preset_name) without overwriting paths.
    """
    async with aiosqlite.connect(disc_repository.get_db_path()) as db:
        # Check disc exists
        cursor = await db.execute("SELECT id FROM discs WHERE id = ?", (disc_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail="Disc not found")

        # Update disc fields if provided
        disc_updates = []
        disc_values = []
        for field in ["title", "year", "imdb_id"]:
            if field in request.disc and request.disc[field] is not None:
                disc_updates.append(f"{field} = ?")
                disc_values.append(request.disc[field])

        if disc_updates:
            disc_values.append(disc_id)
            await db.execute(
                f"UPDATE discs SET {', '.join(disc_updates)} WHERE id = ?",
                disc_values
            )

        # Update tracks
        for track_data in request.tracks:
            track_id = track_data.get("id")
            if not track_id:
                continue

            track_updates = []
            track_values = []
            for field in ["track_name", "track_type", "preset_name"]:
                if field in track_data and track_data[field] is not None:
                    track_updates.append(f"{field} = ?")
                    track_values.append(track_data[field])

            if track_updates:
                track_values.append(track_id)
                await db.execute(
                    f"UPDATE tracks SET {', '.join(track_updates)} WHERE id = ?",
                    track_values
                )

        await db.commit()

    return {"status": "saved"}


class VerifyFilesResponse(BaseModel):
    """Response for file verification."""
    ripped_exists: bool
    ripped_path: Optional[str] = None
    transcoded_exists: bool
    transcoded_path: Optional[str] = None
    inserted_exists: bool
    inserted_path: Optional[str] = None


@tracks_router.get("/{track_id}/verify-files", response_model=VerifyFilesResponse)
async def verify_track_files(track_id: int) -> VerifyFilesResponse:
    """Check if a track's output files exist on disk."""
    async with aiosqlite.connect(disc_repository.get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT ripped_path, transcoded_path, inserted_path FROM tracks WHERE id = ?",
            (track_id,)
        )
        row = await cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Track not found")

        track = dict(row)

        ripped_path = track.get("ripped_path")
        transcoded_path = track.get("transcoded_path")
        inserted_path = track.get("inserted_path")

        return VerifyFilesResponse(
            ripped_exists=bool(ripped_path and Path(ripped_path).exists()),
            ripped_path=ripped_path,
            transcoded_exists=bool(transcoded_path and Path(transcoded_path).exists()),
            transcoded_path=transcoded_path,
            inserted_exists=bool(inserted_path and Path(inserted_path).exists()),
            inserted_path=inserted_path,
        )


@tracks_router.post("/{track_id}/reset")
async def reset_track(track_id: int):
    """Reset a track for reprocessing.

    Deletes any existing files and clears paths in database.
    """
    async with aiosqlite.connect(disc_repository.get_db_path()) as db:
        db.row_factory = aiosqlite.Row

        # Get current paths
        cursor = await db.execute(
            "SELECT ripped_path, transcoded_path, inserted_path FROM tracks WHERE id = ?",
            (track_id,)
        )
        row = await cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Track not found")

        track = dict(row)

        # Delete files if they exist
        for path_key in ["ripped_path", "transcoded_path", "inserted_path"]:
            path = track.get(path_key)
            if path:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass  # Ignore errors (e.g., permission denied)

        # Clear paths and reset status
        await db.execute(
            """UPDATE tracks
               SET ripped_path = NULL,
                   transcoded_path = NULL,
                   inserted_path = NULL,
                   status = 'discovered'
               WHERE id = ?""",
            (track_id,)
        )
        await db.commit()

    return {"status": "reset"}
