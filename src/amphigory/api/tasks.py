"""Task API for file-based task queue management.

These endpoints create/read tasks that the daemon processes.
Tasks are stored as JSON files in the shared storage.
"""

import html
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import aiosqlite
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from amphigory.api.common import generate_task_id
from amphigory.api import disc_repository
from amphigory.websocket import manager

logger = logging.getLogger("uvicorn.error")


router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def get_tasks_dir() -> Path:
    """Get the tasks directory from environment."""
    data_dir = Path(os.environ.get("AMPHIGORY_DATA", "/data"))
    return data_dir / "tasks"


class TrackInfo(BaseModel):
    """Track information for rip tasks."""
    number: int
    expected_size_bytes: Optional[int] = None
    expected_duration: Optional[str] = None


class OutputInfo(BaseModel):
    """Output information for rip tasks."""
    directory: Optional[str] = None
    filename: str


class CreateRipTaskRequest(BaseModel):
    """Request body for creating a rip task."""
    track_number: int
    output_filename: str
    output_directory: Optional[str] = None
    expected_size_bytes: Optional[int] = None
    expected_duration: Optional[str] = None


class TaskResponse(BaseModel):
    """Response for task creation."""
    task_id: str
    type: str
    status: str


class TaskStatusResponse(BaseModel):
    """Response for task status."""
    id: str
    type: Optional[str] = None
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    result: Optional[dict] = None
    error: Optional[dict] = None


class TaskListResponse(BaseModel):
    """Response for listing tasks."""
    tasks: list[TaskStatusResponse]
    paused: bool


class ProcessTrackRequest(BaseModel):
    """Single track to process."""
    track_number: int
    output_filename: str
    output_directory: Optional[str] = None
    preset: Optional[str] = None
    expected_size_bytes: Optional[int] = None
    expected_duration: Optional[str] = None


class ProcessTracksRequest(BaseModel):
    """Request to process multiple tracks."""
    tracks: list[ProcessTrackRequest]
    disc_fingerprint: str


class ProcessTracksResponse(BaseModel):
    """Response with created tasks."""
    tasks: list[dict]


class PauseStatusResponse(BaseModel):
    """Response for pause status endpoints."""
    paused: bool


def ensure_directories(tasks_dir: Path) -> None:
    """Ensure task directories exist."""
    (tasks_dir / "queued").mkdir(parents=True, exist_ok=True)
    (tasks_dir / "in_progress").mkdir(parents=True, exist_ok=True)
    (tasks_dir / "complete").mkdir(parents=True, exist_ok=True)


def get_pause_status() -> bool:
    """Check if the task queue is paused.

    Returns True if the PAUSED marker file exists in the tasks directory.
    """
    tasks_dir = get_tasks_dir()
    paused_file = tasks_dir / "PAUSED"
    return paused_file.exists()


def update_tasks_json(tasks_dir: Path, task_id: str) -> None:
    """Add task ID to tasks.json for ordering."""
    tasks_json = tasks_dir / "tasks.json"

    if tasks_json.exists():
        with open(tasks_json) as f:
            task_order = json.load(f)
    else:
        task_order = []

    task_order.append(task_id)

    with open(tasks_json, "w") as f:
        json.dump(task_order, f, indent=2)


def translate_daemon_path_to_webapp(path: str) -> str:
    """Translate a path from daemon's perspective to webapp's perspective.

    The daemon writes paths like /Volumes/Media Drive 1/Ripped/...
    The webapp sees these as /media/ripped/...

    Uses DAEMON_RIPPED_DIR and AMPHIGORY_RIPPED_DIR environment variables.
    """
    daemon_prefix = os.environ.get("DAEMON_RIPPED_DIR", "")
    webapp_prefix = os.environ.get("AMPHIGORY_RIPPED_DIR", "/media/ripped")

    if daemon_prefix and path.startswith(daemon_prefix):
        return webapp_prefix + path[len(daemon_prefix):]
    return path


