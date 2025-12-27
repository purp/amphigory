"""Tests for tasks API endpoints."""

import json
import re
import pytest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


@pytest.fixture
def tasks_dir(tmp_path):
    """Create a temporary tasks directory structure."""
    tasks = tmp_path / "tasks"
    (tasks / "queued").mkdir(parents=True)
    (tasks / "in_progress").mkdir(parents=True)
    (tasks / "complete").mkdir(parents=True)
    return tasks


@pytest.fixture
def client(tasks_dir):
    """Create test client with mocked tasks directory."""
    with patch.dict("os.environ", {"AMPHIGORY_DATA": str(tasks_dir.parent)}):
        from amphigory.main import app
        with TestClient(app) as client:
            yield client


class TestCreateScanTask:
    """Tests for POST /api/tasks/scan."""

    def test_creates_scan_task_file(self, client, tasks_dir):
        """Creating a scan task writes a JSON file to queued/."""
        response = client.post("/api/tasks/scan")

        assert response.status_code == 201
        data = response.json()
        assert "task_id" in data
        assert data["type"] == "scan"
        assert data["status"] == "queued"

        # Verify file was created
        task_file = tasks_dir / "queued" / f"{data['task_id']}.json"
        assert task_file.exists()

        # Verify file contents
        with open(task_file) as f:
            task_data = json.load(f)
        assert task_data["type"] == "scan"
        assert task_data["id"] == data["task_id"]

    def test_task_id_has_human_readable_format(self, client, tasks_dir):
        """Task ID uses human-readable timestamp format."""
        response = client.post("/api/tasks/scan")

        assert response.status_code == 201
        data = response.json()
        task_id = data["task_id"]

        # Verify format: YYYYMMDDTHHMMSS.ffffff-scan (ISO8601 basic with dot separator)
        pattern = r'^\d{8}T\d{6}\.\d{6}-scan$'
        assert re.match(pattern, task_id), f"Task ID '{task_id}' does not match expected format"

        # Verify the task type suffix
        assert task_id.endswith("-scan")

    def test_updates_tasks_json(self, client, tasks_dir):
        """Creating a task adds its ID to tasks.json."""
        response = client.post("/api/tasks/scan")
        task_id = response.json()["task_id"]

        tasks_json = tasks_dir / "tasks.json"
        assert tasks_json.exists()

        with open(tasks_json) as f:
            task_order = json.load(f)
        assert task_id in task_order


class TestCreateRipTask:
    """Tests for POST /api/tasks/rip."""

    def test_creates_rip_task_file(self, client, tasks_dir):
        """Creating a rip task writes a JSON file to queued/."""
        response = client.post(
            "/api/tasks/rip",
            json={
                "track_number": 1,
                "output_filename": "movie.mkv",
            }
        )

        assert response.status_code == 201
        data = response.json()
        assert "task_id" in data
        assert data["type"] == "rip"
        assert data["status"] == "queued"

        # Verify file was created
        task_file = tasks_dir / "queued" / f"{data['task_id']}.json"
        assert task_file.exists()

        # Verify file contents
        with open(task_file) as f:
            task_data = json.load(f)
        assert task_data["type"] == "rip"
        assert task_data["track"]["number"] == 1

    def test_task_id_has_human_readable_format(self, client, tasks_dir):
        """Rip task ID uses human-readable timestamp format."""
        response = client.post(
            "/api/tasks/rip",
            json={
                "track_number": 1,
                "output_filename": "movie.mkv",
            }
        )

        assert response.status_code == 201
        data = response.json()
        task_id = data["task_id"]

        # Verify format: YYYYMMDDTHHMMSS.ffffff-rip (ISO8601 basic with dot separator)
        pattern = r'^\d{8}T\d{6}\.\d{6}-rip$'
        assert re.match(pattern, task_id), f"Task ID '{task_id}' does not match expected format"

        # Verify the task type suffix
        assert task_id.endswith("-rip")

    def test_requires_track_number(self, client):
        """Rip task requires track_number."""
        response = client.post(
            "/api/tasks/rip",
            json={"output_filename": "movie.mkv"}
        )
        assert response.status_code == 422

    def test_task_ids_sort_chronologically(self, client, tasks_dir):
        """Task IDs with timestamps sort chronologically."""
        import time

        # Create first task
        response1 = client.post(
            "/api/tasks/rip",
            json={"track_number": 1, "output_filename": "movie1.mkv"}
        )
        task_id1 = response1.json()["task_id"]

        # Wait a tiny bit to ensure different timestamps
        time.sleep(0.01)

        # Create second task
        response2 = client.post(
            "/api/tasks/rip",
            json={"track_number": 2, "output_filename": "movie2.mkv"}
        )
        task_id2 = response2.json()["task_id"]

        # Verify earlier task has earlier ID (lexicographic sort)
        assert task_id1 < task_id2


