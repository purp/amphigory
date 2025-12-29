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

# No code goes above these
logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# Constants, to prevent incessent method calls
DATA_DIR = Path(os.environ.get("AMPHIGORY_DATA", "/data"))
                
## Filesystem-based task queue directories
TASKS_DIR = DATA_DIR / "tasks"
QUEUED_DIR = TASKS_DIR / "queued"
IN_PROGRESS_DIR = TASKS_DIR / "in_progress"
COMPLETE_DIR = TASKS_DIR / "complete"
FAILED_DIR = TASKS_DIR / "failed"

## TODO: re-add ensure loop

## Task queue system files
TASK_MANIFEST = TASKS_DIR / "tasks.json"
PAUSE_MARKER = TASKS_DIR / "PAUSED"


# Task request and response classes
## TODO: Factor these out for use with models.py in daemon
class TrackInfo(BaseModel):
    """Track information."""
    db_track_id: int
    expected_size_bytes: Optional[int] = None
    expected_duration: Optional[str] = None

    ## TODO: add method to get track info from db?


class TaskInfo(BaseModel):
    id: str
    type: str


class TrackProcessingTaskRequest(TaskInfo, TrackInfo):
    """Core elements required in request body for a task that processes tracks.
    Abstract class.
    """
    output_directory: str
    output_filename: str


class FileProcessingTaskRequest(TrackProcessingTaskRequest):
    """Core elements required in request body for a task that processes files.
    Abstract class.
    """
    input_directory: str
    input_filename: str


class RipTaskRequest(TrackProcessingTaskRequest):
    """Request body for creating a rip task."""
    type = "rip"


class TranscodeTaskRequest(FileProcessingTaskRequest):
    """Request body for creating a transcode task."""
    type = "transcode"
    handbrake_preset: str


class InsertionTaskRequest(FileProcessingTaskRequest):
    """Request body for creating an insertion task."""
    type = "insertion"
    media_library_dir: str


class TaskCreateResponse(BaseModel):
    """Response for task creation."""
    task_id: str
    type: str
    status: str


class TaskStatus(BaseModel):
    """Response for task status."""
    id: str
    type: str
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[int] = None
    result: Optional[dict] = None
    error: Optional[dict] = None


## TODO: Look at these two
class TaskStatusList(BaseModel):
    """Response for listing tasks."""
    tasks: list[TaskStatus]
    paused: bool


class ProcessTrackRequest(BaseModel):
    """Single track to process."""
    track_number: int
    output_filename: str
    output_directory: Optional[str] = None
    preset: Optional[str] = None
    expected_size_bytes: Optional[int] = None
    expected_duration: Optional[str] = None


class ProcessTrackListRequest(BaseModel):
    """Request to process multiple tracks."""
    tracks: list[ProcessTrackRequest]
    disc_fingerprint: str


class ProcessTrackListResponse(BaseModel):
    """Response with created tasks."""
    tasks: list[dict]


class PauseStatusResponse(BaseModel):
    """Response for pause status endpoints."""
    paused: bool


## Utility functions
def _safely_load_json_data(task_file: Path, reraise: Optional[bool]=False) -> dict:
    json_data = None

    try:
        with open(task_file) as task_json:
            json_data = json.load(task_json)
    except (json.JSONDecodeError, IOError, FileNotFoundError):
        logger.warning(f"Error processing task {task_file.name}:\n    {type(err).__name__}: {err}")

    return json_data


## Task Creation and Completion
def _fetch_incomplete_manifest_tasks() -> list:
    # If we don't have a manifest yet, we'll give back an empty list
    if not TASK_MANIFEST.exists(): return []

    manifest_tasks = _safely_load_json_data(TASK_MANIFEST)

    completed_tasks = [task_file.stem for task_file in COMPLETE_DIR.glob("*.json")]
    incomplete_tasks = list(set(manifest_tasks) - set(completed_tasks))

    # set math doesn't guarantee ordering so re-sort using a dictionary map
    # with the manifest task list as ordering reference
    sort_map = {task: idx for idx, task in enumerate(manifest_tasks)}
    result = sorted(incomplete_tasks, key=lambda task: sort_map[task])

    return result