async def sync_completed_rip_tasks(tasks_dir: Path) -> int:
    """Sync completed rip tasks to the database.

    For each successful rip task in complete/, finds the corresponding track
    by disc fingerprint and track number, then updates the track's ripped_path
    and status if not already set.

    Paths are translated from daemon perspective to webapp perspective using
    DAEMON_RIPPED_DIR and AMPHIGORY_RIPPED_DIR environment variables.

    Args:
        tasks_dir: The tasks directory containing complete/

    Returns:
        Number of tracks updated
    """
    updated_count = 0
    complete_dir = tasks_dir / "complete"

    if not complete_dir.exists():
        return 0

    db_path = disc_repository.get_db_path()
    if not db_path.exists():
        return 0

    async with aiosqlite.connect(db_path) as conn:
        for task_file in complete_dir.glob("*-rip.json"):
            try:
                with open(task_file) as f:
                    data = json.load(f)

                # Only process successful rip tasks
                if data.get("status") != "success":
                    continue
                if data.get("type") != "rip":
                    continue

                source = data.get("source", {})
                result = data.get("result", {})
                destination = result.get("destination", {})

                fingerprint = source.get("disc_fingerprint")
                track_number = source.get("track_number")
                directory = destination.get("directory", "")
                filename = destination.get("filename", "")

                if not fingerprint or track_number is None or not filename:
                    continue

                # Build full ripped path and translate to webapp perspective
                raw_path = f"{directory}{filename}"
                ripped_path = translate_daemon_path_to_webapp(raw_path)

                # Find track by fingerprint and track_number, only update if ripped_path is NULL
                cursor = await conn.execute(
                    """
                    UPDATE tracks
                    SET ripped_path = ?, status = 'ripped'
                    WHERE disc_id IN (SELECT id FROM discs WHERE fingerprint = ?)
                      AND track_number = ?
                      AND ripped_path IS NULL
                    """,
                    (ripped_path, fingerprint, track_number)
                )

                if cursor.rowcount > 0:
                    updated_count += cursor.rowcount
                    logger.info(f"Updated track {track_number} for disc {fingerprint[:12]}... with ripped_path")

            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Error processing completed task {task_file.name}: {e}")
                continue

        if updated_count > 0:
            await conn.commit()

    return updated_count


def cleanup_old_tasks(tasks_dir: Path, max_age_hours: int = 24) -> dict:
    """Clean up old completed tasks and stale tasks.json entries.

    Args:
        tasks_dir: The tasks directory containing queued/, in_progress/, complete/
        max_age_hours: Maximum age in hours before completed tasks are removed

    Returns:
        Dict with counts of removed files and stale entries
    """
    result = {"removed_files": 0, "removed_entries": 0}
    cutoff_time = datetime.now() - timedelta(hours=max_age_hours)

    # Remove old completed task files
    complete_dir = tasks_dir / "complete"
    if complete_dir.exists():
        for task_file in complete_dir.glob("*.json"):
            mtime = datetime.fromtimestamp(task_file.stat().st_mtime)
            if mtime < cutoff_time:
                task_file.unlink()
                result["removed_files"] += 1
                logger.info(f"Cleaned up old completed task: {task_file.name}")

    # Collect all existing task IDs from directories
    existing_ids = set()
    for subdir in ["queued", "in_progress", "complete"]:
        dir_path = tasks_dir / subdir
        if dir_path.exists():
            for task_file in dir_path.glob("*.json"):
                existing_ids.add(task_file.stem)

    # Clean up stale entries in tasks.json
    tasks_json = tasks_dir / "tasks.json"
    if tasks_json.exists():
        with open(tasks_json) as f:
            task_order = json.load(f)

        original_count = len(task_order)
        task_order = [tid for tid in task_order if tid in existing_ids]
        result["removed_entries"] = original_count - len(task_order)

        with open(tasks_json, "w") as f:
            json.dump(task_order, f, indent=2)

        if result["removed_entries"] > 0:
            logger.info(f"Cleaned up {result['removed_entries']} stale entries from tasks.json")

    return result


@router.get("/pause-status", response_model=PauseStatusResponse)
async def get_pause_status_endpoint() -> PauseStatusResponse:
    """Get the current pause status of the task queue.

    Returns paused=true if the PAUSED marker file exists.
    """
    return PauseStatusResponse(paused=get_pause_status())


