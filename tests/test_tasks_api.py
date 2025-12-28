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


class TestSyncCompletedRipTasks:
    """Tests for syncing completed rip tasks to database."""

    @pytest.fixture
    def db_with_disc_and_tracks(self, tmp_path, monkeypatch):
        """Create a test database with a disc and tracks."""
        import asyncio
        from amphigory.database import Database
        from amphigory.api import disc_repository

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        asyncio.run(db.initialize())
        monkeypatch.setattr(disc_repository, "get_db_path", lambda: db_path)

        # Create a disc with fingerprint and tracks
        async def create_disc_and_tracks():
            async with db.connection() as conn:
                await conn.execute(
                    "INSERT INTO discs (id, fingerprint, title) VALUES (?, ?, ?)",
                    (1, "test_fingerprint_123", "Test Movie")
                )
                # Create tracks with track_numbers 0, 1, 2
                for track_num in range(3):
                    await conn.execute(
                        "INSERT INTO tracks (disc_id, track_number, status) VALUES (?, ?, ?)",
                        (1, track_num, "discovered")
                    )
                await conn.commit()
        asyncio.run(create_disc_and_tracks())

        return db_path

    def test_sync_updates_track_ripped_path(self, client, tasks_dir, db_with_disc_and_tracks):
        """Completed rip task updates track's ripped_path in database."""
        import asyncio
        import aiosqlite

        # Create a completed rip task with matching fingerprint and track_number
        complete_dir = tasks_dir / "complete"
        complete_dir.mkdir(exist_ok=True)

        task_data = {
            "task_id": "20251226T100000.000000-rip",
            "type": "rip",
            "status": "success",
            "started_at": "2025-12-26T10:00:00.000000",
            "completed_at": "2025-12-26T10:30:00.000000",
            "duration_seconds": 1800,
            "source": {
                "disc_fingerprint": "test_fingerprint_123",
                "track_number": 1
            },
            "result": {
                "destination": {
                    "directory": "/media/ripped/Test Movie (2024)/",
                    "filename": "Test Movie (2024).mkv"
                }
            }
        }
        with open(complete_dir / "20251226T100000.000000-rip.json", "w") as f:
            json.dump(task_data, f)

        # Call list_tasks to trigger sync
        response = client.get("/api/tasks")
        assert response.status_code == 200

        # Check that the track was updated in the database
        async def check_track():
            async with aiosqlite.connect(db_with_disc_and_tracks) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    "SELECT ripped_path, status FROM tracks WHERE track_number = 1"
                )
                row = await cursor.fetchone()
                return dict(row)

        track = asyncio.run(check_track())
        assert track["ripped_path"] == "/media/ripped/Test Movie (2024)/Test Movie (2024).mkv"
        assert track["status"] == "ripped"

    def test_sync_does_not_update_already_ripped_tracks(self, client, tasks_dir, db_with_disc_and_tracks):
        """Sync skips tracks that already have ripped_path set."""
        import asyncio
        import aiosqlite

        # Pre-set the track's ripped_path
        async def preset_track():
            async with aiosqlite.connect(db_with_disc_and_tracks) as conn:
                await conn.execute(
                    "UPDATE tracks SET ripped_path = ?, status = ? WHERE track_number = 1",
                    ("/original/path.mkv", "ripped")
                )
                await conn.commit()
        asyncio.run(preset_track())

        # Create a completed rip task
        complete_dir = tasks_dir / "complete"
        complete_dir.mkdir(exist_ok=True)

        task_data = {
            "task_id": "20251226T110000.000000-rip",
            "type": "rip",
            "status": "success",
            "source": {
                "disc_fingerprint": "test_fingerprint_123",
                "track_number": 1
            },
            "result": {
                "destination": {
                    "directory": "/new/path/",
                    "filename": "new_file.mkv"
                }
            }
        }
        with open(complete_dir / "20251226T110000.000000-rip.json", "w") as f:
            json.dump(task_data, f)

        # Call list_tasks
        client.get("/api/tasks")

        # Track should still have original path
        async def check_track():
            async with aiosqlite.connect(db_with_disc_and_tracks) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    "SELECT ripped_path FROM tracks WHERE track_number = 1"
                )
                row = await cursor.fetchone()
                return row["ripped_path"]

        assert asyncio.run(check_track()) == "/original/path.mkv"

    def test_sync_handles_missing_disc(self, client, tasks_dir, db_with_disc_and_tracks):
        """Sync gracefully handles tasks with unknown disc fingerprint."""
        # Create a completed rip task with non-existent fingerprint
        complete_dir = tasks_dir / "complete"
        complete_dir.mkdir(exist_ok=True)

        task_data = {
            "task_id": "20251226T120000.000000-rip",
            "type": "rip",
            "status": "success",
            "source": {
                "disc_fingerprint": "unknown_fingerprint",
                "track_number": 0
            },
            "result": {
                "destination": {
                    "directory": "/media/ripped/",
                    "filename": "file.mkv"
                }
            }
        }
        with open(complete_dir / "20251226T120000.000000-rip.json", "w") as f:
            json.dump(task_data, f)

        # Should not raise an error
        response = client.get("/api/tasks")
        assert response.status_code == 200

    def test_sync_translates_daemon_paths_to_webapp_paths(self, client, tasks_dir, db_with_disc_and_tracks, monkeypatch):
        """Sync translates daemon paths to webapp paths using env vars."""
        import asyncio
        import aiosqlite

        # Set up path translation env vars
        monkeypatch.setenv("DAEMON_RIPPED_DIR", "/Volumes/Media Drive 1/Ripped")
        monkeypatch.setenv("AMPHIGORY_RIPPED_DIR", "/media/ripped")

        # Create a completed rip task with daemon-style path
        complete_dir = tasks_dir / "complete"
        complete_dir.mkdir(exist_ok=True)

        task_data = {
            "task_id": "20251226T130000.000000-rip",
            "type": "rip",
            "status": "success",
            "source": {
                "disc_fingerprint": "test_fingerprint_123",
                "track_number": 2
            },
            "result": {
                "destination": {
                    "directory": "/Volumes/Media Drive 1/Ripped/Test Movie (2024)/",
                    "filename": "Test Movie (2024).mkv"
                }
            }
        }
        with open(complete_dir / "20251226T130000.000000-rip.json", "w") as f:
            json.dump(task_data, f)

        # Call list_tasks to trigger sync
        response = client.get("/api/tasks")
        assert response.status_code == 200

        # Check that the track was updated with translated path
        async def check_track():
            async with aiosqlite.connect(db_with_disc_and_tracks) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    "SELECT ripped_path FROM tracks WHERE track_number = 2"
                )
                row = await cursor.fetchone()
                return row["ripped_path"]

        ripped_path = asyncio.run(check_track())
        # Should be translated from /Volumes/... to /media/ripped/...
        assert ripped_path == "/media/ripped/Test Movie (2024)/Test Movie (2024).mkv"