class TestGetTaskStatus:
    """Tests for GET /api/tasks/{task_id}."""

    def test_queued_task_status(self, client, tasks_dir):
        """Getting status of queued task returns 'queued'."""
        # Create task first
        response = client.post("/api/tasks/scan")
        task_id = response.json()["task_id"]

        # Get status
        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "queued"

    def test_in_progress_task_status(self, client, tasks_dir):
        """Getting status of in-progress task returns 'in_progress'."""
        # Create a task file directly in in_progress/
        task_id = "test-in-progress-123"
        task_file = tasks_dir / "in_progress" / f"{task_id}.json"
        with open(task_file, "w") as f:
            json.dump({"id": task_id, "type": "scan"}, f)

        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "in_progress"

    def test_completed_task_returns_result(self, client, tasks_dir):
        """Getting status of completed task returns result."""
        task_id = "test-complete-123"
        result_file = tasks_dir / "complete" / f"{task_id}.json"
        with open(result_file, "w") as f:
            json.dump({
                "task_id": task_id,
                "status": "success",
                "result": {
                    "disc_name": "Test Disc",
                    "disc_type": "bluray",
                    "tracks": [],
                },
            }, f)

        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["result"]["disc_name"] == "Test Disc"

    def test_unknown_task_returns_404(self, client):
        """Getting status of unknown task returns 404."""
        response = client.get("/api/tasks/nonexistent-task")
        assert response.status_code == 404


class TestListTasks:
    """Tests for GET /api/tasks."""

    def test_lists_all_tasks(self, client, tasks_dir):
        """Lists tasks from all states."""
        # Create tasks in different states
        task1 = tasks_dir / "queued" / "task-1.json"
        task2 = tasks_dir / "in_progress" / "task-2.json"
        task3 = tasks_dir / "complete" / "task-3.json"

        with open(task1, "w") as f:
            json.dump({"id": "task-1", "type": "scan"}, f)
        with open(task2, "w") as f:
            json.dump({"id": "task-2", "type": "rip"}, f)
        with open(task3, "w") as f:
            json.dump({"task_id": "task-3", "status": "success"}, f)

        response = client.get("/api/tasks")
        assert response.status_code == 200
        data = response.json()

        assert len(data["tasks"]) == 3
        statuses = {t["id"]: t["status"] for t in data["tasks"]}
        assert statuses["task-1"] == "queued"
        assert statuses["task-2"] == "in_progress"
        assert statuses["task-3"] == "success"

    def test_empty_queue_returns_empty_list(self, client):
        """Empty queue returns empty tasks list."""
        response = client.get("/api/tasks")
        assert response.status_code == 200
        assert response.json()["tasks"] == []