@router.post("/pause", response_model=PauseStatusResponse)
async def pause_queue() -> PauseStatusResponse:
    """Pause the task queue.

    Creates a PAUSED marker file with a timestamp. The daemon will check
    for this file and stop picking up new tasks while paused.

    This operation is idempotent - calling pause multiple times is safe.
    """
    tasks_dir = get_tasks_dir()
    tasks_dir.mkdir(parents=True, exist_ok=True)
    paused_file = tasks_dir / "PAUSED"
    paused_file.write_text(datetime.now().isoformat())

    # Broadcast pause state change to all connected browsers
    await manager.broadcast({"type": "queue_paused", "paused": True})

    return PauseStatusResponse(paused=True)


@router.post("/resume", response_model=PauseStatusResponse)
async def resume_queue() -> PauseStatusResponse:
    """Resume the task queue.

    Removes the PAUSED marker file if it exists. The daemon will resume
    picking up new tasks.

    This operation is idempotent - calling resume when not paused is safe.
    """
    tasks_dir = get_tasks_dir()
    paused_file = tasks_dir / "PAUSED"
    try:
        paused_file.unlink()
    except FileNotFoundError:
        pass  # Already removed - idempotent behavior

    # Broadcast pause state change to all connected browsers
    await manager.broadcast({"type": "queue_paused", "paused": False})

    return PauseStatusResponse(paused=False)


@router.post("/scan", status_code=status.HTTP_201_CREATED, response_model=TaskResponse)
async def create_scan_task() -> TaskResponse:
    """Create a new scan task.

    The daemon will pick this up and scan the currently inserted disc.
    """
    tasks_dir = get_tasks_dir()
    ensure_directories(tasks_dir)

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

    # Update tasks.json
    update_tasks_json(tasks_dir, task_id)

    return TaskResponse(task_id=task_id, type="scan", status="queued")


@router.post("/rip", status_code=status.HTTP_201_CREATED, response_model=TaskResponse)
async def create_rip_task(request: CreateRipTaskRequest) -> TaskResponse:
    """Create a new rip task.

    The daemon will pick this up and rip the specified track.
    """
    tasks_dir = get_tasks_dir()
    ensure_directories(tasks_dir)

    task_id = generate_task_id("rip")
    task_data = {
        "id": task_id,
        "type": "rip",
        "created_at": datetime.now().isoformat(),
        "track": {
            "number": request.track_number,
            "expected_size_bytes": request.expected_size_bytes,
            "expected_duration": request.expected_duration,
        },
        "output": {
            "directory": request.output_directory,
            "filename": request.output_filename,
        },
    }

    # Write task file to queued/
    task_file = tasks_dir / "queued" / f"{task_id}.json"
    with open(task_file, "w") as f:
        json.dump(task_data, f, indent=2)

    # Update tasks.json
    update_tasks_json(tasks_dir, task_id)

    # Clean up old completed tasks and stale entries
    cleanup_old_tasks(tasks_dir)

    return TaskResponse(task_id=task_id, type="rip", status="queued")