class TestCreateProcessTasks:
    """Tests for POST /api/tasks/process."""

    def test_create_process_tasks_creates_rip_and_transcode(self, client, tasks_dir):
        """Test that process creates both rip and transcode tasks."""
        # Ensure failed/ directory exists (for unified queue)
        (tasks_dir / "failed").mkdir(parents=True, exist_ok=True)

        response = client.post("/api/tasks/process", json={
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

    def test_process_multiple_tracks_creates_pairs(self, client, tmp_path, monkeypatch):
        """Test that processing multiple tracks creates rip+transcode pairs for each."""
        monkeypatch.setenv("AMPHIGORY_DATA", str(tmp_path))
        tasks_dir = tmp_path / "tasks"
        (tasks_dir / "queued").mkdir(parents=True, exist_ok=True)
        (tasks_dir / "in_progress").mkdir(parents=True, exist_ok=True)
        (tasks_dir / "complete").mkdir(parents=True, exist_ok=True)
        (tasks_dir / "failed").mkdir(parents=True, exist_ok=True)

        response = client.post("/api/tasks/process", json={
            "tracks": [
                {"track_number": 1, "output_filename": "Track1.mkv"},
                {"track_number": 2, "output_filename": "Track2.mkv"},
            ],
            "disc_fingerprint": "abc123",
        })

        assert response.status_code == 201
        data = response.json()
        assert len(data["tasks"]) == 4  # 2 tracks * 2 tasks each

        # Should have 2 rip tasks and 2 transcode tasks
        rip_tasks = [t for t in data["tasks"] if t["type"] == "rip"]
        transcode_tasks = [t for t in data["tasks"] if t["type"] == "transcode"]
        assert len(rip_tasks) == 2
        assert len(transcode_tasks) == 2

    def test_process_writes_task_files(self, client, tmp_path, monkeypatch):
        """Test that task JSON files are written to queued/ directory."""
        monkeypatch.setenv("AMPHIGORY_DATA", str(tmp_path))
        tasks_dir = tmp_path / "tasks"
        (tasks_dir / "queued").mkdir(parents=True, exist_ok=True)
        (tasks_dir / "in_progress").mkdir(parents=True, exist_ok=True)
        (tasks_dir / "complete").mkdir(parents=True, exist_ok=True)
        (tasks_dir / "failed").mkdir(parents=True, exist_ok=True)

        response = client.post("/api/tasks/process", json={
            "tracks": [{"track_number": 1, "output_filename": "Movie.mkv"}],
            "disc_fingerprint": "test-fingerprint",
        })

        assert response.status_code == 201

        # Check files were written
        queued_files = list((tasks_dir / "queued").glob("*.json"))
        assert len(queued_files) == 2

        # Check tasks.json was updated
        tasks_json = tasks_dir / "tasks.json"
        assert tasks_json.exists()
        with open(tasks_json) as f:
            task_order = json.load(f)
        assert len(task_order) == 2
        assert task_order[0].endswith("-rip")
        assert task_order[1].endswith("-transcode")


class TestActiveTasksHtml:
    """Tests for GET /api/tasks/active-html."""

    def test_returns_no_active_tasks_message_when_empty(self, client, tasks_dir):
        """Returns empty message when no tasks in in_progress/."""
        response = client.get("/api/tasks/active-html")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "No active tasks" in response.text

    def test_returns_no_active_tasks_when_directory_missing(self, tmp_path):
        """Returns empty message when in_progress/ directory doesn't exist."""
        # Create tasks_dir without in_progress/
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir()
        (tasks_dir / "queued").mkdir()
        (tasks_dir / "complete").mkdir()
        # Explicitly do NOT create in_progress/

        from unittest.mock import patch
        with patch.dict("os.environ", {"AMPHIGORY_DATA": str(tmp_path)}):
            from amphigory.main import app
            from fastapi.testclient import TestClient
            with TestClient(app) as client:
                response = client.get("/api/tasks/active-html")
                assert response.status_code == 200
                assert "No active tasks" in response.text

    def test_returns_html_with_task_info(self, client, tasks_dir):
        """Returns HTML fragment with task information."""
        # Create an in-progress task
        task_id = "20251227T120000.000000-rip"
        task_data = {
            "id": task_id,
            "type": "rip",
            "track": {"number": 1}
        }
        task_file = tasks_dir / "in_progress" / f"{task_id}.json"
        with open(task_file, "w") as f:
            json.dump(task_data, f)

        response = client.get("/api/tasks/active-html")
        assert response.status_code == 200
        html = response.text

        # Check for task type (title case)
        assert "Rip" in html
        # Check for truncated task ID (everything after position 11)
        assert "120000.000000-rip" in html
        # Check for task-item div
        assert "task-item" in html
        # Check for progress bar
        assert "progress-bar" in html

    def test_returns_multiple_tasks(self, client, tasks_dir):
        """Returns HTML for multiple in-progress tasks."""
        # Create two in-progress tasks
        for i, task_type in enumerate(["rip", "transcode"]):
            task_id = f"20251227T12000{i}.000000-{task_type}"
            task_data = {"id": task_id, "type": task_type}
            task_file = tasks_dir / "in_progress" / f"{task_id}.json"
            with open(task_file, "w") as f:
                json.dump(task_data, f)

        response = client.get("/api/tasks/active-html")
        assert response.status_code == 200
        html = response.text

        # Both tasks should be present
        assert "Rip" in html
        assert "Transcode" in html
        # Two task-item divs
        assert html.count("task-item") == 2

    def test_handles_malformed_json_gracefully(self, client, tasks_dir):
        """Gracefully skips malformed JSON files."""
        # Create a valid task
        valid_task_id = "20251227T130000.000000-rip"
        valid_task = {"id": valid_task_id, "type": "rip"}
        with open(tasks_dir / "in_progress" / f"{valid_task_id}.json", "w") as f:
            json.dump(valid_task, f)

        # Create a malformed JSON file
        with open(tasks_dir / "in_progress" / "malformed.json", "w") as f:
            f.write("{invalid json")

        response = client.get("/api/tasks/active-html")
        assert response.status_code == 200
        html = response.text

        # Valid task should be present
        assert "Rip" in html
        # Should not crash

    def test_uses_filename_stem_when_id_missing(self, client, tasks_dir):
        """Falls back to filename stem when 'id' field is missing."""
        task_id = "20251227T140000.000000-scan"
        # Task data without 'id' field
        task_data = {"type": "scan"}
        task_file = tasks_dir / "in_progress" / f"{task_id}.json"
        with open(task_file, "w") as f:
            json.dump(task_data, f)

        response = client.get("/api/tasks/active-html")
        assert response.status_code == 200
        # Should use filename stem as task_id
        assert "140000.000000-scan" in response.text

    def test_defaults_to_task_type_when_missing(self, client, tasks_dir):
        """Defaults to 'Task' when type field is missing."""
        task_id = "20251227T150000.000000-unknown"
        # Task data without 'type' field
        task_data = {"id": task_id}
        task_file = tasks_dir / "in_progress" / f"{task_id}.json"
        with open(task_file, "w") as f:
            json.dump(task_data, f)

        response = client.get("/api/tasks/active-html")
        assert response.status_code == 200
        # Should default to "Task" (title case of "task")
        assert "Task" in response.text

    def test_escapes_html_in_task_data(self, client, tasks_dir):
        """HTML special characters in task data are escaped to prevent XSS."""
        # Create a task with HTML/XSS in type and id fields
        task_id = "<script>alert('xss')</script>"
        task_data = {
            "id": task_id,
            "type": "<img src=x onerror=alert('xss')>"
        }
        # Use a safe filename for the task file
        task_file = tasks_dir / "in_progress" / "malicious-task.json"
        with open(task_file, "w") as f:
            json.dump(task_data, f)

        response = client.get("/api/tasks/active-html")
        assert response.status_code == 200
        html_response = response.text

        # Raw HTML tags should NOT appear (angle brackets must be escaped)
        # This prevents XSS because browsers won't interpret escaped tags as HTML
        assert "<script>" not in html_response
        assert "</script>" not in html_response
        assert "<img " not in html_response

        # Escaped angle brackets SHOULD appear
        assert "&lt;script&gt;" in html_response
        assert "&lt;/script&gt;" in html_response
        # The type gets .title() applied, so <img becomes <Img
        assert "&lt;img " in html_response.lower()


class TestFailedTasksAPI:
    """Tests for failed task endpoints."""

    @pytest.fixture
    def failed_tasks_dir(self, tasks_dir):
        """Create the failed tasks directory."""
        failed_dir = tasks_dir / "failed"
        failed_dir.mkdir(parents=True, exist_ok=True)
        return failed_dir

    def test_get_failed_tasks_returns_empty_list(self, client, failed_tasks_dir):
        """GET /api/tasks/failed returns empty list when no failed tasks."""
        response = client.get("/api/tasks/failed")
        assert response.status_code == 200
        data = response.json()
        assert data["tasks"] == []

    def test_get_failed_tasks_returns_tasks(self, client, failed_tasks_dir):
        """GET /api/tasks/failed returns tasks from failed/ directory."""
        # Create a failed task
        task_data = {
            "task_id": "20251226T140000.000000-rip",
            "type": "rip",
            "status": "failed",
            "error": {
                "code": "RIP_ERROR",
                "message": "Disc read error",
                "detail": "Unable to read sector 12345"
            }
        }
        with open(failed_tasks_dir / "20251226T140000.000000-rip.json", "w") as f:
            json.dump(task_data, f)

        response = client.get("/api/tasks/failed")
        assert response.status_code == 200
        data = response.json()
        assert len(data["tasks"]) == 1
        task = data["tasks"][0]
        assert task["id"] == "20251226T140000.000000-rip"
        assert task["type"] == "rip"
        assert task["status"] == "failed"
        assert task["error"]["message"] == "Disc read error"

    def test_get_failed_tasks_returns_multiple_tasks(self, client, failed_tasks_dir):
        """GET /api/tasks/failed returns all tasks from failed/ directory."""
        # Create multiple failed tasks
        for i in range(3):
            task_data = {
                "task_id": f"20251226T{140000 + i:06d}.000000-rip",
                "type": "rip",
                "status": "failed",
                "error": {"message": f"Error {i}"}
            }
            with open(failed_tasks_dir / f"20251226T{140000 + i:06d}.000000-rip.json", "w") as f:
                json.dump(task_data, f)

        response = client.get("/api/tasks/failed")
        assert response.status_code == 200
        data = response.json()
        assert len(data["tasks"]) == 3

    def test_delete_failed_task_removes_file(self, client, failed_tasks_dir):
        """DELETE /api/tasks/failed/{task_id} removes task from failed/ directory."""
        task_id = "20251226T150000.000000-rip"
        task_file = failed_tasks_dir / f"{task_id}.json"
        task_data = {
            "task_id": task_id,
            "type": "rip",
            "status": "failed",
            "error": {"message": "Some error"}
        }
        with open(task_file, "w") as f:
            json.dump(task_data, f)

        assert task_file.exists()

        response = client.delete(f"/api/tasks/failed/{task_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "dismissed"
        assert not task_file.exists()

    def test_delete_failed_task_not_found(self, client, failed_tasks_dir):
        """DELETE /api/tasks/failed/{task_id} returns 404 for non-existent task."""
        response = client.delete("/api/tasks/failed/nonexistent-task")
        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    def test_delete_failed_task_validates_task_id_with_dotdot(self, client, failed_tasks_dir):
        """DELETE /api/tasks/failed/{task_id} rejects task IDs containing '..'."""
        # Task ID containing ".." should be rejected
        response = client.delete("/api/tasks/failed/task..id")
        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()

    def test_delete_failed_task_validates_task_id_with_backslash(self, client, failed_tasks_dir):
        """DELETE /api/tasks/failed/{task_id} rejects task IDs containing backslashes."""
        import urllib.parse

        # Task ID containing backslash should be rejected (URL-encode to pass routing)
        malicious_id = "task\\id"
        encoded_id = urllib.parse.quote(malicious_id, safe='')
        response = client.delete(f"/api/tasks/failed/{encoded_id}")
        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()

    def test_delete_failed_task_with_url_encoded_id(self, client, failed_tasks_dir):
        """DELETE /api/tasks/failed/{task_id} works with URL-encoded task IDs."""
        # Task IDs can have dots which might need encoding
        task_id = "20251226T160000.000000-rip"
        task_file = failed_tasks_dir / f"{task_id}.json"
        task_data = {
            "task_id": task_id,
            "type": "rip",
            "status": "failed",
            "error": {"message": "Error"}
        }
        with open(task_file, "w") as f:
            json.dump(task_data, f)

        # URL-encoded version of task_id
        import urllib.parse
        encoded_id = urllib.parse.quote(task_id, safe='')

        response = client.delete(f"/api/tasks/failed/{encoded_id}")
        assert response.status_code == 200
        assert not task_file.exists()

    def test_get_failed_tasks_handles_malformed_json(self, client, failed_tasks_dir):
        """GET /api/tasks/failed gracefully handles malformed JSON files."""
        # Create a valid task
        valid_task = {
            "task_id": "20251226T170000.000000-rip",
            "type": "rip",
            "status": "failed",
            "error": {"message": "Valid error"}
        }
        with open(failed_tasks_dir / "20251226T170000.000000-rip.json", "w") as f:
            json.dump(valid_task, f)

        # Create a malformed JSON file
        with open(failed_tasks_dir / "malformed-task.json", "w") as f:
            f.write("{invalid json content")

        # Should still return the valid task and not crash
        response = client.get("/api/tasks/failed")
        assert response.status_code == 200
        data = response.json()
        # Should have only the valid task, malformed one is skipped
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["id"] == "20251226T170000.000000-rip"

    def test_get_failed_tasks_includes_timing_fields(self, client, failed_tasks_dir):
        """GET /api/tasks/failed includes started_at and completed_at fields."""
        task_data = {
            "task_id": "20251226T180000.000000-rip",
            "type": "rip",
            "status": "failed",
            "started_at": "2025-12-26T18:00:00.000000",
            "completed_at": "2025-12-26T18:00:05.000000",
            "error": {"message": "Some error"}
        }
        with open(failed_tasks_dir / "20251226T180000.000000-rip.json", "w") as f:
            json.dump(task_data, f)

        response = client.get("/api/tasks/failed")
        assert response.status_code == 200
        data = response.json()
        assert len(data["tasks"]) == 1
        task = data["tasks"][0]
        assert task["started_at"] == "2025-12-26T18:00:00.000000"
        assert task["completed_at"] == "2025-12-26T18:00:05.000000"


class TestPauseStatusAPI:
    """Tests for pause status endpoints."""

    def test_pause_status_returns_false_when_no_marker(self, client, tasks_dir):
        """GET /api/tasks/pause-status returns paused=false when no PAUSED file exists."""
        response = client.get("/api/tasks/pause-status")
        assert response.status_code == 200
        data = response.json()
        assert data["paused"] is False

    def test_pause_status_returns_true_when_marker_exists(self, client, tasks_dir):
        """GET /api/tasks/pause-status returns paused=true when PAUSED file exists."""
        # Create the PAUSED marker file
        paused_file = tasks_dir / "PAUSED"
        paused_file.write_text("2025-12-27T12:00:00.000000")

        response = client.get("/api/tasks/pause-status")
        assert response.status_code == 200
        data = response.json()
        assert data["paused"] is True

    def test_pause_creates_marker_file(self, client, tasks_dir):
        """POST /api/tasks/pause creates PAUSED marker file with timestamp."""
        response = client.post("/api/tasks/pause")
        assert response.status_code == 200

        paused_file = tasks_dir / "PAUSED"
        assert paused_file.exists()

        # Check that the file contains a timestamp
        content = paused_file.read_text()
        # Should be an ISO format timestamp
        assert "T" in content
        assert len(content) > 10  # ISO timestamps are at least 10 chars

    def test_pause_returns_paused_true(self, client, tasks_dir):
        """POST /api/tasks/pause returns paused=true in response."""
        response = client.post("/api/tasks/pause")
        assert response.status_code == 200
        data = response.json()
        assert data["paused"] is True

    def test_resume_removes_marker_file(self, client, tasks_dir):
        """POST /api/tasks/resume removes PAUSED marker file."""
        # Create the PAUSED marker file first
        paused_file = tasks_dir / "PAUSED"
        paused_file.write_text("2025-12-27T12:00:00.000000")
        assert paused_file.exists()

        response = client.post("/api/tasks/resume")
        assert response.status_code == 200

        assert not paused_file.exists()

    def test_resume_returns_paused_false(self, client, tasks_dir):
        """POST /api/tasks/resume returns paused=false in response."""
        # Create the PAUSED marker file first
        paused_file = tasks_dir / "PAUSED"
        paused_file.write_text("2025-12-27T12:00:00.000000")

        response = client.post("/api/tasks/resume")
        assert response.status_code == 200
        data = response.json()
        assert data["paused"] is False

    def test_pause_is_idempotent(self, client, tasks_dir):
        """POST /api/tasks/pause is idempotent - calling multiple times succeeds."""
        # Call pause twice
        response1 = client.post("/api/tasks/pause")
        assert response1.status_code == 200
        assert response1.json()["paused"] is True

        response2 = client.post("/api/tasks/pause")
        assert response2.status_code == 200
        assert response2.json()["paused"] is True

        # PAUSED file should still exist
        paused_file = tasks_dir / "PAUSED"
        assert paused_file.exists()

    def test_resume_is_idempotent(self, client, tasks_dir):
        """POST /api/tasks/resume is idempotent - calling when not paused succeeds."""
        # Call resume without any PAUSED file
        response1 = client.post("/api/tasks/resume")
        assert response1.status_code == 200
        assert response1.json()["paused"] is False

        # Call again
        response2 = client.post("/api/tasks/resume")
        assert response2.status_code == 200
        assert response2.json()["paused"] is False
