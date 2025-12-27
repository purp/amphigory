"""Tests for task queue management - TDD: tests written first."""

import json
from datetime import datetime
from pathlib import Path

import pytest


class TestTaskQueueDirectories:
    def test_ensure_directories_creates_structure(self, tmp_path):
        """Create queue directory structure if it doesn't exist."""
        from amphigory_daemon.tasks import TaskQueue

        queue = TaskQueue(tmp_path)
        queue.ensure_directories()

        assert (tmp_path / "queued").is_dir()
        assert (tmp_path / "in_progress").is_dir()
        assert (tmp_path / "complete").is_dir()

    def test_ensure_directories_idempotent(self, tmp_path):
        """Calling ensure_directories multiple times is safe."""
        from amphigory_daemon.tasks import TaskQueue

        queue = TaskQueue(tmp_path)
        queue.ensure_directories()
        queue.ensure_directories()  # Should not raise

        assert (tmp_path / "queued").is_dir()


class TestGetTaskOrder:
    def test_returns_empty_list_when_no_tasks_json(self, tmp_path):
        """Return empty list when tasks.json doesn't exist."""
        from amphigory_daemon.tasks import TaskQueue

        queue = TaskQueue(tmp_path)
        queue.ensure_directories()

        order = queue.get_task_order()

        assert order == []

    def test_returns_ordered_task_ids(self, tmp_path):
        """Return list of task IDs from tasks.json in order."""
        from amphigory_daemon.tasks import TaskQueue

        queue = TaskQueue(tmp_path)
        queue.ensure_directories()

        # Create tasks.json with ordered IDs
        tasks_json = tmp_path / "tasks.json"
        tasks_json.write_text(json.dumps([
            "20251221-143052-001",
            "20251221-143052-002",
            "20251221-143052-003",
        ]))

        order = queue.get_task_order()

        assert order == [
            "20251221-143052-001",
            "20251221-143052-002",
            "20251221-143052-003",
        ]


class TestGetNextTask:
    def test_returns_none_when_queue_empty(self, tmp_path):
        """Return None when no tasks in queue."""
        from amphigory_daemon.tasks import TaskQueue

        queue = TaskQueue(tmp_path)
        queue.ensure_directories()

        task = queue.get_next_task()

        assert task is None

    def test_returns_none_when_no_tasks_json(self, tmp_path):
        """Return None when tasks.json doesn't exist."""
        from amphigory_daemon.tasks import TaskQueue

        queue = TaskQueue(tmp_path)
        queue.ensure_directories()

        # Put a task file but no tasks.json
        task_file = tmp_path / "queued" / "20251221-143052-001.json"
        task_file.write_text(json.dumps({
            "id": "20251221-143052-001",
            "type": "scan",
            "created_at": "2025-12-21T14:30:52Z",
        }))

        task = queue.get_next_task()

        assert task is None

    def test_picks_first_task_with_file(self, tmp_path):
        """Pick first task ID in tasks.json that has a queued file."""
        from amphigory_daemon.tasks import TaskQueue
        from amphigory_daemon.models import ScanTask, TaskType

        queue = TaskQueue(tmp_path)
        queue.ensure_directories()

        # tasks.json with 3 IDs (using new format with task type suffix)
        tasks_json = tmp_path / "tasks.json"
        tasks_json.write_text(json.dumps([
            "20251221T143052.000001-scan",
            "20251221T143052.000002-scan",
            "20251221T143052.000003-scan",
        ]))

        # Only create file for second task
        task_file = tmp_path / "queued" / "20251221T143052.000002-scan.json"
        task_file.write_text(json.dumps({
            "id": "20251221T143052.000002-scan",
            "type": "scan",
            "created_at": "2025-12-21T14:30:52Z",
        }))

        task = queue.get_next_task()

        assert isinstance(task, ScanTask)
        assert task.id == "20251221T143052.000002-scan"

    def test_moves_task_to_in_progress(self, tmp_path):
        """Move task file from queued/ to in_progress/."""
        from amphigory_daemon.tasks import TaskQueue

        queue = TaskQueue(tmp_path)
        queue.ensure_directories()

        tasks_json = tmp_path / "tasks.json"
        tasks_json.write_text(json.dumps(["20251221T143052.000001-scan"]))

        queued_file = tmp_path / "queued" / "20251221T143052.000001-scan.json"
        queued_file.write_text(json.dumps({
            "id": "20251221T143052.000001-scan",
            "type": "scan",
            "created_at": "2025-12-21T14:30:52Z",
        }))

        queue.get_next_task()

        assert not queued_file.exists()
        assert (tmp_path / "in_progress" / "20251221T143052.000001-scan.json").exists()

    def test_parses_rip_task(self, tmp_path):
        """Parse rip task with track and output info."""
        from amphigory_daemon.tasks import TaskQueue
        from amphigory_daemon.models import RipTask, TaskType

        queue = TaskQueue(tmp_path)
        queue.ensure_directories()

        tasks_json = tmp_path / "tasks.json"
        tasks_json.write_text(json.dumps(["20251221T143052.000001-rip"]))

        task_file = tmp_path / "queued" / "20251221T143052.000001-rip.json"
        task_file.write_text(json.dumps({
            "id": "20251221T143052.000001-rip",
            "type": "rip",
            "created_at": "2025-12-21T14:30:52Z",
            "track": {
                "number": 0,
                "expected_size_bytes": 11397666816,
                "expected_duration": "1:39:56",
            },
            "output": {
                "directory": "/media/ripped/Movie (2004)",
                "filename": "Movie (2004).mkv",
            },
        }))

        task = queue.get_next_task()

        assert isinstance(task, RipTask)
        assert task.track.number == 0
        assert task.output.filename == "Movie (2004).mkv"


