"""Tests for tasks API endpoints."""

import json
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

    def test_requires_track_number(self, client):
        """Rip task requires track_number."""
        response = client.post(
            "/api/tasks/rip",
            json={"output_filename": "movie.mkv"}
        )
        assert response.status_code == 422


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
