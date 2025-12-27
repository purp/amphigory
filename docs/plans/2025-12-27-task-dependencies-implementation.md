# Task Dependencies & Unified Queue Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Unify daemon and webapp task queues with file-based dependencies so rip + transcode tasks can be submitted together.

**Architecture:** Both daemon and webapp observe the same filesystem task queue. Daemon processes `scan`/`rip` tasks, webapp processes `transcode`/`insert` tasks. Dependencies resolved by checking if input file exists before claiming a task.

**Tech Stack:** Python (aiosqlite, FastAPI, asyncio), filesystem-based queue, WebSocket for progress

---

## Task 1: Add `input`/`output` Fields to Task Structure

Update task structure to include dependency fields.

**Files:**
- Modify: `daemon/src/amphigory_daemon/models.py`
- Modify: `src/amphigory/api/tasks.py`
- Test: `daemon/tests/test_models.py`
- Test: `tests/test_tasks_api.py`

**Step 1: Write failing test for task parsing with input/output**

In `daemon/tests/test_models.py`:

```python
def test_task_from_dict_with_input_output():
    """Test parsing task with input/output dependency fields."""
    data = {
        "id": "20251227T143052.123456-rip",
        "type": "rip",
        "created_at": "2025-12-27T14:30:52.123456",
        "input": None,
        "output": "/media/ripped/Movie (2024)/Movie (2024).mkv",
        "track": {"number": 1, "expected_size_bytes": 1000, "expected_duration": "1:30:00"},
        "output": {"directory": "/media/ripped/Movie (2024)/", "filename": "Movie (2024).mkv"},
    }
    task = task_from_dict(data)
    assert task.input_path is None
    assert task.output_path == "/media/ripped/Movie (2024)/Movie (2024).mkv"
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_models.py::test_task_from_dict_with_input_output -v`
Expected: FAIL with AttributeError

**Step 3: Add input_path/output_path to task dataclasses**

In `daemon/src/amphigory_daemon/models.py`, update `ScanTask` and `RipTask`:

```python
@dataclass
class ScanTask:
    """A task to scan a disc for track information."""
    id: str
    type: TaskType
    created_at: datetime
    input_path: Optional[str] = None  # Always None for scan
    output_path: Optional[str] = None  # Scan results go to complete/, not a file


@dataclass
class RipTask:
    """A task to rip a specific track from a disc."""
    id: str
    type: TaskType
    created_at: datetime
    track: TrackInfo
    output: OutputInfo
    input_path: Optional[str] = None  # Always None for rip (reads from disc)
    output_path: Optional[str] = None  # Path where ripped file will be written
```

Update `task_from_dict()`:

```python
def task_from_dict(data: dict) -> Union[ScanTask, RipTask]:
    """Parse a task from a dictionary (loaded from JSON)."""
    task_type = TaskType(data["type"])
    created_at = _parse_datetime(data["created_at"])
    input_path = data.get("input")
    output_path = data.get("output")

    if task_type == TaskType.SCAN:
        return ScanTask(
            id=data["id"],
            type=task_type,
            created_at=created_at,
            input_path=input_path,
            output_path=output_path,
        )
    elif task_type == TaskType.RIP:
        track_data = data["track"]
        output_data = data.get("output_info", data.get("output", {}))  # Support both formats
        return RipTask(
            id=data["id"],
            type=task_type,
            created_at=created_at,
            track=TrackInfo(
                number=track_data["number"],
                expected_size_bytes=track_data.get("expected_size_bytes"),
                expected_duration=track_data.get("expected_duration"),
            ),
            output=OutputInfo(
                directory=output_data.get("directory", ""),
                filename=output_data.get("filename", ""),
            ),
            input_path=input_path,
            output_path=output_path,
        )
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_models.py::test_task_from_dict_with_input_output -v`
Expected: PASS

**Step 5: Commit**

```bash
git add daemon/src/amphigory_daemon/models.py daemon/tests/test_models.py
git commit -m "feat: add input_path/output_path to task dataclasses"
```

---

## Task 2: Add TranscodeTask Type to Daemon Models

The daemon needs to know about transcode tasks to filter them out.

**Files:**
- Modify: `daemon/src/amphigory_daemon/models.py`
- Test: `daemon/tests/test_models.py`

**Step 1: Write failing test**

```python
def test_task_type_includes_transcode():
    """Test TaskType enum includes transcode."""
    assert TaskType.TRANSCODE.value == "transcode"
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_models.py::test_task_type_includes_transcode -v`
Expected: FAIL with AttributeError

**Step 3: Add TRANSCODE to TaskType enum**

```python
class TaskType(Enum):
    """Type of task to process."""
    SCAN = "scan"
    RIP = "rip"
    TRANSCODE = "transcode"
    INSERT = "insert"
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_models.py::test_task_type_includes_transcode -v`
Expected: PASS

**Step 5: Commit**