@router.post("/process", status_code=status.HTTP_201_CREATED, response_model=ProcessTracksResponse)
async def process_tracks(request: ProcessTracksRequest) -> ProcessTracksResponse:
    """Create rip + transcode tasks for selected tracks.

    For each track, creates:
    1. Rip task (input: null, output: ripped path)
    2. Transcode task (input: ripped path, output: transcoded path)
    """
    from amphigory.config import get_config

    tasks_dir = get_tasks_dir()
    ensure_directories(tasks_dir)
    # Also ensure failed/ directory for unified queue
    (tasks_dir / "failed").mkdir(parents=True, exist_ok=True)

    config = get_config()

    created_tasks = []

    for track in request.tracks:
        # Build output paths
        # DAEMON_RIPPED_DIR is the base path where daemon should write ripped files
        ripped_dir = os.environ.get("DAEMON_RIPPED_DIR") or str(config.ripped_dir)
        # Ensure ripped_dir ends with /
        if not ripped_dir.endswith("/"):
            ripped_dir += "/"
        # output_directory from frontend is the disc folder name (e.g., "Movie (2024) {imdb-tt123}/")
        # Combine with base ripped_dir to get full path
        disc_folder = track.output_directory or ""
        output_dir = f"{ripped_dir}{disc_folder}"
        # Ensure output_dir ends with /
        if output_dir and not output_dir.endswith("/"):
            output_dir += "/"
        ripped_path = f"{output_dir}{track.output_filename}"

        transcoded_dir = str(config.transcoded_dir)
        # Replace .mkv with .mp4 for transcoded output
        stem = track.output_filename.rsplit(".", 1)[0]
        transcode_filename = f"{stem}.mp4"
        transcoded_path = f"{transcoded_dir}/{stem}/{transcode_filename}"

        # Create rip task
        rip_id = generate_task_id("rip")
        rip_task = {
            "id": rip_id,
            "type": "rip",
            "created_at": datetime.now().isoformat(),
            "input": None,
            "output": ripped_path,
            "track": {
                "number": track.track_number,
                "expected_size_bytes": track.expected_size_bytes,
                "expected_duration": track.expected_duration,
            },
            "output_info": {
                "directory": output_dir,
                "filename": track.output_filename,
            },
            "disc_fingerprint": request.disc_fingerprint,
        }

        rip_file = tasks_dir / "queued" / f"{rip_id}.json"
        with open(rip_file, "w") as f:
            json.dump(rip_task, f, indent=2)
        update_tasks_json(tasks_dir, rip_id)

        created_tasks.append({
            "task_id": rip_id,
            "type": "rip",
            "input": None,
            "output": ripped_path,
        })

        # Create transcode task (depends on rip output)
        transcode_id = generate_task_id("transcode")
        transcode_task = {
            "id": transcode_id,
            "type": "transcode",
            "created_at": datetime.now().isoformat(),
            "input": ripped_path,
            "output": transcoded_path,
            "preset": track.preset,
            "disc_fingerprint": request.disc_fingerprint,
            "track_number": track.track_number,
        }

        transcode_file = tasks_dir / "queued" / f"{transcode_id}.json"
        with open(transcode_file, "w") as f:
            json.dump(transcode_task, f, indent=2)
        update_tasks_json(tasks_dir, transcode_id)

        created_tasks.append({
            "task_id": transcode_id,
            "type": "transcode",
            "input": ripped_path,
            "output": transcoded_path,
        })

    cleanup_old_tasks(tasks_dir)

    return ProcessTracksResponse(tasks=created_tasks)


@router.get("/failed", response_model=TaskListResponse)
async def get_failed_tasks() -> TaskListResponse:
    """Get all failed tasks from the failed/ directory."""
    tasks_dir = get_tasks_dir()
    failed_dir = tasks_dir / "failed"
    tasks = []

    if failed_dir.exists():
        for task_file in failed_dir.glob("*.json"):
            try:
                with open(task_file) as f:
                    data = json.load(f)
                tasks.append(TaskStatusResponse(
                    id=data.get("task_id", task_file.stem),
                    type=data.get("type"),
                    status="failed",
                    started_at=data.get("started_at"),
                    completed_at=data.get("completed_at"),
                    error=data.get("error"),
                ))
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Error reading failed task {task_file.name}: {e}")
                continue

    return TaskListResponse(tasks=tasks, paused=get_pause_status())


@router.delete("/failed/{task_id}")
async def dismiss_failed_task(task_id: str):
    """Remove a task from the failed/ directory."""
    # Validate task_id to prevent path traversal
    if "/" in task_id or "\\" in task_id or ".." in task_id:
        raise HTTPException(status_code=400, detail="Invalid task ID")

    tasks_dir = get_tasks_dir()
    failed_file = tasks_dir / "failed" / f"{task_id}.json"

    if not failed_file.exists():
        raise HTTPException(status_code=404, detail="Failed task not found")

    failed_file.unlink()
    return {"status": "dismissed"}