def _append_task_to_manifest(task_id: str) -> int:
    """Add task ID to tasks.json for ordering."""
    manifest_tasks = _fetch_incomplete_manifest_tasks()

    manifest_tasks.append(task_id)

    with open(TASK_MANIFEST, "w") as manifest:
        json.dump(manifest_tasks, manifest, indent=2)
    
    queue_length = len(manifest_tasks)

    return queue_length

def _add_task_to_queue(task_data) -> str:    
    task_data.id = generate_task_id(task_data.type)

    # Write task file to queue dir
    task_file = QUEUED_DIR / f"{task_data.id}.json"
    with open(task_file, "w") as task:
        json.dump(task_data, task, indent=2)

    task_status = "queued" if isinstance(_append_task_to_manifest(task_data.id), int) else "error"

    return task_status


## TODO: Implement
def _find_webapp_path_for(file_path: Path) -> Path:
    return file_path


def _get_db_col_and_status_for_task_type(task_type: str) -> tuple:
    match task_type:
        case "rip":
            status = "ripped"
        case "transcode":
            status = "transcoded"
        case "insertion":
            status = "inserted"
        case _:
            raise ValueError(f"Task type '{task_type}' is not a valid type")
    return (f"{status}_path", status)

async def consume_completed_tasks() -> int:
    """Sync completed tasks to the database.

    For each successful task in complete/, finds the corresponding track
    in the database, then updates the status and task-type-appropriate column
    with the full path to the output file, e.g. `ripped_path` for a rip task,
    `transcoded_path` for a transcode task, `inserted_path` for an insertion 
    task, etc.

    All paths are written to be accessible by the webapp.

    Returns:
        Number of tracks updated
    """
    updated_count = 0

    db_path = disc_repository.get_db_path()
    if not db_path.exists():
        error_msg = f"database ({db_path}) does not exist"
        raise Exception(error_msg)

    completed_rip_task_files = COMPLETE_DIR.glob("*-rip.json")

    async with aiosqlite.connect(db_path) as conn:
        for task_file in completed_rip_task_files:
            try:
                with open(task_file) as completed_task:
                    task_data = json.load(completed_task)

                # Only process successful tasks
                if task_data.get("status") != "success" or task_data.get("type") == "scan":
                    continue

                source = task_data.get("source", {})
                destination = task_data.get("destination", {})
                result = task_data.get("result", {})

                db_track_id = source.get("db_track_id", None)
                dest_dir = destination.get("directory", None)
                dest_filename = destination.get("filename", None)

                # db_track_id must be an integer, and dest_filename must not be empty
                if not isinstance(db_track_id, int) or not or not dest_filename:
                    # We shouldn't be able to reach this state
                    error_msg = f"Completed task '{task_file}' is missing critical values: db_track_id={db_track_id} dest_dir={dest_dir} dest_filename={dest_filename} ... skipping task"
                    raise ValueError(error_msg)

                # Build full ripped path and translate to webapp perspective
                dest_path = _find_webapp_path_for(Path(dest_dir) / dest_filename)
                if not dest_path.exists():
                    error_msg = f"Completed task '{task_file}' output file '{dest_path}' does not exist"
                    FileNotFoundError(error_msg)

                db_track_col_name, db_track_status = _get_db_col_and_status_for_task_type(task_data.get("type"))

                cursor = await conn.execute(
                    """
                    UPDATE tracks
                    SET ? = ?, status = '?'
                    WHERE id = ?
                    """,
                    (db_track_col_name, dest_path, db_track_status, db_track_id)
                )

                if cursor.rowcount > 0:
                    updated_count += cursor.rowcount
                    logger.info(f"Updated track id={db_track_id} with {db_track_col_name}='{dest_path}' and status='{db_track_status}'")
            except (json.JSONDecodeError, FileNotFoundError, IOError, ValueError) as err:
                logger.warning(f"Error processing task {task_file.name}:\n    {type(err).__name__}: {err}")
                continue

        if updated_count > 0:
            await conn.commit()

    return updated_count


def _create_and_enqueue_task(task_data) -> TaskCreateResponse:
    """Create a new task

    The daemon will pick this up and scan the currently inserted disc.
    """
    if not task_data.type:
        error_msg = "Cannot create typeless task ({task_data})"
        raise Exception(error_msg)

    task_data.created_at = datetime.now().isoformat()

    status = _add_task_to_queue(task_data)

    return TaskCreateResponse(task_id=task_data.id, type=task_data.type, status=status)


