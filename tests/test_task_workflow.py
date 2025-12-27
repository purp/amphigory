"""Integration tests for the rip->transcode task workflow."""

import pytest
import json
from pathlib import Path
from unittest.mock import patch


class TestTaskWorkflow:
    """Integration tests for the rip->transcode task workflow."""

    @pytest.fixture
    def tasks_dir(self, tmp_path, monkeypatch):
        """Create and set up a tasks directory."""
        monkeypatch.setenv("AMPHIGORY_DATA", str(tmp_path))
        tasks_dir = tmp_path / "tasks"
        (tasks_dir / "queued").mkdir(parents=True)
        (tasks_dir / "in_progress").mkdir(parents=True)
        (tasks_dir / "complete").mkdir(parents=True)
        (tasks_dir / "failed").mkdir(parents=True)
        with open(tasks_dir / "tasks.json", "w") as f:
            json.dump([], f)
        return tasks_dir

    @pytest.fixture
    def client(self, tasks_dir):
        """Create test client with mocked tasks directory."""
        from amphigory.main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            yield client

    def test_process_creates_rip_and_transcode_tasks(self, client, tasks_dir):
        """Test that POST /api/tasks/process creates both rip and transcode tasks."""
        response = client.post("/api/tasks/process", json={
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

    def test_process_creates_task_files_in_queued(self, client, tasks_dir):
        """Test that tasks are written to the queued directory."""
        client.post("/api/tasks/process", json={
            "tracks": [{
                "track_number": 1,
                "output_filename": "Test Movie.mkv",
                "preset": "H.265 MKV 1080p",
            }],
            "disc_fingerprint": "fp-123",
        })

        queued_files = list((tasks_dir / "queued").glob("*.json"))
        assert len(queued_files) == 2

    def test_process_creates_tasks_json_ordering(self, client, tasks_dir):
        """Test that tasks.json contains correct ordering (rip before transcode)."""
        client.post("/api/tasks/process", json={
            "tracks": [{
                "track_number": 1,
                "output_filename": "Movie.mkv",
                "preset": "H.265 MKV 1080p",
            }],
            "disc_fingerprint": "fp-123",
        })

        with open(tasks_dir / "tasks.json") as f:
            task_order = json.load(f)

        assert len(task_order) == 2
        assert task_order[0].endswith("-rip")
        assert task_order[1].endswith("-transcode")

    def test_transcode_input_matches_rip_output(self, client, tasks_dir):
        """Test that transcode task's input matches rip task's output (dependency)."""
        response = client.post("/api/tasks/process", json={
            "tracks": [{
                "track_number": 1,
                "output_filename": "Movie.mkv",
                "preset": "H.265 MKV 1080p",
            }],
            "disc_fingerprint": "fp-123",
        })

        data = response.json()
        rip_task = next(t for t in data["tasks"] if t["type"] == "rip")
        transcode_task = next(t for t in data["tasks"] if t["type"] == "transcode")

        assert transcode_task["input"] == rip_task["output"]

    def test_multiple_tracks_create_correct_task_pairs(self, client, tasks_dir):
        """Test that multiple tracks create paired rip+transcode tasks."""
        response = client.post("/api/tasks/process", json={
            "tracks": [
                {"track_number": 1, "output_filename": "Movie.mkv", "preset": "H.265 MKV 1080p"},
                {"track_number": 2, "output_filename": "Extras.mkv", "preset": "H.265 MKV 1080p"},
            ],
            "disc_fingerprint": "fp-123",
        })

        data = response.json()
        assert len(data["tasks"]) == 4  # 2 rips + 2 transcodes

        # Verify each track has a matching pair
        rip_tasks = [t for t in data["tasks"] if t["type"] == "rip"]
        transcode_tasks = [t for t in data["tasks"] if t["type"] == "transcode"]
        assert len(rip_tasks) == 2
        assert len(transcode_tasks) == 2