class TestCleanupOldTasks:
    """Tests for cleanup_old_tasks function."""

    def test_removes_old_completed_tasks(self, tasks_dir):
        """Completed tasks older than max_age_hours are removed."""
        import time
        from amphigory.api.tasks import cleanup_old_tasks

        # Create an old task file (modify mtime to be old)
        task_file = tasks_dir / "complete" / "old-task.json"
        with open(task_file, "w") as f:
            json.dump({"task_id": "old-task", "status": "success"}, f)

        # Set mtime to 25 hours ago
        old_time = time.time() - (25 * 3600)
        import os
        os.utime(task_file, (old_time, old_time))

        # Create a recent task file
        recent_file = tasks_dir / "complete" / "recent-task.json"
        with open(recent_file, "w") as f:
            json.dump({"task_id": "recent-task", "status": "success"}, f)

        result = cleanup_old_tasks(tasks_dir, max_age_hours=24)

        assert result["removed_files"] == 1
        assert not task_file.exists()
        assert recent_file.exists()

    def test_removes_stale_tasks_json_entries(self, tasks_dir):
        """Entries in tasks.json without corresponding files are removed."""
        from amphigory.api.tasks import cleanup_old_tasks

        # Create a task file
        task_file = tasks_dir / "queued" / "existing-task.json"
        with open(task_file, "w") as f:
            json.dump({"id": "existing-task", "type": "scan"}, f)

        # Create tasks.json with an extra stale entry
        tasks_json = tasks_dir / "tasks.json"
        with open(tasks_json, "w") as f:
            json.dump(["existing-task", "deleted-task", "another-deleted"], f)

        result = cleanup_old_tasks(tasks_dir)

        assert result["removed_entries"] == 2

        with open(tasks_json) as f:
            remaining = json.load(f)
        assert remaining == ["existing-task"]

    def test_cleanup_handles_missing_directories(self, tmp_path):
        """Cleanup doesn't fail if directories don't exist."""
        from amphigory.api.tasks import cleanup_old_tasks

        empty_tasks_dir = tmp_path / "empty_tasks"
        empty_tasks_dir.mkdir()

        result = cleanup_old_tasks(empty_tasks_dir)

        assert result["removed_files"] == 0
        assert result["removed_entries"] == 0

    def test_rip_task_triggers_cleanup(self, client, tasks_dir):
        """Creating a rip task triggers cleanup of old tasks."""
        import time
        import os

        # Create an old completed task
        task_file = tasks_dir / "complete" / "old-rip-task.json"
        with open(task_file, "w") as f:
            json.dump({"task_id": "old-rip-task", "status": "success"}, f)

        # Set mtime to 25 hours ago
        old_time = time.time() - (25 * 3600)
        os.utime(task_file, (old_time, old_time))

        # Also add a stale entry to tasks.json
        tasks_json = tasks_dir / "tasks.json"
        with open(tasks_json, "w") as f:
            json.dump(["stale-entry"], f)

        # Create a new rip task (this should trigger cleanup)
        response = client.post(
            "/api/tasks/rip",
            json={"track_number": 1, "output_filename": "movie.mkv"}
        )

        assert response.status_code == 201

        # Old file should be removed
        assert not task_file.exists()

        # tasks.json should only have the new task (stale entry removed)
        with open(tasks_json) as f:
            entries = json.load(f)
        assert len(entries) == 1
        assert entries[0] == response.json()["task_id"]


class TestListTasksFullData:
    """Tests for full task data in list response."""

    def test_completed_task_includes_timing_fields(self, client, tasks_dir):
        """Completed tasks include started_at, completed_at, duration_seconds."""
        complete_dir = tasks_dir / "complete"
        complete_dir.mkdir(exist_ok=True)

        task_data = {
            "task_id": "20251225T120000.000000-rip",
            "type": "rip",
            "status": "success",
            "started_at": "2025-12-25T12:00:00.000000",
            "completed_at": "2025-12-25T12:45:32.000000",
            "duration_seconds": 2732,
            "result": {
                "destination": {
                    "directory": "/media/ripped",
                    "filename": "Movie.mkv"
                }
            }
        }
        with open(complete_dir / "20251225T120000.000000-rip.json", "w") as f:
            json.dump(task_data, f)

        response = client.get("/api/tasks")
        assert response.status_code == 200

        data = response.json()
        completed = [t for t in data["tasks"] if t["status"] == "success"]
        assert len(completed) >= 1

        task = completed[0]
        assert task["started_at"] == "2025-12-25T12:00:00.000000"
        assert task["completed_at"] == "2025-12-25T12:45:32.000000"
        assert task["duration_seconds"] == 2732
        assert task["result"]["destination"]["filename"] == "Movie.mkv"
        assert task["result"]["destination"]["directory"] == "/media/ripped"

    def test_failed_task_includes_error(self, client, tasks_dir):
        """Failed tasks include error details."""
        complete_dir = tasks_dir / "complete"
        complete_dir.mkdir(exist_ok=True)

        task_data = {
            "task_id": "20251225T130000.000000-rip",
            "type": "rip",
            "status": "failed",
            "started_at": "2025-12-25T13:00:00.000000",
            "completed_at": "2025-12-25T13:00:01.000000",
            "duration_seconds": 1,
            "error": {
                "code": "IO_ERROR",
                "message": "Read-only file system",
                "detail": "[Errno 30] Read-only file system: '/media'"
            }
        }
        with open(complete_dir / "20251225T130000.000000-rip.json", "w") as f:
            json.dump(task_data, f)

        response = client.get("/api/tasks")
        data = response.json()

        failed = [t for t in data["tasks"] if t["status"] == "failed"]
        assert len(failed) >= 1
        assert "error" in failed[0]
        assert failed[0]["error"]["detail"] == "[Errno 30] Read-only file system: '/media'"
