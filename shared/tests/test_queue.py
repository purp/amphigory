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

    task = temp_queue.get_next_task(TaskOwner.WEBAPP)
    assert task is None


def test_create_task_updates_tasks_json(temp_queue):
    """Test that create_task adds ID to tasks.json."""
    task = {
        "id": "20251227T140000.000000-scan",
        "type": "scan",
        "created_at": "2025-12-27T14:00:00",
        "input": None,
        "output": None,
    }
    temp_queue.create_task(task)

    order = temp_queue.get_task_order()
    assert "20251227T140000.000000-scan" in order


def test_complete_task_moves_to_complete(temp_queue):
    """Test that complete_task writes to complete/ and removes from in_progress/."""
    task = {
        "id": "20251227T140000.000000-scan",
        "type": "scan",
        "created_at": "2025-12-27T14:00:00",
        "input": None,
        "output": None,
    }
    temp_queue.create_task(task)

    # Claim the task
    claimed = temp_queue.get_next_task(TaskOwner.DAEMON)
    assert claimed is not None

    # Complete it
    response = {"task_id": task["id"], "status": "success"}
    temp_queue.complete_task(task["id"], response)

    # Verify it's in complete/
    complete_file = temp_queue.complete_dir / f"{task['id']}.json"
    assert complete_file.exists()

    # Verify it's not in in_progress/
    in_progress_file = temp_queue.in_progress_dir / f"{task['id']}.json"
    assert not in_progress_file.exists()


def test_failed_task_copied_to_failed_dir(temp_queue):
    """Test that failed tasks are copied to failed/ directory."""
    task = {
        "id": "20251227T140000.000000-scan",
        "type": "scan",
        "created_at": "2025-12-27T14:00:00",
        "input": None,
        "output": None,
    }
    temp_queue.create_task(task)
    temp_queue.get_next_task(TaskOwner.DAEMON)

    response = {"task_id": task["id"], "status": "failed", "error": {"message": "Test error"}}
    temp_queue.complete_task(task["id"], response)

    failed_file = temp_queue.failed_dir / f"{task['id']}.json"
    assert failed_file.exists()
