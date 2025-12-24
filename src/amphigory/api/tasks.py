"""Task API for file-based task queue management.

These endpoints create/read tasks that the daemon processes.
Tasks are stored as JSON files in the shared storage.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from amphigory.api.common import generate_task_id


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
    result: Optional[dict] = None


class TaskListResponse(BaseModel):
    """Response for listing tasks."""
    tasks: list[TaskStatusResponse]


def ensure_directories(tasks_dir: Path) -> None:
    """Ensure task directories exist."""
    (tasks_dir / "queued").mkdir(parents=True, exist_ok=True)
    (tasks_dir / "in_progress").mkdir(parents=True, exist_ok=True)
    (tasks_dir / "complete").mkdir(parents=True, exist_ok=True)


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

    return TaskResponse(task_id=task_id, type="rip", status="queued")


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
            ))

    return TaskListResponse(tasks=tasks)