class TestCompleteTask:
    def test_writes_response_to_complete(self, tmp_path):
        """Write response JSON to complete/ directory."""
        from amphigory_daemon.tasks import TaskQueue
        from amphigory_daemon.models import (
            TaskResponse, TaskStatus, RipResult, DiscSource, FileDestination
        )

        queue = TaskQueue(tmp_path)
        queue.ensure_directories()

        # Create in_progress file
        in_progress_file = tmp_path / "in_progress" / "20251221-143052-001.json"
        in_progress_file.write_text("{}")

        response = TaskResponse(
            task_id="20251221-143052-001",
            status=TaskStatus.SUCCESS,
            started_at=datetime(2025, 12, 21, 14, 30, 55),
            completed_at=datetime(2025, 12, 21, 14, 45, 23),
            duration_seconds=868,
            source=DiscSource(
                disc_fingerprint="abc123def456",
                track_number=4,
                makemkv_track_name="B1_t04.mkv",
                duration="1:39:56",
                size_bytes=12000000000,
            ),
            result=RipResult(
                destination=FileDestination(
                    directory="/media/ripped/Movie",
                    filename="Movie.mkv",
                    size_bytes=11397666816,
                ),
            ),
        )

        queue.complete_task(response)

        complete_file = tmp_path / "complete" / "20251221-143052-001.json"
        assert complete_file.exists()

        data = json.loads(complete_file.read_text())
        assert data["task_id"] == "20251221-143052-001"
        assert data["status"] == "success"

    def test_deletes_from_in_progress(self, tmp_path):
        """Delete task file from in_progress/ after completion."""
        from amphigory_daemon.tasks import TaskQueue
        from amphigory_daemon.models import (
            TaskResponse, TaskStatus, RipResult, DiscSource, FileDestination
        )

        queue = TaskQueue(tmp_path)
        queue.ensure_directories()

        in_progress_file = tmp_path / "in_progress" / "20251221-143052-001.json"
        in_progress_file.write_text("{}")

        response = TaskResponse(
            task_id="20251221-143052-001",
            status=TaskStatus.SUCCESS,
            started_at=datetime(2025, 12, 21, 14, 30, 55),
            completed_at=datetime(2025, 12, 21, 14, 45, 23),
            duration_seconds=868,
            source=DiscSource(
                disc_fingerprint="abc123def456",
                track_number=4,
                makemkv_track_name="B1_t04.mkv",
                duration="1:39:56",
                size_bytes=12000000000,
            ),
            result=RipResult(
                destination=FileDestination(
                    directory="/media/ripped/Movie",
                    filename="Movie.mkv",
                    size_bytes=11397666816,
                ),
            ),
        )

        queue.complete_task(response)

        assert not in_progress_file.exists()