```bash
git add daemon/src/amphigory_daemon/models.py daemon/tests/test_models.py
git commit -m "feat: add TRANSCODE and INSERT to TaskType enum"
```

---

## Task 3: Create Shared TaskQueue Library

Create a shared library that both daemon and webapp can use for queue operations.

**Files:**
- Create: `shared/amphigory_tasks/__init__.py`
- Create: `shared/amphigory_tasks/queue.py`
- Create: `shared/pyproject.toml`
- Test: `shared/tests/test_queue.py`

**Step 1: Create shared package structure**

```bash
mkdir -p shared/amphigory_tasks shared/tests
```

**Step 2: Write failing test for task filtering by type**

Create `shared/tests/test_queue.py`:

```python
import pytest
from pathlib import Path
import json
import tempfile

from amphigory_tasks.queue import UnifiedTaskQueue, TaskOwner


@pytest.fixture
def temp_queue():
    """Create a temporary task queue directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        queue = UnifiedTaskQueue(Path(tmpdir))
        queue.ensure_directories()
        yield queue


def test_get_next_task_filters_by_owner(temp_queue):
    """Test that get_next_task only returns tasks for the specified owner."""
    # Create a rip task (daemon) and transcode task (webapp)
    rip_task = {
        "id": "20251227T140000.000000-rip",
        "type": "rip",
        "created_at": "2025-12-27T14:00:00",
        "input": None,
        "output": "/media/ripped/test.mkv",
    }
    transcode_task = {
        "id": "20251227T140001.000000-transcode",
        "type": "transcode",
        "created_at": "2025-12-27T14:00:01",
        "input": "/media/ripped/test.mkv",
        "output": "/media/inbox/test.mkv",
    }

    # Write tasks
    temp_queue.create_task(rip_task)
    temp_queue.create_task(transcode_task)

    # Daemon should only see rip task
    daemon_task = temp_queue.get_next_task(TaskOwner.DAEMON)
    assert daemon_task["type"] == "rip"

    # Webapp should only see transcode task (but it's waiting on input)
    webapp_task = temp_queue.get_next_task(TaskOwner.WEBAPP)
    assert webapp_task is None  # Input file doesn't exist


def test_get_next_task_respects_input_dependency(temp_queue):
    """Test that tasks with input dependency wait for file to exist."""
    transcode_task = {
        "id": "20251227T140001.000000-transcode",
        "type": "transcode",
        "created_at": "2025-12-27T14:00:01",
        "input": "/nonexistent/file.mkv",
        "output": "/media/inbox/test.mkv",
    }
    temp_queue.create_task(transcode_task)

    # Task should not be returned because input doesn't exist
    task = temp_queue.get_next_task(TaskOwner.WEBAPP)
    assert task is None
```

**Step 3: Run test to verify it fails**

Run: `cd shared && python -m pytest tests/test_queue.py -v`
Expected: FAIL with ImportError

**Step 4: Implement UnifiedTaskQueue**

Create `shared/amphigory_tasks/__init__.py`:

```python
"""Shared task queue library for Amphigory."""

from .queue import UnifiedTaskQueue, TaskOwner

__all__ = ["UnifiedTaskQueue", "TaskOwner"]
```

Create `shared/amphigory_tasks/queue.py`:

