"""Tests for updated disc API that reads from daemon results."""

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


class TestDiscScan:
    """Tests for POST /api/disc/scan."""

    def test_creates_scan_task(self, client, tasks_dir):
        """Scanning disc creates a scan task."""
        response = client.post("/api/disc/scan")

        assert response.status_code == 202  # Accepted
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "scanning"

        # Verify task file was created
        task_file = tasks_dir / "queued" / f"{data['task_id']}.json"
        assert task_file.exists()

    def test_task_id_has_human_readable_format(self, client, tasks_dir):
        """Task ID uses human-readable timestamp format."""
        response = client.post("/api/disc/scan")

        assert response.status_code == 202
        data = response.json()
        task_id = data["task_id"]

        # Verify format: YYYY-MM-DDTHH:MM:SS.ffffff-scan
        pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}-scan$'
        assert re.match(pattern, task_id), f"Task ID '{task_id}' does not match expected format"

        # Verify the task type suffix
        assert task_id.endswith("-scan")

    def test_task_file_uses_human_readable_name(self, client, tasks_dir):
        """Task file is created with human-readable name."""
        response = client.post("/api/disc/scan")

        task_id = response.json()["task_id"]
        task_file = tasks_dir / "queued" / f"{task_id}.json"

        assert task_file.exists()

        # Verify file name matches pattern
        assert re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}-scan\.json$', task_file.name)

    def test_task_id_in_json_matches_filename(self, client, tasks_dir):
        """Task ID in JSON matches the filename (without .json)."""
        response = client.post("/api/disc/scan")

        task_id = response.json()["task_id"]
        task_file = tasks_dir / "queued" / f"{task_id}.json"

        with open(task_file) as f:
            task_data = json.load(f)

        assert task_data["id"] == task_id
        assert task_file.stem == task_id


class TestDiscScanResult:
    """Tests for GET /api/disc/scan-result."""

    def test_returns_latest_scan_result_without_task_id(self, client, tasks_dir):
        """Returns the most recent scan result when no task_id specified."""
        # Create a completed scan task
        result_file = tasks_dir / "complete" / "scan-task-123.json"
        with open(result_file, "w") as f:
            json.dump({
                "task_id": "scan-task-123",
                "status": "success",
                "result": {
                    "disc_name": "MY_MOVIE",
                    "disc_type": "bluray",
                    "tracks": [
                        {
                            "number": 0,
                            "duration": "2:15:30",
                            "size_bytes": 25000000000,
                            "chapters": 32,
                            "resolution": "1920x1080",
                        }
                    ],
                },
                "completed_at": "2024-01-15T10:30:00",
            }, f)

        response = client.get("/api/disc/scan-result")

        assert response.status_code == 200
        data = response.json()
        assert data["disc_name"] == "MY_MOVIE"
        assert len(data["tracks"]) == 1

    def test_returns_specific_task_result_when_task_id_provided(self, client, tasks_dir):
        """Returns only the specified task's result when task_id is provided."""
        # Create an OLD completed scan (should be ignored)
        old_result = tasks_dir / "complete" / "old-scan.json"
        with open(old_result, "w") as f:
            json.dump({
                "task_id": "old-scan",
                "status": "success",
                "result": {
                    "disc_name": "OLD_MOVIE",
                    "disc_type": "dvd",
                    "tracks": [],
                },
                "completed_at": "2024-01-01T00:00:00",
            }, f)

        # Create the NEW completed scan we actually want
        new_result = tasks_dir / "complete" / "new-scan.json"
        with open(new_result, "w") as f:
            json.dump({
                "task_id": "new-scan",
                "status": "success",
                "result": {
                    "disc_name": "NEW_MOVIE",
                    "disc_type": "bluray",
                    "tracks": [{"number": 1}],
                },
                "completed_at": "2024-01-15T10:30:00",
            }, f)

        # Request the specific new task
        response = client.get("/api/disc/scan-result?task_id=new-scan")

        assert response.status_code == 200
        data = response.json()
        assert data["disc_name"] == "NEW_MOVIE"  # Not OLD_MOVIE

    def test_returns_404_when_specific_task_not_complete(self, client, tasks_dir):
        """Returns 404 when the specified task hasn't completed yet."""
        # Create an old completed scan (should be ignored because we're asking for specific task)
        old_result = tasks_dir / "complete" / "old-scan.json"
        with open(old_result, "w") as f:
            json.dump({
                "task_id": "old-scan",
                "status": "success",
                "result": {
                    "disc_name": "OLD_MOVIE",
                    "disc_type": "dvd",
                    "tracks": [],
                },
                "completed_at": "2024-01-01T00:00:00",
            }, f)

        # Request a task that doesn't exist in complete/
        response = client.get("/api/disc/scan-result?task_id=nonexistent-task")

        assert response.status_code == 404
        assert "not complete" in response.json()["detail"].lower()

    def test_returns_404_when_no_scan_results(self, client, tasks_dir):
        """Returns 404 when no scan results exist."""
        response = client.get("/api/disc/scan-result")
        assert response.status_code == 404

    def test_rejects_path_traversal_in_task_id(self, client, tasks_dir):
        """Rejects task_id with path traversal characters."""
        # These should all return 400, not attempt to read files
        dangerous_ids = [
            "../../../etc/passwd",
            "..\\..\\windows\\system32",
            "foo/../bar",
            "/etc/passwd",
        ]
        for task_id in dangerous_ids:
            response = client.get(f"/api/disc/scan-result?task_id={task_id}")
            assert response.status_code == 400, f"Expected 400 for task_id={task_id}"
            assert "Invalid task_id" in response.json()["detail"]


class TestDiscStatus:
    """Tests for GET /api/disc/status."""

    def test_returns_disc_status_from_daemon(self, client):
        """Returns disc status from connected daemon."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from datetime import datetime

        # Register a daemon with disc info
        _daemons["test-daemon"] = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/local/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
            disc_inserted=True,
            disc_device="/dev/disk2",
            disc_volume="MY_DISC",
        )

        try:
            response = client.get("/api/disc/status")

            assert response.status_code == 200
            data = response.json()
            assert data["has_disc"] is True
            assert data["volume_name"] == "MY_DISC"
        finally:
            del _daemons["test-daemon"]

    def test_returns_no_disc_when_no_daemon(self, client):
        """Returns no disc when no daemon connected."""
        from amphigory.api.settings import _daemons
        _daemons.clear()

        response = client.get("/api/disc/status")

        assert response.status_code == 200
        data = response.json()
        assert data["has_disc"] is False