class TestRecoverCrashedTasks:
    def test_moves_in_progress_back_to_queued(self, tmp_path):
        """Move tasks from in_progress/ back to queued/ on recovery."""
        from amphigory_daemon.tasks import TaskQueue

        queue = TaskQueue(tmp_path)
        queue.ensure_directories()

        # Simulate crashed task in in_progress/
        in_progress_file = tmp_path / "in_progress" / "20251221-143052-001.json"
        in_progress_file.write_text(json.dumps({
            "id": "20251221-143052-001",
            "type": "scan",
            "created_at": "2025-12-21T14:30:52Z",
        }))

        queue.recover_crashed_tasks()

        assert not in_progress_file.exists()
        assert (tmp_path / "queued" / "20251221-143052-001.json").exists()

    def test_recovers_multiple_tasks(self, tmp_path):
        """Recover all crashed tasks."""
        from amphigory_daemon.tasks import TaskQueue

        queue = TaskQueue(tmp_path)
        queue.ensure_directories()

        # Multiple crashed tasks
        for i in range(3):
            task_file = tmp_path / "in_progress" / f"20251221-14305{i}-001.json"
            task_file.write_text(json.dumps({
                "id": f"20251221-14305{i}-001",
                "type": "scan",
                "created_at": "2025-12-21T14:30:52Z",
            }))

        queue.recover_crashed_tasks()

        assert len(list((tmp_path / "in_progress").iterdir())) == 0
        assert len(list((tmp_path / "queued").iterdir())) == 3

    def test_no_op_when_nothing_to_recover(self, tmp_path):
        """Does nothing when in_progress/ is empty."""
        from amphigory_daemon.tasks import TaskQueue

        queue = TaskQueue(tmp_path)
        queue.ensure_directories()

        queue.recover_crashed_tasks()  # Should not raise

        assert len(list((tmp_path / "in_progress").iterdir())) == 0