```python
"""Unified file-based task queue for daemon and webapp."""

import json
import shutil
from enum import Enum
from pathlib import Path
from typing import Optional


class TaskOwner(Enum):
    """Which component processes which task types."""
    DAEMON = "daemon"
    WEBAPP = "webapp"


# Map task type suffix to owner
TASK_OWNERS = {
    "-scan": TaskOwner.DAEMON,
    "-rip": TaskOwner.DAEMON,
    "-transcode": TaskOwner.WEBAPP,
    "-insert": TaskOwner.WEBAPP,
}


class UnifiedTaskQueue:
    """
    File-based task queue with dependency resolution.

    Directory structure:
        base_dir/
        ├── tasks.json          # Ordered list of task IDs
        ├── queued/             # Tasks waiting to be processed
        ├── in_progress/        # Currently being processed
        ├── complete/           # Finished tasks
        └── failed/             # Failed tasks for review
    """

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.tasks_json = self.base_dir / "tasks.json"
        self.queued_dir = self.base_dir / "queued"
        self.in_progress_dir = self.base_dir / "in_progress"
        self.complete_dir = self.base_dir / "complete"
        self.failed_dir = self.base_dir / "failed"

    def ensure_directories(self) -> None:
        """Create queue directories if they don't exist."""
        self.queued_dir.mkdir(parents=True, exist_ok=True)
        self.in_progress_dir.mkdir(parents=True, exist_ok=True)
        self.complete_dir.mkdir(parents=True, exist_ok=True)
        self.failed_dir.mkdir(parents=True, exist_ok=True)

    def get_task_order(self) -> list[str]:
        """Read tasks.json and return ordered list of task IDs."""
        if not self.tasks_json.exists():
            return []
        with open(self.tasks_json) as f:
            return json.load(f)

    def _get_owner_for_task_id(self, task_id: str) -> Optional[TaskOwner]:
        """Determine owner based on task ID suffix."""
        for suffix, owner in TASK_OWNERS.items():
            if task_id.endswith(suffix):
                return owner
        return None

    def _is_input_ready(self, task_data: dict) -> bool:
        """Check if task's input dependency is satisfied."""
        input_path = task_data.get("input")
        if input_path is None:
            return True
        return Path(input_path).exists()

    def create_task(self, task_data: dict) -> str:
        """
        Create a new task in the queue.

        Args:
            task_data: Task dictionary with id, type, input, output, etc.

        Returns:
            Task ID
        """
        task_id = task_data["id"]

        # Write task file
        task_file = self.queued_dir / f"{task_id}.json"
        with open(task_file, "w") as f:
            json.dump(task_data, f, indent=2)

        # Update tasks.json
        task_order = self.get_task_order()
        task_order.append(task_id)
        with open(self.tasks_json, "w") as f:
            json.dump(task_order, f, indent=2)

        return task_id

    def get_next_task(self, owner: TaskOwner) -> Optional[dict]:
        """
        Find next task for the specified owner.

        Filters by task type and checks input dependencies.

        Args:
            owner: TaskOwner.DAEMON or TaskOwner.WEBAPP

        Returns:
            Task data dict if found, None otherwise
        """
        task_order = self.get_task_order()

        for task_id in task_order:
            # Filter by owner based on task ID suffix
            task_owner = self._get_owner_for_task_id(task_id)
            if task_owner != owner:
                continue

            # Check if task exists in queued/
            queued_file = self.queued_dir / f"{task_id}.json"
            if not queued_file.exists():
                continue

            # Read task and check input dependency
            with open(queued_file) as f:
                task_data = json.load(f)

            if not self._is_input_ready(task_data):
                continue

            # Claim task by moving to in_progress/
            in_progress_file = self.in_progress_dir / f"{task_id}.json"
            shutil.move(str(queued_file), str(in_progress_file))

            return task_data

        return None

    def complete_task(self, task_id: str, response: dict) -> None:
        """
        Mark a task as complete.

        Args:
            task_id: Task ID
            response: Response data to write to complete/
        """
        complete_file = self.complete_dir / f"{task_id}.json"
        with open(complete_file, "w") as f:
            json.dump(response, f, indent=2)

        # Remove from in_progress/
        in_progress_file = self.in_progress_dir / f"{task_id}.json"
        if in_progress_file.exists():
            in_progress_file.unlink()

        # If failed, also copy to failed/
        if response.get("status") == "failed":
            failed_file = self.failed_dir / f"{task_id}.json"
            with open(failed_file, "w") as f:
                json.dump(response, f, indent=2)

    def get_failed_tasks(self) -> list[dict]:
        """Get all failed tasks."""
        tasks = []
        for task_file in self.failed_dir.glob("*.json"):
            with open(task_file) as f:
                tasks.append(json.load(f))
        return tasks

    def remove_from_failed(self, task_id: str) -> None:
        """Remove a task from failed/ directory."""
        failed_file = self.failed_dir / f"{task_id}.json"
        if failed_file.exists():
            failed_file.unlink()

    def get_downstream_tasks(self, output_path: str) -> list[dict]:
        """
        Find tasks whose input matches the given output path.

        Args:
            output_path: Output path to match against task inputs

        Returns:
            List of task data dicts
        """
        downstream = []
        for task_file in self.queued_dir.glob("*.json"):
            with open(task_file) as f:
                task_data = json.load(f)
            if task_data.get("input") == output_path:
                downstream.append(task_data)
        return downstream
```

Create `shared/pyproject.toml`:

```toml
[project]
name = "amphigory-tasks"
version = "0.1.0"
description = "Shared task queue library for Amphigory"
requires-python = ">=3.11"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

**Step 5: Run tests to verify they pass**

Run: `cd shared && pip install -e . && python -m pytest tests/test_queue.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add shared/
git commit -m "feat: create shared task queue library with dependency resolution"
```

---

## Task 4: Update Daemon to Use UnifiedTaskQueue

Migrate daemon's TaskQueue to use the shared library.

**Files:**
- Modify: `daemon/src/amphigory_daemon/tasks.py`
- Modify: `daemon/pyproject.toml`
- Test: `daemon/tests/test_tasks.py`

**Step 1: Write failing test for daemon filtering**

Add to `daemon/tests/test_tasks.py`:

```python
def test_daemon_only_claims_scan_and_rip_tasks(temp_queue):
    """Test daemon ignores transcode tasks."""
    # Add a transcode task to queue
    transcode_id = "20251227T140000.000000-transcode"
    transcode_file = temp_queue.queued_dir / f"{transcode_id}.json"
    with open(transcode_file, "w") as f:
        json.dump({
            "id": transcode_id,
            "type": "transcode",
            "input": "/tmp/test.mkv",
            "output": "/tmp/out.mkv",
        }, f)

    # Update tasks.json
    with open(temp_queue.tasks_json, "w") as f:
        json.dump([transcode_id], f)

    # Daemon should not claim it
    task = temp_queue.get_next_task()
    assert task is None
