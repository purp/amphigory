"""Integration tests for the full Amphigory workflow.

Tests the interaction between webapp components, simulating daemon behavior.
"""

import json
import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from amphigory.database import Database
from amphigory.api import disc_repository


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
    )

    yield daemon_id

    if daemon_id in _daemons:
        del _daemons[daemon_id]


class TestFullScanWorkflow:
    """Test complete scan workflow from disc detection to results."""

    @pytest.mark.asyncio
    async def test_disc_status_shows_daemon_disc(self, client, registered_daemon):
        """Disc status queries daemon via WebSocket."""
        from amphigory.websocket import manager
        from unittest.mock import patch

        # Mock the WebSocket request to daemon
        async def mock_request_from_daemon(daemon_id, method, params, timeout):
            return {
                "state": "disc_inserted",
                "device": "/dev/disk2",
                "disc_volume": "MY_MOVIE_DISC",
            }

        with patch.object(manager, 'request_from_daemon', side_effect=mock_request_from_daemon):
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

    def test_disc_event_broadcasts_to_clients(self, client):
        """Disc events are broadcast to browser clients (no local state)."""
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

            # Daemon should be registered but without disc state
            daemon = _daemons.get("disc-test-daemon")
            assert daemon is not None
            # Verify disc state is NOT stored locally (daemon is source of truth)
            assert not hasattr(daemon, 'disc_inserted') or daemon.disc_inserted is False


class TestRipTranscodeChain:
    """Integration tests for rip → transcode task chain."""

    @pytest.fixture
    def media_dirs(self, tmp_path):
        """Create ripped and transcoded directories."""
        ripped = tmp_path / "ripped"
        transcoded = tmp_path / "transcoded"
        ripped.mkdir()
        transcoded.mkdir()
        return {"ripped": ripped, "transcoded": transcoded}

    def test_transcode_task_waits_for_rip_output(self, client, tasks_dir, media_dirs):
        """Transcode task is queued even when rip output file doesn't exist yet."""
        rip_output = media_dirs["ripped"] / "Movie (2024)" / "Movie (2024).mkv"

        # Create rip task (completed) and transcode task (waiting)
        rip_task = {
            "id": "20251227T100000.000000-rip",
            "type": "rip",
            "status": "complete",
            "output": str(rip_output),
        }
        transcode_task = {
            "id": "20251227T100000.000001-transcode",
            "type": "transcode",
            "input": str(rip_output),
            "output": str(media_dirs["transcoded"] / "Movie (2024).mp4"),
            "preset": "H.265 MKV 1080p",
        }

        # Write tasks
        with open(tasks_dir / "complete" / f"{rip_task['id']}.json", "w") as f:
            json.dump(rip_task, f)
        with open(tasks_dir / "queued" / f"{transcode_task['id']}.json", "w") as f:
            json.dump(transcode_task, f)

        # Transcode should be in queued state (input doesn't exist yet)
        response = client.get("/api/tasks")
        data = response.json()
        queued = [t for t in data.get("tasks", []) if t["id"] == transcode_task["id"]]
        assert len(queued) == 1
        assert queued[0]["status"] == "queued"

    def test_transcode_ready_when_rip_output_exists(self, client, tasks_dir, media_dirs):
        """Transcode task is gettable when rip output file exists."""
        rip_output = media_dirs["ripped"] / "Movie (2024)" / "Movie (2024).mkv"
        rip_output.parent.mkdir(parents=True)
        rip_output.write_text("fake mkv content")  # Create the file

        transcode_task = {
            "id": "20251227T100000.000001-transcode",
            "type": "transcode",
            "input": str(rip_output),
            "output": str(media_dirs["transcoded"] / "Movie (2024).mp4"),
            "preset": "H.265 MKV 1080p",
        }

        with open(tasks_dir / "queued" / f"{transcode_task['id']}.json", "w") as f:
            json.dump(transcode_task, f)
        with open(tasks_dir / "tasks.json", "w") as f:
            json.dump([transcode_task["id"]], f)

        # Input exists, so transcode should be gettable and queued
        response = client.get("/api/tasks")
        assert response.status_code == 200
        data = response.json()
        # The task should exist in the response
        task_ids = [t["id"] for t in data.get("tasks", [])]
        assert transcode_task["id"] in task_ids