@router.post("/scan", status_code=status.HTTP_201_CREATED, response_model=TaskCreateResponse)
async def create_scan_task() -> TaskCreateResponse:
    """Create a new scan task.

    The daemon will pick this up and scan the currently inserted disc.
    """
    return _create_and_enqueue_task({"type": "scan"})


@router.post("/rip", status_code=status.HTTP_201_CREATED, response_model=TaskCreateResponse)
async def create_rip_task(request: RipTaskRequest) -> TaskCreateResponse:
    """Create a new rip task.

    The daemon will pick this up and rip the specified track.
    """
    task_data = {
        "type": "rip",
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
    return _create_and_enqueue_task(task_data)

@router.post("/transcode", status_code=status.HTTP_201_CREATED, response_model=TaskCreateResponse)
async def create_transcode_task(request: TranscodeTaskRequest) -> TaskCreateResponse:
    """Create a new transcode task.

    The webapp will pick this up and transcode the specified file.
    """
    task_data = {
        "type": "transcode",
        "track": {
            "number": request.track_number,
            "expected_size_bytes": request.expected_size_bytes,
            "expected_duration": request.expected_duration,
        },
        "input": {
            "directory": request.input_directory,
            "filename": request.input_filename,
        },
        "output": {
            "directory": request.output_directory,
            "filename": request.output_filename,
        },
        "preset": request.handbrake_preset,
    }
    return _create_and_enqueue_task(task_data)


## TODO: Wire this in
# @router.post("/insertion", status_code=status.HTTP_201_CREATED, response_model=TaskCreateResponse)
async def create_insertion_task(request: InsertionTaskRequest) -> TaskCreateResponse:
    """Create a new library insertion task.

    The webapp will pick this up and insert the specified file.
    """
    task_data = {
        "type": "insertion",
        "track": {
            "number": request.track_number,
            "expected_size_bytes": request.expected_size_bytes,
            "expected_duration": request.expected_duration,
        },
        "input": {
            "directory": request.input_directory,
            "filename": request.input_filename,
        },
        "output": {
            "directory": request.output_directory,
            "media_library_dir" : request.media_library_dir,
            "filename": request.output_filename,
        },
    }
    return _create_and_enqueue_task(task_data)


@router.post("/process", status_code=status.HTTP_201_CREATED, response_model=ProcessTrackListResponse)
async def process_tracks(request: ProcessTrackListRequest) -> ProcessTrackListResponse:
    """Create rip + transcode tasks for selected tracks.

    For each track, creates:
    1. Rip task (input: null, output: ripped path)
    2. Transcode task (input: ripped path, output: transcoded path)
    """
    from amphigory.config import get_config

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

        # For transcode task, use container paths (not daemon/host paths)
        # The container sees ripped files at /media/ripped, transcoded at /media/transcoded
        container_ripped_dir = str(config.ripped_dir)  # e.g., /media/ripped
        if not container_ripped_dir.endswith("/"):
            container_ripped_dir += "/"
        container_ripped_path = f"{container_ripped_dir}{disc_folder}{track.output_filename}"

        transcoded_dir = str(config.transcoded_dir)  # e.g., /media/transcoded
        # Replace .mkv with .mp4 for transcoded output
        stem = track.output_filename.rsplit(".", 1)[0]
        transcode_filename = f"{stem}.mp4"
        transcoded_path = f"{transcoded_dir}/{disc_folder}{transcode_filename}"

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
        append_task_to_manifest(tasks_dir, rip_id)

        created_tasks.append({
            "task_id": rip_id,
            "type": "rip",
            "input": None,
            "output": ripped_path,
        })

        # Create transcode task (depends on rip output)
        # Uses container paths since transcoding runs inside the container
        transcode_id = generate_task_id("transcode")
        transcode_task = {
            "id": transcode_id,
            "type": "transcode",
            "created_at": datetime.now().isoformat(),
            "input": container_ripped_path,
            "output": transcoded_path,
            "preset": track.preset,
            "disc_fingerprint": request.disc_fingerprint,
            "track_number": track.track_number,
        }
        ## TODO: raise an exception if any values in `transcode_task` are empty

        transcode_file = tasks_dir / "queued" / f"{transcode_id}.json"
        with open(transcode_file, "w") as f:
            json.dump(transcode_task, f, indent=2)
        append_task_to_manifest(tasks_dir, transcode_id)

        created_tasks.append({
            "task_id": transcode_id,
            "type": "transcode",
            "input": container_ripped_path,
            "output": transcoded_path,
        })

    cleanup_old_tasks(tasks_dir)

    return ProcessTrackListResponse(tasks=created_tasks)


## Queue Management
def _get_pause_status() -> bool:
    """Check if the task queue is paused.

    Returns True if the PAUSED marker file exists in the tasks directory.
    """
    return PAUSE_MARKER.exists()


## TODO: Wire this to webapp if not already?
@router.get("/pause-status", response_model=PauseStatusResponse)
async def get_pause_status() -> PauseStatusResponse:
    """Get the current pause status of the task queue.

    Returns paused=true if the PAUSED marker file exists.
    """
    return PauseStatusResponse(paused=_get_pause_status())


@router.post("/pause", response_model=PauseStatusResponse)
async def pause_queue() -> PauseStatusResponse:
    """Pause the task queue.

    Creates a PAUSED marker file with a timestamp. The daemon will check
    for this file and stop picking up new tasks while paused.

    This operation is idempotent - calling pause multiple times is safe.
    """
    if not get_pause_status():
        PAUSE_MARKER.write_text(datetime.now().isoformat())

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
    if get_pause_status():
        PAUSE_MARKER.unlink()

        # Broadcast pause state change to all connected browsers
        await manager.broadcast({"type": "queue_paused", "paused": False})

    return PauseStatusResponse(paused=False)

## Queue Inspection
def _fetch_tasks_statuses(statuses: list[str]=["queued", "in_progress", "complete"], task_id: Optional[str]=None) -> list[TaskStatus]:
    if task_id and ("/" in task_id or "\\" in task_id or ".." in task_id):
        raise HTTPException(status_code=400, detail="Invalid task ID")

    task_statuses = []

    task_dirs = [globals()[f"{status.upper()}_DIR"] for status in statuses if f"{status.upper()}_DIR" in globals()]

    globby = f"{task_id}.json" if task_id else "*.json"

    for task_dir in task_dirs:
        for task_file in task_dir.glob("*.json"):
            task_data = {
                "id": task_file.stem,
                "type": task_file.stem.split("-")[-1],
                "status": task_file.parent.name,
            }

            # Completed tasks get more details
            try:
                if task_data["status"] in ("complete", "failed"):
                    # Who says naming is a hard problem? =P
                    if task_data["status"] == "complete": task_data["status"] = "completed"

                    task_details = _safely_load_json_data(task_file, reraise=True)
                    
                    addl_keys = ["started_at", "completed_at", "duration_seconds", "result", "error"]
                    task_data.update({key: task_details[key] for key in addl_keys if key in task_details})
            except (json.JSONDecodeError, IOError) as error_msg:
                logger.warning(f"Error reading task {task_file.name}:\n    {type(err).__name__}: {err}")
                continue

            task_statuses.append(TaskStatus(**task_data))

    return task_statuses


@router.get("", response_model=TaskStatusList)
async def list_tasks() -> TaskStatusList:
    """List all tasks across all states."""
    # Sync completed tasks to database
    await consume_completed_tasks()

    return TaskStatusList(tasks=_fetch_tasks_statuses(), paused=_get_pause_status())


@router.get("/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str) -> TaskStatus:
    """Get the status of a task.

    Checks queued/, in_progress/, and complete/ directories.
    """
    try:
        return _fetch_tasks_statuses(task_id=task_id)[0]
    except:
        raise HTTPException(status_code=404, detail="Task not found")


@router.get("/failed", response_model=TaskStatusList)
async def get_failed_tasks() -> TaskStatusList:
    """Get all failed tasks from the failed/ directory."""
    return TaskStatusList(tasks=_fetch_tasks_statuses(["failed"]), paused=_get_pause_status())


@router.delete("/failed/{task_id}")
async def dismiss_failed_task(task_id: str):
    """Remove a task from the failed/ directory."""
    failed_task_file = FAILED_DIR / f"{task_id}.json"

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
        data = _safely_load_json_data(task_file)

        if not data:
            logger.warning(f"Error reading {task_file} ... skipping")
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