```

**Step 2: Run test to verify behavior**

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_tasks.py::test_daemon_only_claims_scan_and_rip_tasks -v`

**Step 3: Update daemon TaskQueue to filter by type**

In `daemon/src/amphigory_daemon/tasks.py`, update `get_next_task()`:

```python
DAEMON_TASK_TYPES = {"scan", "rip"}

def get_next_task(self) -> Optional[Union[ScanTask, RipTask]]:
    """
    Find next task to process.

    Only returns scan and rip tasks (daemon's responsibility).
    """
    task_order = self.get_task_order()

    for task_id in task_order:
        # Filter by task type suffix
        task_type = task_id.split("-")[-1] if "-" in task_id else None
        if task_type not in DAEMON_TASK_TYPES:
            continue

        queued_file = self.queued_dir / f"{task_id}.json"
        if not queued_file.exists():
            continue

        # Move to in_progress and return
        in_progress_file = self.in_progress_dir / f"{task_id}.json"
        shutil.move(str(queued_file), str(in_progress_file))

        with open(in_progress_file) as f:
            data = json.load(f)
        return task_from_dict(data)

    return None
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=daemon/src daemon/.venv/bin/pytest daemon/tests/test_tasks.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add daemon/src/amphigory_daemon/tasks.py daemon/tests/test_tasks.py
git commit -m "feat: daemon filters to only process scan/rip tasks"
```

---

## Task 5: Create Webapp Task Processor

Replace JobRunner with a task processor that handles transcode tasks.

**Files:**
- Create: `src/amphigory/task_processor.py`
- Test: `tests/test_task_processor.py`

**Step 1: Write failing test**

Create `tests/test_task_processor.py`:

```python
import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from amphigory.task_processor import TaskProcessor


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.connection = MagicMock(return_value=AsyncMock())
    return db


@pytest.fixture
def temp_tasks_dir(tmp_path):
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "queued").mkdir(parents=True)
    (tasks_dir / "in_progress").mkdir(parents=True)
    (tasks_dir / "complete").mkdir(parents=True)
    (tasks_dir / "failed").mkdir(parents=True)
    return tasks_dir


def test_task_processor_init(mock_db, temp_tasks_dir, tmp_path):
    """Test TaskProcessor initialization."""
    processor = TaskProcessor(
        db=mock_db,
        tasks_dir=temp_tasks_dir,
        inbox_dir=tmp_path / "inbox",
        preset_dir=tmp_path / "presets",
    )
    assert processor.db == mock_db
    assert processor.tasks_dir == temp_tasks_dir
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_task_processor.py -v`
Expected: FAIL with ImportError

**Step 3: Create TaskProcessor class**

Create `src/amphigory/task_processor.py`:

```python
"""Background task processor for webapp (transcode/insert tasks)."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Callable, Optional

from amphigory.database import Database
from amphigory.presets import PresetManager
from amphigory.services.transcoder import TranscoderService, TranscodeProgress
from amphigory.preset_selector import parse_resolution, recommend_preset

logger = logging.getLogger(__name__)

WEBAPP_TASK_TYPES = {"transcode", "insert"}


class TaskProcessor:
    """Background task processor for transcode and insert tasks."""

    def __init__(
        self,
        db: Database,
        tasks_dir: Path | str,
        inbox_dir: Path | str,
        preset_dir: Path | str,
        progress_callback: Optional[Callable[[dict], None]] = None,
    ):
        self.db = db
        self.tasks_dir = Path(tasks_dir)
        self.inbox_dir = Path(inbox_dir)
        self.preset_dir = Path(preset_dir)
        self.progress_callback = progress_callback
        self.transcoder = TranscoderService()
        self.preset_manager = PresetManager(preset_dir)
        self._running = False
        self._task = None

    @property
    def queued_dir(self) -> Path:
        return self.tasks_dir / "queued"

    @property
    def in_progress_dir(self) -> Path:
        return self.tasks_dir / "in_progress"

    @property
    def complete_dir(self) -> Path:
        return self.tasks_dir / "complete"

    @property
    def failed_dir(self) -> Path:
        return self.tasks_dir / "failed"

    def get_task_order(self) -> list[str]:
        """Read tasks.json for ordering."""
        tasks_json = self.tasks_dir / "tasks.json"
        if not tasks_json.exists():
            return []
        with open(tasks_json) as f:
            return json.load(f)

    def _is_input_ready(self, task_data: dict) -> bool:
        """Check if task's input file exists."""
        input_path = task_data.get("input")
        if input_path is None:
            return True
        return Path(input_path).exists()

    async def start(self) -> None:
        """Start the task processor loop."""
        if self._running:
            return
        self._running = True
        await self.preset_manager.load()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the task processor."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        """Main loop that polls for tasks."""
        while self._running:
            try:
                await self.process_one_task()
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error processing task: {e}")
                await asyncio.sleep(5)

    async def get_next_task(self) -> Optional[dict]:
        """Get next task for webapp (transcode/insert)."""
        task_order = self.get_task_order()

        for task_id in task_order:
            # Filter by task type suffix
            task_type = task_id.split("-")[-1] if "-" in task_id else None
            if task_type not in WEBAPP_TASK_TYPES:
                continue

            queued_file = self.queued_dir / f"{task_id}.json"
            if not queued_file.exists():
                continue

            with open(queued_file) as f:
                task_data = json.load(f)

            # Check input dependency
            if not self._is_input_ready(task_data):
                continue

            # Claim task
            import shutil
            in_progress_file = self.in_progress_dir / f"{task_id}.json"
            shutil.move(str(queued_file), str(in_progress_file))

            return task_data

        return None

    async def process_one_task(self) -> bool:
        """Process one task from the queue."""
        task_data = await self.get_next_task()
        if not task_data:
            return False

        task_id = task_data["id"]
        task_type = task_data.get("type")

        try:
            if task_type == "transcode":
                await self._process_transcode(task_data)
            elif task_type == "insert":
                await self._process_insert(task_data)

            return True
        except Exception as e:
            await self._complete_task(task_id, {
                "task_id": task_id,
                "status": "failed",
                "error": {"message": str(e)},
            })
            return True

    async def _process_transcode(self, task_data: dict) -> None:
        """Process a transcode task."""
        task_id = task_data["id"]
        input_path = Path(task_data["input"])
        output_path = Path(task_data["output"])

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Get preset
        preset_name = task_data.get("preset")
        if not preset_name:
            # Auto-select based on resolution
            # TODO: Read resolution from input file
            preset_name = self.preset_manager.get_active_preset("bluray")

        preset_path = self.preset_manager.get_preset_path("bluray")

        # Run transcode
        def progress_cb(p: TranscodeProgress):
            if self.progress_callback:
                self.progress_callback({
                    "task_id": task_id,
                    "percent": p.percent,
                    "eta_seconds": p.eta_seconds,
                })

        success = await self.transcoder.transcode(
            input_path=input_path,
            output_path=output_path,
            preset_path=preset_path,
            preset_name=preset_name,
            progress_callback=progress_cb,
        )

        if not success:
            raise Exception("Transcode failed")

        await self._complete_task(task_id, {
            "task_id": task_id,
            "status": "success",
            "result": {
                "output": str(output_path),
            },
        })

    async def _process_insert(self, task_data: dict) -> None:
        """Process an insert task (move to Plex library)."""
        # TODO: Implement insert task
        task_id = task_data["id"]
        await self._complete_task(task_id, {
            "task_id": task_id,
            "status": "success",
        })

    async def _complete_task(self, task_id: str, response: dict) -> None:
        """Write task completion and clean up."""
        complete_file = self.complete_dir / f"{task_id}.json"
        with open(complete_file, "w") as f:
            json.dump(response, f, indent=2)

        in_progress_file = self.in_progress_dir / f"{task_id}.json"
        if in_progress_file.exists():
            in_progress_file.unlink()

        if response.get("status") == "failed":
            failed_file = self.failed_dir / f"{task_id}.json"
            with open(failed_file, "w") as f:
                json.dump(response, f, indent=2)
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_task_processor.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/task_processor.py tests/test_task_processor.py
git commit -m "feat: add TaskProcessor for webapp transcode/insert tasks"
```

---

## Task 6: Update Process Action to Create Rip + Transcode Tasks

When user clicks "Process Selected Tracks", create both rip and transcode tasks.

**Files:**
- Modify: `src/amphigory/api/tasks.py`
- Modify: `src/amphigory/templates/disc.html`
- Test: `tests/test_tasks_api.py`

**Step 1: Write failing test**

Add to `tests/test_tasks_api.py`:

```python
@pytest.mark.asyncio
async def test_create_process_tasks_creates_rip_and_transcode(client, tmp_path, monkeypatch):
    """Test that process creates both rip and transcode tasks."""
    monkeypatch.setenv("AMPHIGORY_DATA", str(tmp_path))

    response = await client.post("/api/tasks/process", json={
        "tracks": [
            {
                "track_number": 1,
                "output_filename": "Movie (2024).mkv",
                "output_directory": "/media/ripped/Movie (2024)/",
                "preset": "H.265 MKV 1080p",
            }
        ],
        "disc_fingerprint": "abc123",
    })

    assert response.status_code == 201
    data = response.json()
    assert len(data["tasks"]) == 2

    rip_task = next(t for t in data["tasks"] if t["type"] == "rip")
    transcode_task = next(t for t in data["tasks"] if t["type"] == "transcode")

    # Transcode input should match rip output
    assert transcode_task["input"] == rip_task["output"]
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_tasks_api.py::test_create_process_tasks_creates_rip_and_transcode -v`
Expected: FAIL with 404 (endpoint doesn't exist)

**Step 3: Add POST /api/tasks/process endpoint**

In `src/amphigory/api/tasks.py`:

```python
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


@router.post("/process", status_code=status.HTTP_201_CREATED, response_model=ProcessTracksResponse)
async def process_tracks(request: ProcessTracksRequest) -> ProcessTracksResponse:
    """Create rip + transcode tasks for selected tracks.

    For each track, creates:
    1. Rip task (input: null, output: ripped path)
    2. Transcode task (input: ripped path, output: inbox path)
    """
    import os
    from amphigory.config import get_config

    tasks_dir = get_tasks_dir()
    ensure_directories(tasks_dir)
    config = get_config()

    created_tasks = []

    for track in request.tracks:
        # Build output paths
        ripped_dir = os.environ.get("DAEMON_RIPPED_DIR") or str(config.ripped_dir)
        output_dir = track.output_directory or ripped_dir
        ripped_path = f"{output_dir}{track.output_filename}"

        inbox_dir = str(config.inbox_dir)
        # Replace .mkv with .mp4 for transcoded output
        transcode_filename = track.output_filename.replace(".mkv", ".mp4")
        inbox_path = f"{inbox_dir}/{track.output_filename.rsplit('.', 1)[0]}/{transcode_filename}"

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
            "output": inbox_path,
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
            "output": inbox_path,
        })

    cleanup_old_tasks(tasks_dir)

    return ProcessTracksResponse(tasks=created_tasks)
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_tasks_api.py::test_create_process_tasks_creates_rip_and_transcode -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/amphigory/api/tasks.py tests/test_tasks_api.py
git commit -m "feat: add POST /api/tasks/process for rip+transcode creation"
```

---

## Task 7: Update Disc Review Page to Use Process Endpoint

Update the frontend to call the new process endpoint.

**Files:**
- Modify: `src/amphigory/templates/disc.html`

**Step 1: Update processSelectedTracks function**

In `src/amphigory/templates/disc.html`, update the `processSelectedTracks()` function:

```javascript
async function processSelectedTracks() {
    const checkboxes = document.querySelectorAll('input[name="track"]:checked');
    if (checkboxes.length === 0) {
        alert('Please select at least one track to process');
        return;
    }

    const fingerprint = scanResult?.fingerprint || window.knownDiscInfo?.fingerprint;
    if (!fingerprint) {
        alert('No disc fingerprint available. Please scan the disc first.');
        return;
    }

    const tracks = [];
    checkboxes.forEach(cb => {
        const row = cb.closest('tr');
        const trackNumber = parseInt(cb.value);
        const nameInput = row.querySelector('.track-name-input');
        const presetSelect = row.querySelector('.preset-select');
        const trackData = getTrackData(trackNumber);

        tracks.push({
            track_number: trackNumber,
            output_filename: `${nameInput?.value || `Track ${trackNumber}`}.mkv`,
            output_directory: null,  // Use default
            preset: presetSelect?.value || null,
            expected_size_bytes: trackData?.size_bytes,
            expected_duration: trackData?.duration,
        });
    });

    try {
        const response = await fetch('/api/tasks/process', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                tracks: tracks,
                disc_fingerprint: fingerprint,
            }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create tasks');
        }

        const data = await response.json();
        alert(`Created ${data.tasks.length} tasks. Check the Queue page for status.`);

        // Optionally redirect to queue page
        // window.location.href = '/queue';
    } catch (error) {
        console.error('Error creating tasks:', error);
        alert(`Error: ${error.message}`);
    }
}
```

**Step 2: Commit**

```bash
git add src/amphigory/templates/disc.html
git commit -m "feat: update disc review to use /api/tasks/process endpoint"
```

---

## Task 8: Add Failed Tasks Section to Queue Page

Add UI for viewing and managing failed tasks.

**Files:**
- Modify: `src/amphigory/templates/queue.html`
- Modify: `src/amphigory/api/tasks.py`

**Step 1: Add GET /api/tasks/failed endpoint**

In `src/amphigory/api/tasks.py`:

```python
@router.get("/failed", response_model=TaskListResponse)
async def get_failed_tasks() -> TaskListResponse:
    """Get all failed tasks from the failed/ directory."""
    tasks_dir = get_tasks_dir()
    failed_dir = tasks_dir / "failed"
    tasks = []

    if failed_dir.exists():
        for task_file in failed_dir.glob("*.json"):
            with open(task_file) as f:
                data = json.load(f)
            tasks.append(TaskStatusResponse(
                id=data.get("task_id", task_file.stem),
                type=data.get("type"),
                status="failed",
                error=data.get("error"),
            ))

    return TaskListResponse(tasks=tasks)
```

**Step 2: Add failed tasks section to queue.html**

In `src/amphigory/templates/queue.html`, add after completed-tasks section:

```html
<section class="failed-tasks card">
    <div class="section-header">
        <h2>Failed Tasks</h2>
    </div>
    <div id="failed-tasks">
        <p class="text-muted">No failed tasks</p>
    </div>
</section>
```

Add JavaScript:

```javascript
async function loadFailedTasks() {
    try {
        const response = await fetch('/api/tasks/failed');
        const data = await response.json();
        renderFailedTasks(data.tasks);
    } catch (error) {
        console.error('Error loading failed tasks:', error);
    }
}

function renderFailedTasks(failedTasks) {
    const container = document.getElementById('failed-tasks');

    if (failedTasks.length === 0) {
        container.innerHTML = '<p class="text-muted">No failed tasks</p>';
        return;
    }

    container.innerHTML = failedTasks.map(task => `
        <div class="task-item task-failed">
            <div class="task-header">
                <span class="task-type">${task.type}</span>
                <span class="task-id">${task.id.substring(0, 12)}...</span>
            </div>
            <div class="task-error">
                ${task.error?.message || 'Unknown error'}
            </div>
            <div class="task-actions">
                <button class="btn btn-small btn-primary" onclick="resubmitTask('${task.id}')">
                    Resubmit
                </button>
                <button class="btn btn-small btn-secondary" onclick="cancelFailedTask('${task.id}')">
                    Dismiss
                </button>
            </div>
        </div>
    `).join('');
}

async function resubmitTask(taskId) {
    // TODO: Implement resubmit
    alert('Resubmit not yet implemented');
}

async function cancelFailedTask(taskId) {
    try {
        await fetch(`/api/tasks/failed/${taskId}`, { method: 'DELETE' });
        loadFailedTasks();
    } catch (error) {
        console.error('Error dismissing task:', error);
    }
}
```

Update `startPolling()`:

```javascript
function startPolling() {
    loadTasks();
    loadFailedTasks();
    setInterval(loadTasks, 5000);
    setInterval(loadFailedTasks, 10000);
}
```

**Step 3: Add DELETE /api/tasks/failed/{task_id} endpoint**

```python
@router.delete("/failed/{task_id}")
async def dismiss_failed_task(task_id: str):
    """Remove a task from the failed/ directory."""
    tasks_dir = get_tasks_dir()
    failed_file = tasks_dir / "failed" / f"{task_id}.json"

    if not failed_file.exists():
        raise HTTPException(status_code=404, detail="Failed task not found")

    failed_file.unlink()
    return {"status": "dismissed"}
```

**Step 4: Commit**

```bash
git add src/amphigory/api/tasks.py src/amphigory/templates/queue.html
git commit -m "feat: add failed tasks section to queue page"
```

---

## Task 9: Remove Jobs Infrastructure

Remove the old database-based job queue.

**Files:**
- Delete: `src/amphigory/jobs.py`
- Delete: `src/amphigory/job_runner.py`
- Delete: `src/amphigory/api/jobs.py`
- Delete: `tests/test_jobs.py`
- Delete: `tests/test_job_runner.py`
- Modify: `src/amphigory/main.py`
- Modify: `src/amphigory/database.py`

**Step 1: Remove imports and router from main.py**

In `src/amphigory/main.py`, remove:

```python
# Remove from imports
from amphigory.api import disc_router, tracks_router, jobs_router, settings_router, tasks_router, drives_router, library_router, cleanup_router
# Change to:
from amphigory.api import disc_router, tracks_router, settings_router, tasks_router, drives_router, library_router, cleanup_router

# Remove router include
app.include_router(jobs_router)
```

Also update `__init__.py` in `src/amphigory/api/`:

```python
# Remove jobs_router from exports
```

**Step 2: Remove jobs table from schema**

In `src/amphigory/database.py`, remove the jobs table from SCHEMA:

```python
# Remove this block:
-- Job queue for ripping and transcoding
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    ...
);
```

**Step 3: Delete files**

```bash
git rm src/amphigory/jobs.py
git rm src/amphigory/job_runner.py
git rm src/amphigory/api/jobs.py
git rm tests/test_jobs.py
git rm tests/test_job_runner.py
```

**Step 4: Run tests to verify nothing broke**

Run: `PYTHONPATH=src .venv/bin/pytest tests/ -v`
Expected: PASS (with fewer tests)

**Step 5: Commit**

```bash
git add -A
git commit -m "refactor: remove old jobs infrastructure in favor of unified task queue"
```

---

## Task 10: Start TaskProcessor in Webapp Lifespan

Wire up the TaskProcessor to start on webapp startup.

**Files:**
- Modify: `src/amphigory/main.py`

**Step 1: Add TaskProcessor to lifespan**

```python
from amphigory.task_processor import TaskProcessor
from amphigory.websocket import manager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    _configure_logging()

    # Initialize database
    config = get_config()
    app.state.db = Database(config.database_path)
    await app.state.db.initialize()

    # Start task processor
    import os
    data_dir = Path(os.environ.get("AMPHIGORY_DATA", "/data"))

    def progress_callback(progress: dict):
        # Broadcast to all connected clients
        asyncio.create_task(manager.broadcast({
            "type": "progress",
            **progress,
        }))

    app.state.task_processor = TaskProcessor(
        db=app.state.db,
        tasks_dir=data_dir / "tasks",
        inbox_dir=config.inbox_dir,
        preset_dir=config.preset_dir,
        progress_callback=progress_callback,
    )
    await app.state.task_processor.start()

    yield

    # Cleanup
    await app.state.task_processor.stop()
    await app.state.db.close()
```

**Step 2: Commit**

```bash
git add src/amphigory/main.py
git commit -m "feat: start TaskProcessor on webapp startup"
```

---

## Task 11: Update Dashboard to Show Tasks Instead of Jobs

Update the dashboard to use the unified task API.

**Files:**
- Modify: `src/amphigory/templates/index.html`

**Step 1: Update active jobs section**

Change "Active Jobs" to "Active Tasks" and update HTMX polling:

```html
<section class="card">
    <h2>Active Tasks</h2>
    <div id="active-tasks"
         hx-get="/api/tasks/active-html"
         hx-trigger="load, every 2s"
         hx-swap="innerHTML">
        <p class="text-muted">Loading...</p>
    </div>
</section>
```

**Step 2: Add /api/tasks/active-html endpoint**

In `src/amphigory/api/tasks.py`:

```python
from fastapi.responses import HTMLResponse

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

    html = ""
    for task_file in tasks:
        with open(task_file) as f:
            data = json.load(f)
        task_type = data.get("type", "task")
        task_id = data.get("id", task_file.stem)
        truncated_id = task_id[11:] if len(task_id) > 20 else task_id  # HHMM.ffffff-type

        html += f'''
        <div class="task-item">
            <div class="task-info">
                <span class="task-type">{task_type.title()}</span>
                <span class="task-id">{truncated_id}</span>
            </div>
            <div class="progress-bar">
                <div class="progress-bar-fill" id="progress-{task_id}" style="width: 0%"></div>
            </div>
        </div>
        '''

    return html
```

**Step 3: Commit**

```bash
git add src/amphigory/templates/index.html src/amphigory/api/tasks.py
git commit -m "feat: update dashboard to show tasks instead of jobs"
```

---

## Task 12: Integration Tests

Add integration tests for the full rip→transcode workflow.

**Files:**
- Create: `tests/test_task_workflow.py`

**Step 1: Write integration test**

```python
import pytest
import json
from pathlib import Path


@pytest.mark.asyncio
async def test_full_process_workflow(client, tmp_path, monkeypatch):
    """Test creating rip+transcode tasks and dependency resolution."""
    monkeypatch.setenv("AMPHIGORY_DATA", str(tmp_path))

    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "queued").mkdir(parents=True)
    (tasks_dir / "in_progress").mkdir(parents=True)
    (tasks_dir / "complete").mkdir(parents=True)
    (tasks_dir / "failed").mkdir(parents=True)

    # Create process request
    response = await client.post("/api/tasks/process", json={
        "tracks": [{
            "track_number": 1,
            "output_filename": "Test Movie (2024).mkv",
            "preset": "H.265 MKV 1080p",
        }],
        "disc_fingerprint": "test-fingerprint-123",
    })

    assert response.status_code == 201
    data = response.json()
    assert len(data["tasks"]) == 2

    # Verify tasks in filesystem
    queued_files = list((tasks_dir / "queued").glob("*.json"))
    assert len(queued_files) == 2

    # Verify tasks.json ordering
    with open(tasks_dir / "tasks.json") as f:
        task_order = json.load(f)
    assert len(task_order) == 2
    assert task_order[0].endswith("-rip")
    assert task_order[1].endswith("-transcode")

    # Verify dependency chain
    rip_task = next(t for t in data["tasks"] if t["type"] == "rip")
    transcode_task = next(t for t in data["tasks"] if t["type"] == "transcode")
    assert transcode_task["input"] == rip_task["output"]
```

**Step 2: Run test**

Run: `PYTHONPATH=src .venv/bin/pytest tests/test_task_workflow.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_task_workflow.py
git commit -m "test: add integration tests for task workflow"
```

---

## Summary

This plan covers:

1. **Task Structure** (Tasks 1-2): Add input/output fields, new task types
2. **Shared Library** (Task 3): Create unified queue with dependency resolution
3. **Daemon Updates** (Task 4): Filter to only process scan/rip tasks
4. **Webapp Processor** (Task 5): Create TaskProcessor for transcode/insert
5. **Process Endpoint** (Tasks 6-7): Create rip+transcode tasks together
6. **Failed Tasks UI** (Task 8): View and manage failed tasks
7. **Migration** (Task 9): Remove old jobs infrastructure
8. **Integration** (Tasks 10-12): Wire up and test full workflow

**Total: 12 tasks**