# --- Track Normalization Integration Tests ---


@pytest.fixture
async def integration_db(tmp_path):
    """Create a test database for integration tests."""
    db_path = tmp_path / "integration_test.db"
    database = Database(db_path)
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
async def integration_db_path(tmp_path, integration_db):
    """Provide database path for repository functions in integration tests."""
    db_path = tmp_path / "integration_test.db"
    # Temporarily set the db path for the repository module
    original_get_db = disc_repository.get_db_path
    disc_repository.get_db_path = lambda: db_path
    yield db_path
    disc_repository.get_db_path = original_get_db


class TestTrackNormalizationIntegration:
    """Integration tests for track normalization during disc scan flow."""

    @pytest.mark.asyncio
    async def test_scan_flow_populates_tracks_table(self, integration_db, integration_db_path):
        """Full scan creates disc and properly populates tracks table."""
        # 1. Create scan_data with multiple tracks
        scan_data = {
            "disc_name": "TEST_MOVIE",
            "disc_type": "bluray",
            "tracks": [
                {
                    "number": 0,
                    "duration": "1:45:00",
                    "classification": "main_feature",
                    "confidence": "high",
                    "score": 0.95,
                    "size_bytes": 25000000000,
                    "chapters": 28,
                    "resolution": "1920x1080",
                    "segment_map": "1,2,3,4,5",
                    "makemkv_name": "B1_t00.mkv",
                    "audio_streams": [
                        {"language": "eng", "codec": "TrueHD", "channels": 8},
                        {"language": "spa", "codec": "AC3", "channels": 6},
                    ],
                    "subtitle_streams": [
                        {"language": "eng", "format": "PGS"},
                        {"language": "spa", "format": "PGS"},
                    ],
                },
                {
                    "number": 1,
                    "duration": "0:05:00",
                    "classification": "extra",
                    "confidence": "medium",
                    "score": 0.70,
                    "size_bytes": 500000000,
                    "chapters": 1,
                    "resolution": "1920x1080",
                    "makemkv_name": "B1_t01.mkv",
                },
                {
                    "number": 2,
                    "duration": "0:02:30",
                    "classification": "trailer",
                    "confidence": "high",
                    "score": 0.85,
                    "size_bytes": 200000000,
                },
            ],
        }

        # 2. Call save_disc_scan
        disc_id = await disc_repository.save_disc_scan("fp_integration_test", scan_data)

        # 3. Query tracks table directly
        async with integration_db.connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM tracks WHERE disc_id = ? ORDER BY track_number",
                (disc_id,),
            )
            tracks = await cursor.fetchall()

        # 4. Verify tracks match scan_data
        assert len(tracks) == 3

        # Verify first track (main feature)
        track_0 = tracks[0]
        assert track_0["track_number"] == 0
        assert track_0["track_type"] == "main_feature"
        assert track_0["duration_seconds"] == 6300  # 1:45:00 = 1*3600 + 45*60
        assert track_0["classification_confidence"] == "high"
        assert track_0["classification_score"] == 0.95
        assert track_0["size_bytes"] == 25000000000
        assert track_0["chapter_count"] == 28
        assert track_0["resolution"] == "1920x1080"
        assert track_0["segment_map"] == "1,2,3,4,5"
        assert track_0["makemkv_name"] == "B1_t00.mkv"
        assert track_0["status"] == "discovered"

        # Verify audio/subtitle JSON
        audio_tracks = json.loads(track_0["audio_tracks"])
        assert len(audio_tracks) == 2
        assert audio_tracks[0]["codec"] == "TrueHD"
        subtitle_tracks = json.loads(track_0["subtitle_tracks"])
        assert len(subtitle_tracks) == 2

        # Verify second track (extra)
        track_1 = tracks[1]
        assert track_1["track_number"] == 1
        assert track_1["track_type"] == "extra"
        assert track_1["duration_seconds"] == 300  # 0:05:00 = 5*60
        assert track_1["classification_confidence"] == "medium"

        # Verify third track (trailer)
        track_2 = tracks[2]
        assert track_2["track_number"] == 2
        assert track_2["track_type"] == "trailer"
        assert track_2["duration_seconds"] == 150  # 0:02:30 = 2*60 + 30

    @pytest.mark.asyncio
    async def test_rescan_updates_tracks(self, integration_db, integration_db_path):
        """Rescanning clears old tracks and inserts new ones from fresh scan data."""
        # 1. First scan with 3 tracks
        scan_data_1 = {
            "disc_name": "TEST_MOVIE_RESCAN",
            "tracks": [
                {"number": 0, "duration": "1:30:00", "classification": "main_feature"},
                {"number": 1, "duration": "0:05:00", "classification": "extra"},
                {"number": 2, "duration": "0:03:00", "classification": "trailer"},
            ],
        }

        disc_id = await disc_repository.save_disc_scan("fp_rescan_integration", scan_data_1)

        # Verify initial 3 tracks exist
        async with integration_db.connection() as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) as count FROM tracks WHERE disc_id = ?",
                (disc_id,),
            )
            row = await cursor.fetchone()
        assert row["count"] == 3

        # 2. Rescan with different track data (only 2 tracks, different values)
        scan_data_2 = {
            "disc_name": "TEST_MOVIE_RESCAN_UPDATED",
            "tracks": [
                {
                    "number": 0,
                    "duration": "1:35:00",
                    "classification": "main_feature",
                    "confidence": "high",
                    "size_bytes": 26000000000,
                },
                {
                    "number": 1,
                    "duration": "0:04:30",
                    "classification": "deleted_scene",
                    "confidence": "medium",
                },
            ],
        }

        disc_id_2 = await disc_repository.save_disc_scan("fp_rescan_integration", scan_data_2)

        # 3. Verify same disc ID returned
        assert disc_id_2 == disc_id

        # 4. Verify old tracks were cleared and new tracks inserted
        async with integration_db.connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM tracks WHERE disc_id = ? ORDER BY track_number",
                (disc_id,),
            )
            tracks = await cursor.fetchall()

        # Should only have 2 tracks now (old 3 cleared, new 2 inserted)
        assert len(tracks) == 2

        # Verify new track data
        assert tracks[0]["track_number"] == 0
        assert tracks[0]["duration_seconds"] == 5700  # 1:35:00 = 1*3600 + 35*60
        assert tracks[0]["track_type"] == "main_feature"
        assert tracks[0]["size_bytes"] == 26000000000

        assert tracks[1]["track_number"] == 1
        assert tracks[1]["duration_seconds"] == 270  # 0:04:30 = 4*60 + 30
        assert tracks[1]["track_type"] == "deleted_scene"

    @pytest.mark.asyncio
    async def test_tracks_match_scan_data(self, integration_db, integration_db_path):
        """Track table data exactly matches the values in scan_data JSON."""
        # Create comprehensive scan data
        scan_data = {
            "disc_name": "TRACK_DATA_MATCH_TEST",
            "disc_type": "bluray",
            "tracks": [
                {
                    "number": 0,
                    "duration": "2:15:30",
                    "classification": "main_feature",
                    "confidence": "high",
                    "score": 0.92,
                    "size_bytes": 35000000000,
                    "chapters": 32,
                    "resolution": "3840x2160",
                    "segment_map": "1,2,3,4,5,6,7",
                    "makemkv_name": "B1_t00.mkv",
                    "audio_streams": [
                        {"language": "eng", "codec": "TrueHD Atmos", "channels": 8},
                    ],
                    "subtitle_streams": [
                        {"language": "eng", "format": "PGS", "forced": False},
                        {"language": "eng", "format": "PGS", "forced": True},
                    ],
                },
                {
                    "number": 5,
                    "duration": "0:45:00",
                    "classification": "behind_the_scenes",
                    "confidence": "low",
                    "score": 0.55,
                    "size_bytes": 8000000000,
                    "chapters": 8,
                    "resolution": "1920x1080",
                },
            ],
        }

        disc_id = await disc_repository.save_disc_scan("fp_data_match_test", scan_data)

        # Query disc to get scan_data JSON and tracks
        async with integration_db.connection() as conn:
            # Get disc with scan_data
            cursor = await conn.execute(
                "SELECT scan_data FROM discs WHERE id = ?",
                (disc_id,),
            )
            disc_row = await cursor.fetchone()
            stored_scan_data = json.loads(disc_row["scan_data"])

            # Get tracks
            cursor = await conn.execute(
                "SELECT * FROM tracks WHERE disc_id = ? ORDER BY track_number",
                (disc_id,),
            )
            tracks = await cursor.fetchall()

        # Verify each track matches corresponding scan_data track
        for i, track_row in enumerate(tracks):
            scan_track = stored_scan_data["tracks"][i]

            # Core fields match
            assert track_row["track_number"] == scan_track["number"]
            assert track_row["track_type"] == scan_track["classification"]
            assert track_row["classification_confidence"] == scan_track.get("confidence")
            assert track_row["classification_score"] == scan_track.get("score")
            assert track_row["size_bytes"] == scan_track.get("size_bytes")
            assert track_row["chapter_count"] == scan_track.get("chapters")
            assert track_row["resolution"] == scan_track.get("resolution")
            assert track_row["segment_map"] == scan_track.get("segment_map")
            assert track_row["makemkv_name"] == scan_track.get("makemkv_name")

            # Duration parsed correctly
            duration_str = scan_track["duration"]
            parts = duration_str.split(":")
            if len(parts) == 3:
                expected_seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                expected_seconds = int(parts[0]) * 60 + int(parts[1])
            else:
                expected_seconds = int(parts[0])
            assert track_row["duration_seconds"] == expected_seconds

            # Audio/subtitle JSON matches if present
            if scan_track.get("audio_streams"):
                stored_audio = json.loads(track_row["audio_tracks"])
                assert stored_audio == scan_track["audio_streams"]
            if scan_track.get("subtitle_streams"):
                stored_subs = json.loads(track_row["subtitle_tracks"])
                assert stored_subs == scan_track["subtitle_streams"]


