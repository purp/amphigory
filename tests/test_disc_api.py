"""Tests for updated disc API that reads from daemon results."""

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


class TestDiscScanResult:
    """Tests for GET /api/disc/scan-result."""

    def test_returns_latest_scan_result(self, client, tasks_dir):
        """Returns the most recent scan result."""
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

    def test_returns_404_when_no_scan_results(self, client, tasks_dir):
        """Returns 404 when no scan results exist."""
        response = client.get("/api/disc/scan-result")
        assert response.status_code == 404


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