class TestStorageRecovery:
    """Tests for recovery directory when storage is unavailable."""

    def test_recovery_dir_constant_exists(self):
        """Module has RECOVERY_DIR constant."""
        from amphigory_daemon.tasks import RECOVERY_DIR

        assert RECOVERY_DIR is not None
        assert "amphigory" in str(RECOVERY_DIR).lower()
        assert "recovery" in str(RECOVERY_DIR).lower()

    def test_save_to_recovery_writes_file(self, tmp_path):
        """save_to_recovery writes response to recovery directory."""
        from amphigory_daemon.tasks import TaskQueue, save_to_recovery
        from amphigory_daemon.models import (
            TaskResponse, TaskStatus, RipResult, DiscSource, FileDestination
        )

        recovery_dir = tmp_path / "recovery"
        response = TaskResponse(
            task_id="20251221-143052-001",
            status=TaskStatus.SUCCESS,
            started_at=datetime(2025, 12, 21, 14, 30, 55),
            completed_at=datetime(2025, 12, 21, 14, 45, 23),
            duration_seconds=868,
            source=DiscSource(
                disc_fingerprint="abc123def456",
                track_number=4,
                makemkv_track_name="B1_t04.mkv",
                duration="1:39:56",
                size_bytes=12000000000,
            ),
            result=RipResult(
                destination=FileDestination(
                    directory="/media/ripped/Movie",
                    filename="Movie.mkv",
                    size_bytes=11397666816,
                ),
            ),
        )

        save_to_recovery(response, recovery_dir)

        recovery_file = recovery_dir / "20251221-143052-001.json"
        assert recovery_file.exists()

        data = json.loads(recovery_file.read_text())
        assert data["task_id"] == "20251221-143052-001"

    def test_save_to_recovery_creates_dir(self, tmp_path):
        """save_to_recovery creates recovery directory if needed."""
        from amphigory_daemon.tasks import save_to_recovery
        from amphigory_daemon.models import (
            TaskResponse, TaskStatus, RipResult, DiscSource, FileDestination
        )

        recovery_dir = tmp_path / "nested" / "recovery"
        response = TaskResponse(
            task_id="20251221-143052-001",
            status=TaskStatus.SUCCESS,
            started_at=datetime(2025, 12, 21, 14, 30, 55),
            completed_at=datetime(2025, 12, 21, 14, 45, 23),
            duration_seconds=868,
            source=DiscSource(
                disc_fingerprint="abc123def456",
                track_number=4,
                makemkv_track_name="B1_t04.mkv",
                duration="1:39:56",
                size_bytes=12000000000,
            ),
            result=RipResult(
                destination=FileDestination(
                    directory="/media/ripped/Movie",
                    filename="Movie.mkv",
                    size_bytes=11397666816,
                ),
            ),
        )

        save_to_recovery(response, recovery_dir)

        assert recovery_dir.exists()

    def test_process_recovery_moves_to_complete(self, tmp_path):
        """process_recovery moves files from recovery to complete dir."""
        from amphigory_daemon.tasks import TaskQueue, save_to_recovery, process_recovery
        from amphigory_daemon.models import (
            TaskResponse, TaskStatus, RipResult, DiscSource, FileDestination
        )

        recovery_dir = tmp_path / "recovery"
        queue = TaskQueue(tmp_path / "tasks")
        queue.ensure_directories()

        # Create a recovery file
        response = TaskResponse(
            task_id="20251221-143052-001",
            status=TaskStatus.SUCCESS,
            started_at=datetime(2025, 12, 21, 14, 30, 55),
            completed_at=datetime(2025, 12, 21, 14, 45, 23),
            duration_seconds=868,
            source=DiscSource(
                disc_fingerprint="abc123def456",
                track_number=4,
                makemkv_track_name="B1_t04.mkv",
                duration="1:39:56",
                size_bytes=12000000000,
            ),
            result=RipResult(
                destination=FileDestination(
                    directory="/media/ripped/Movie",
                    filename="Movie.mkv",
                    size_bytes=11397666816,
                ),
            ),
        )
        save_to_recovery(response, recovery_dir)

        # Process recovery
        moved = process_recovery(recovery_dir, queue)

        assert moved == 1
        assert not (recovery_dir / "20251221-143052-001.json").exists()
        assert (queue.complete_dir / "20251221-143052-001.json").exists()

    def test_process_recovery_handles_empty_dir(self, tmp_path):
        """process_recovery handles empty or nonexistent recovery dir."""
        from amphigory_daemon.tasks import TaskQueue, process_recovery

        recovery_dir = tmp_path / "recovery"
        queue = TaskQueue(tmp_path / "tasks")
        queue.ensure_directories()

        # Non-existent recovery dir
        moved = process_recovery(recovery_dir, queue)
        assert moved == 0

        # Empty recovery dir
        recovery_dir.mkdir()
        moved = process_recovery(recovery_dir, queue)
        assert moved == 0

    def test_process_recovery_handles_multiple_files(self, tmp_path):
        """process_recovery moves all files from recovery."""
        from amphigory_daemon.tasks import TaskQueue, save_to_recovery, process_recovery
        from amphigory_daemon.models import (
            TaskResponse, TaskStatus, RipResult, DiscSource, FileDestination
        )

        recovery_dir = tmp_path / "recovery"
        queue = TaskQueue(tmp_path / "tasks")
        queue.ensure_directories()

        # Create multiple recovery files
        for i in range(3):
            response = TaskResponse(
                task_id=f"20251221-14305{i}-001",
                status=TaskStatus.SUCCESS,
                started_at=datetime(2025, 12, 21, 14, 30, 55),
                completed_at=datetime(2025, 12, 21, 14, 45, 23),
                duration_seconds=868,
                source=DiscSource(
                    disc_fingerprint="abc123def456",
                    track_number=i,
                    makemkv_track_name=f"B1_t0{i}.mkv",
                    duration="1:39:56",
                    size_bytes=12000000000,
                ),
                result=RipResult(
                    destination=FileDestination(
                        directory=f"/media/ripped/Movie{i}",
                        filename="Movie.mkv",
                        size_bytes=11397666816,
                    ),
                ),
            )
            save_to_recovery(response, recovery_dir)

        moved = process_recovery(recovery_dir, queue)

        assert moved == 3
        assert len(list(queue.complete_dir.iterdir())) == 3


class TestDaemonTaskFiltering:
    """Tests for daemon filtering to only process scan and rip tasks."""

    def test_daemon_only_claims_scan_and_rip_tasks(self, tmp_path):
        """Test daemon ignores transcode tasks."""
        from amphigory_daemon.tasks import TaskQueue
        import json

        queue = TaskQueue(tmp_path)
        queue.ensure_directories()

        # Add a transcode task to queue
        transcode_id = "20251227T140000.000000-transcode"
        transcode_file = tmp_path / "queued" / f"{transcode_id}.json"
        with open(transcode_file, "w") as f:
            json.dump({
                "id": transcode_id,
                "type": "transcode",
                "created_at": "2025-12-27T14:00:00",
                "input": "/tmp/test.mkv",
                "output": "/tmp/out.mkv",
            }, f)

        # Update tasks.json
        with open(tmp_path / "tasks.json", "w") as f:
            json.dump([transcode_id], f)

        # Daemon should not claim it
        task = queue.get_next_task()
        assert task is None