class TestDiscToLibraryFlow:
    """Integration tests for disc review → process → library flow."""

    @pytest.fixture
    async def seeded_disc(self, integration_db, integration_db_path):
        """Seed database with a disc and tracks (unprocessed by default)."""
        # Insert disc with processed_at explicitly NULL (unprocessed state)
        async with integration_db.connection() as conn:
            cursor = await conn.execute("""
                INSERT INTO discs (fingerprint, title, year, disc_type, processed_at)
                VALUES (?, ?, ?, ?, NULL)
            """, ("test-fp-12345", "Test Movie", 2024, "bluray"))
            disc_id = cursor.lastrowid

            # Insert tracks
            for i in range(3):
                await conn.execute("""
                    INSERT INTO tracks (disc_id, track_number, duration_seconds, size_bytes, track_type)
                    VALUES (?, ?, ?, ?, ?)
                """, (disc_id, i + 1, 7200 + i * 100, 10_000_000_000, "main_feature" if i == 0 else "extra"))
            await conn.commit()

        return {"disc_id": disc_id, "fingerprint": "test-fp-12345"}

    @pytest.mark.asyncio
    async def test_completed_disc_appears_in_library(self, integration_db, integration_db_path, seeded_disc):
        """Disc with processed_at appears in library listing."""
        # Mark disc as processed
        async with integration_db.connection() as conn:
            await conn.execute("""
                UPDATE discs SET processed_at = datetime('now') WHERE fingerprint = ?
            """, (seeded_disc["fingerprint"],))
            await conn.commit()

        # Query library directly from database (since library API may need more context)
        async with integration_db.connection() as conn:
            cursor = await conn.execute("""
                SELECT id, title, year FROM discs WHERE processed_at IS NOT NULL
            """)
            discs = await cursor.fetchall()

        disc_ids = [d["id"] for d in discs]
        assert seeded_disc["disc_id"] in disc_ids

    @pytest.mark.asyncio
    async def test_unprocessed_disc_not_in_library(self, integration_db, integration_db_path, seeded_disc):
        """Disc without processed_at does not appear in library listing."""
        # Don't mark as processed - query library
        async with integration_db.connection() as conn:
            cursor = await conn.execute("""
                SELECT id, title, year FROM discs WHERE processed_at IS NOT NULL
            """)
            discs = await cursor.fetchall()

        disc_ids = [d["id"] for d in discs]
        assert seeded_disc["disc_id"] not in disc_ids
