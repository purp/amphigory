"""Integration tests for the full Amphigory workflow.

Tests the interaction between webapp components, simulating daemon behavior.
"""

import json
import pytest
from pathlib import Path
from datetime import datetime
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


@pytest.fixture
def registered_daemon(client):
    """Register a daemon and return its ID."""
    from amphigory.api.settings import _daemons, RegisteredDaemon

    daemon_id = "test-daemon@macbook"
    now = datetime.now()
    _daemons[daemon_id] = RegisteredDaemon(
        daemon_id=daemon_id,
        makemkvcon_path="/usr/local/bin/makemkvcon",
        webapp_basedir="/data",
        connected_at=now,
        last_seen=now,
        disc_inserted=True,
        disc_device="/dev/disk2",
        disc_volume="MY_MOVIE_DISC",
    )

    yield daemon_id

    if daemon_id in _daemons:
        del _daemons[daemon_id]


class TestFullScanWorkflow:
    """Test complete scan workflow from disc detection to results."""

    def test_disc_status_shows_daemon_disc(self, client, registered_daemon):
        """Disc status reflects daemon's reported disc state."""
        response = client.get("/api/disc/status")
        assert response.status_code == 200
        data = response.json()
        assert data["has_disc"] is True
        assert data["volume_name"] == "MY_MOVIE_DISC"
        assert data["daemon_id"] == registered_daemon

    def test_scan_creates_task_for_daemon(self, client, tasks_dir, registered_daemon):
        """Scanning creates a task file for daemon to process."""
        response = client.post("/api/disc/scan")
        assert response.status_code == 202
        data = response.json()
        task_id = data["task_id"]

        # Verify task file exists
        task_file = tasks_dir / "queued" / f"{task_id}.json"
        assert task_file.exists()

        with open(task_file) as f:
            task_data = json.load(f)
        assert task_data["type"] == "scan"

    def test_scan_result_available_after_daemon_completes(self, client, tasks_dir, registered_daemon):
        """Scan results are available after daemon writes to complete/."""
        # Simulate daemon completing a scan
        result_file = tasks_dir / "complete" / "daemon-scan-result.json"
        with open(result_file, "w") as f:
            json.dump({
                "task_id": "daemon-scan-result",
                "status": "success",
                "result": {
                    "disc_name": "MY_MOVIE_DISC",
                    "disc_type": "bluray",
                    "tracks": [
                        {"number": 0, "duration": "2:15:30", "size_bytes": 25000000000},
                        {"number": 1, "duration": "0:05:00", "size_bytes": 500000000},
                    ],
                },
                "completed_at": datetime.now().isoformat(),
            }, f)

        response = client.get("/api/disc/scan-result")
        assert response.status_code == 200
        data = response.json()
        assert data["disc_name"] == "MY_MOVIE_DISC"
        assert len(data["tracks"]) == 2


class TestFullRipWorkflow:
    """Test complete rip workflow from track selection to completion."""

    def test_rip_creates_task_with_track_info(self, client, tasks_dir):
        """Creating a rip task includes track and output info."""
        response = client.post("/api/tasks/rip", json={
            "track_number": 0,
            "output_filename": "movie.mkv",
            "output_directory": "/media/ripped",
        })

        assert response.status_code == 201
        task_id = response.json()["task_id"]

        task_file = tasks_dir / "queued" / f"{task_id}.json"
        with open(task_file) as f:
            task_data = json.load(f)

        assert task_data["type"] == "rip"
        assert task_data["track"]["number"] == 0
        assert task_data["output"]["filename"] == "movie.mkv"

    def test_task_lifecycle(self, client, tasks_dir):
        """Tasks move through queued -> in_progress -> complete."""
        # Create a task
        response = client.post("/api/tasks/scan")
        task_id = response.json()["task_id"]

        # Initially queued
        response = client.get(f"/api/tasks/{task_id}")
        assert response.json()["status"] == "queued"

        # Simulate daemon moving to in_progress
        queued_file = tasks_dir / "queued" / f"{task_id}.json"
        in_progress_file = tasks_dir / "in_progress" / f"{task_id}.json"
        queued_file.rename(in_progress_file)

        response = client.get(f"/api/tasks/{task_id}")
        assert response.json()["status"] == "in_progress"

        # Simulate daemon completing
        in_progress_file.unlink()
        complete_file = tasks_dir / "complete" / f"{task_id}.json"
        with open(complete_file, "w") as f:
            json.dump({
                "task_id": task_id,
                "status": "success",
                "result": {"disc_name": "TEST", "disc_type": "dvd", "tracks": []},
            }, f)

        response = client.get(f"/api/tasks/{task_id}")
        assert response.json()["status"] == "success"

    def test_multiple_rip_tasks_queue(self, client, tasks_dir):
        """Multiple rip tasks are queued in order."""
        task_ids = []
        for i in range(3):
            response = client.post("/api/tasks/rip", json={
                "track_number": i,
                "output_filename": f"track{i}.mkv",
            })
            task_ids.append(response.json()["task_id"])

        # All should be queued
        response = client.get("/api/tasks")
        queued = [t for t in response.json()["tasks"] if t["status"] == "queued"]
        assert len(queued) == 3


class TestPageRoutes:
    """Test that all main pages load correctly."""

    def test_dashboard_loads(self, client):
        """Dashboard page loads."""
        response = client.get("/")
        assert response.status_code == 200
        assert "Amphigory" in response.text

    def test_disc_page_loads(self, client):
        """Disc review page loads."""
        response = client.get("/disc")
        assert response.status_code == 200
        assert "Disc Review" in response.text

    def test_queue_page_loads(self, client):
        """Queue page loads."""
        response = client.get("/queue")
        assert response.status_code == 200
        assert "Task Queue" in response.text

    def test_settings_page_loads(self, client):
        """Settings page loads."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "Settings" in response.text

    def test_health_check(self, client):
        """Health check returns healthy."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


class TestWebSocketIntegration:
    """Test WebSocket endpoint functionality."""

    def test_websocket_connects(self, client):
        """WebSocket connection can be established."""
        with client.websocket_connect("/ws") as websocket:
            # Just test that connection works
            pass

    def test_daemon_registration_via_websocket(self, client):
        """Daemon can register via WebSocket."""
        from amphigory.api.settings import _daemons

        initial_count = len(_daemons)

        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({
                "type": "daemon_config",
                "daemon_id": "ws-test-daemon",
                "makemkvcon_path": "/usr/bin/makemkvcon",
                "webapp_basedir": "/data",
            })

            # Give it a moment to process
            import time
            time.sleep(0.1)

            assert "ws-test-daemon" in _daemons

        # Cleanup happens on disconnect
        import time
        time.sleep(0.1)

    def test_disc_event_updates_daemon_status(self, client):
        """Disc events update daemon's disc status."""
        from amphigory.api.settings import _daemons

        with client.websocket_connect("/ws") as websocket:
            # Register first
            websocket.send_json({
                "type": "daemon_config",
                "daemon_id": "disc-test-daemon",
                "webapp_basedir": "/data",
            })
            import time
            time.sleep(0.1)

            # Send disc event
            websocket.send_json({
                "type": "disc_event",
                "event": "inserted",
                "device": "/dev/disk3",
                "volume_name": "TEST_DISC",
            })
            time.sleep(0.1)

            daemon = _daemons.get("disc-test-daemon")
            assert daemon is not None
            assert daemon.disc_inserted is True
            assert daemon.disc_volume == "TEST_DISC"