@router.get("/active-html", response_class=HTMLResponse)
async def get_active_tasks_html() -> str:
    """Return active tasks as HTML fragment for HTMX."""
    tasks_dir = get_tasks_dir()
    in_progress_dir = tasks_dir / "in_progress"

    if not in_progress_dir.exists():
        return '<p class="text-muted">No active tasks</p>'

    tasks = list(in_progress_dir.glob("*.json"))
    if not tasks:
        return '<p class="text-muted">No active tasks</p>'

    html_content = ""
    for task_file in tasks:
        try:
            with open(task_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        task_type = data.get("type", "task")
        task_id = data.get("id", task_file.stem)
        truncated_id = task_id[11:] if len(task_id) > 20 else task_id  # HHMM.ffffff-type

        # Escape values to prevent XSS
        safe_type = html.escape(task_type.title())
        safe_id = html.escape(truncated_id)
        safe_task_id = html.escape(task_id)

        html_content += f'''
        <div class="task-item">
            <div class="task-info">
                <span class="task-type">{safe_type}</span>
                <span class="task-id">{safe_id}</span>
            </div>
            <div class="progress-bar">
                <div class="progress-bar-fill" id="progress-{safe_task_id}" style="width: 0%"></div>
            </div>
        </div>
        '''

    return html_content if html_content else '<p class="text-muted">No active tasks</p>'


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str) -> TaskStatusResponse:
    """Get the status of a task.

    Checks queued/, in_progress/, and complete/ directories.
    """
    tasks_dir = get_tasks_dir()

    # Check queued/
    queued_file = tasks_dir / "queued" / f"{task_id}.json"
    if queued_file.exists():
        with open(queued_file) as f:
            data = json.load(f)
        return TaskStatusResponse(
            id=task_id,
            type=data.get("type"),
            status="queued",
        )

    # Check in_progress/
    in_progress_file = tasks_dir / "in_progress" / f"{task_id}.json"
    if in_progress_file.exists():
        with open(in_progress_file) as f:
            data = json.load(f)
        return TaskStatusResponse(
            id=task_id,
            type=data.get("type"),
            status="in_progress",
        )

    # Check complete/
    complete_file = tasks_dir / "complete" / f"{task_id}.json"
    if complete_file.exists():
        with open(complete_file) as f:
            data = json.load(f)
        return TaskStatusResponse(
            id=data.get("task_id", task_id),
            type=data.get("type"),
            status=data.get("status", "completed"),
            result=data.get("result"),
        )

    raise HTTPException(status_code=404, detail="Task not found")


@router.get("", response_model=TaskListResponse)
async def list_tasks() -> TaskListResponse:
    """List all tasks across all states."""
    tasks_dir = get_tasks_dir()
    tasks = []

    # Sync completed rip tasks to database
    await sync_completed_rip_tasks(tasks_dir)

    # Collect from queued/
    queued_dir = tasks_dir / "queued"
    if queued_dir.exists():
        for task_file in queued_dir.glob("*.json"):
            with open(task_file) as f:
                data = json.load(f)
            tasks.append(TaskStatusResponse(
                id=data.get("id", task_file.stem),
                type=data.get("type"),
                status="queued",
            ))

    # Collect from in_progress/
    in_progress_dir = tasks_dir / "in_progress"
    if in_progress_dir.exists():
        for task_file in in_progress_dir.glob("*.json"):
            with open(task_file) as f:
                data = json.load(f)
            tasks.append(TaskStatusResponse(
                id=data.get("id", task_file.stem),
                type=data.get("type"),
                status="in_progress",
            ))

    # Collect from complete/
    complete_dir = tasks_dir / "complete"
    if complete_dir.exists():
        for task_file in complete_dir.glob("*.json"):
            with open(task_file) as f:
                data = json.load(f)
            tasks.append(TaskStatusResponse(
                id=data.get("task_id", task_file.stem),
                type=data.get("type"),
                status=data.get("status", "completed"),
                started_at=data.get("started_at"),
                completed_at=data.get("completed_at"),
                duration_seconds=data.get("duration_seconds"),
                result=data.get("result"),
                error=data.get("error"),
            ))

    return TaskListResponse(tasks=tasks, paused=get_pause_status())
