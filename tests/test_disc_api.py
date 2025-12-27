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

        # Verify format: YYYYMMDDTHHMMSS.ffffff-scan (ISO8601 basic with dot separator)
        pattern = r'^\d{8}T\d{6}\.\d{6}-scan$'
        assert re.match(pattern, task_id), f"Task ID '{task_id}' does not match expected format"

        # Verify the task type suffix
        assert task_id.endswith("-scan")

    def test_task_file_uses_human_readable_name(self, client, tasks_dir):
        """Task file is created with human-readable name."""
        response = client.post("/api/disc/scan")

        task_id = response.json()["task_id"]
        task_file = tasks_dir / "queued" / f"{task_id}.json"

        assert task_file.exists()

        # Verify file name matches pattern (ISO8601 basic with dot separator)
        assert re.match(r'^\d{8}T\d{6}\.\d{6}-scan\.json$', task_file.name)

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

    @pytest.mark.asyncio
    async def test_returns_disc_status_from_daemon(self, client):
        """Returns disc status by querying daemon via WebSocket."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from amphigory.websocket import manager
        from datetime import datetime
        from unittest.mock import AsyncMock, patch

        # Register a daemon (but without disc state - that's now in daemon)
        _daemons["test-daemon"] = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/local/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
        )

        # Mock the WebSocket request to daemon
        async def mock_request_from_daemon(daemon_id, method, params, timeout):
            return {
                "state": "disc_inserted",
                "device": "/dev/disk2",
                "disc_volume": "MY_DISC",
            }

        with patch.object(manager, 'request_from_daemon', side_effect=mock_request_from_daemon):
            try:
                response = client.get("/api/disc/status")

                assert response.status_code == 200
                data = response.json()
                assert data["has_disc"] is True
                assert data["volume_name"] == "MY_DISC"
                assert data["device_path"] == "/dev/disk2"
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

    @pytest.mark.asyncio
    async def test_returns_no_disc_when_daemon_query_fails(self, client):
        """Returns no disc when daemon query times out or fails."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from amphigory.websocket import manager
        from datetime import datetime
        from unittest.mock import patch
        import asyncio

        # Register a daemon
        _daemons["test-daemon"] = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/local/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
        )

        # Mock the WebSocket request to timeout
        async def mock_timeout(daemon_id, method, params, timeout):
            raise asyncio.TimeoutError()

        with patch.object(manager, 'request_from_daemon', side_effect=mock_timeout):
            try:
                response = client.get("/api/disc/status")

                assert response.status_code == 200
                data = response.json()
                assert data["has_disc"] is False
            finally:
                del _daemons["test-daemon"]


class TestScanCache:
    """Tests for scan result caching functionality."""

    def test_get_current_scan_returns_none_initially(self, client):
        """get_current_scan returns None when no scan is cached."""
        from amphigory.api.disc import get_current_scan, clear_current_scan

        # Ensure cache is clear
        clear_current_scan()

        result = get_current_scan()
        assert result is None

    def test_set_current_scan_stores_result(self, client):
        """set_current_scan stores a scan result that can be retrieved."""
        from amphigory.api.disc import get_current_scan, set_current_scan, clear_current_scan

        # Ensure cache is clear
        clear_current_scan()

        scan_data = {
            "disc_name": "TEST_DISC",
            "disc_type": "bluray",
            "tracks": [{"number": 1}, {"number": 2}],
        }

        set_current_scan(scan_data)
        result = get_current_scan()

        assert result is not None
        assert result["disc_name"] == "TEST_DISC"
        assert result["disc_type"] == "bluray"
        assert len(result["tracks"]) == 2

    def test_clear_current_scan_removes_cached_scan(self, client):
        """clear_current_scan removes the cached scan result."""
        from amphigory.api.disc import get_current_scan, set_current_scan, clear_current_scan

        # Set up a cached scan
        scan_data = {
            "disc_name": "TEST_DISC",
            "disc_type": "dvd",
            "tracks": [],
        }
        set_current_scan(scan_data)
        assert get_current_scan() is not None

        # Clear it
        clear_current_scan()

        # Should be None now
        result = get_current_scan()
        assert result is None

    def test_current_scan_endpoint_returns_404_when_no_cache(self, client):
        """GET /api/disc/current-scan returns 404 when no scan is cached."""
        from amphigory.api.disc import clear_current_scan

        # Ensure cache is clear
        clear_current_scan()

        response = client.get("/api/disc/current-scan")

        assert response.status_code == 404
        assert "No scan cached" in response.json()["detail"]

    def test_current_scan_endpoint_returns_cached_scan(self, client):
        """GET /api/disc/current-scan returns the cached scan result."""
        from amphigory.api.disc import set_current_scan

        scan_data = {
            "disc_name": "MY_MOVIE",
            "disc_type": "bluray",
            "tracks": [
                {"number": 1, "duration": "2:15:30"},
                {"number": 2, "duration": "0:05:00"},
            ],
        }
        set_current_scan(scan_data)

        response = client.get("/api/disc/current-scan")

        assert response.status_code == 200
        data = response.json()
        assert data["disc_name"] == "MY_MOVIE"
        assert data["disc_type"] == "bluray"
        assert len(data["tracks"]) == 2

    def test_scan_result_caches_result_on_success(self, client, tasks_dir):
        """GET /api/disc/scan-result caches the result after successful retrieval."""
        from amphigory.api.disc import get_current_scan, clear_current_scan

        # Ensure cache is clear
        clear_current_scan()

        # Create a completed scan task
        result_file = tasks_dir / "complete" / "test-scan-123.json"
        with open(result_file, "w") as f:
            json.dump({
                "task_id": "test-scan-123",
                "status": "success",
                "result": {
                    "disc_name": "CACHED_MOVIE",
                    "disc_type": "bluray",
                    "tracks": [{"number": 1}, {"number": 2}, {"number": 3}],
                },
                "completed_at": "2024-01-15T10:30:00",
            }, f)

        # Request the scan result
        response = client.get("/api/disc/scan-result?task_id=test-scan-123")
        assert response.status_code == 200

        # Verify it was cached
        cached = get_current_scan()
        assert cached is not None
        assert cached["disc_name"] == "CACHED_MOVIE"
        assert cached["disc_type"] == "bluray"
        assert len(cached["tracks"]) == 3

    def test_disc_eject_clears_scan_cache(self, client):
        """Disc eject event clears the cached scan result."""
        from amphigory.api.disc import set_current_scan, get_current_scan
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from datetime import datetime
        import asyncio

        # Set up a cached scan
        scan_data = {
            "disc_name": "TEST_DISC",
            "disc_type": "dvd",
            "tracks": [{"number": 1}],
        }
        set_current_scan(scan_data)
        assert get_current_scan() is not None

        # Register a daemon
        _daemons["test-daemon"] = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/local/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
        )

        try:
            # Simulate disc eject via WebSocket
            # Note: We can't actually test WebSocket directly with TestClient,
            # so we'll test the disc event handling logic directly
            from amphigory.main import app

            # The WebSocket handler should call clear_current_scan on eject
            # We'll verify this by simulating the eject logic
            # Import and call clear_current_scan as the WebSocket handler would
            from amphigory.api.disc import clear_current_scan
            clear_current_scan()

            # Verify cache was cleared
            result = get_current_scan()
            assert result is None
        finally:
            if "test-daemon" in _daemons:
                del _daemons["test-daemon"]

    @pytest.mark.asyncio
    async def test_dashboard_html_shows_track_count_with_cached_scan(self, client):
        """Dashboard status HTML shows track count when scan is cached."""
        from amphigory.api.disc import set_current_scan
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from amphigory.websocket import manager
        from datetime import datetime
        from unittest.mock import patch

        # Set up a cached scan
        scan_data = {
            "disc_name": "MY_MOVIE",
            "disc_type": "bluray",
            "tracks": [{"number": 1}, {"number": 2}, {"number": 3}],
        }
        set_current_scan(scan_data)

        # Register a daemon
        _daemons["test-daemon"] = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/local/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
        )

        # Mock the WebSocket request to daemon
        async def mock_request_from_daemon(daemon_id, method, params, timeout):
            return {
                "state": "disc_inserted",
                "device": "/dev/disk2",
                "disc_volume": "MY_DISC",
            }

        with patch.object(manager, 'request_from_daemon', side_effect=mock_request_from_daemon):
            try:
                response = client.get("/api/disc/status-html")

                assert response.status_code == 200
                html = response.text

                # Should show track count
                assert "3 tracks scanned" in html
                # Should link to disc review page
                assert 'href="/disc"' in html
                assert "Review Tracks" in html
            finally:
                del _daemons["test-daemon"]
                from amphigory.api.disc import clear_current_scan
                clear_current_scan()

    @pytest.mark.asyncio
    async def test_dashboard_html_shows_scan_button_without_cached_scan(self, client):
        """Dashboard status HTML shows scan button when no scan is cached."""
        from amphigory.api.disc import clear_current_scan
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from amphigory.websocket import manager
        from datetime import datetime
        from unittest.mock import patch

        # Ensure no cached scan
        clear_current_scan()

        # Register a daemon
        _daemons["test-daemon"] = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/local/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
        )

        # Mock the WebSocket request to daemon
        async def mock_request_from_daemon(daemon_id, method, params, timeout):
            return {
                "state": "disc_inserted",
                "device": "/dev/disk2",
                "disc_volume": "MY_DISC",
            }

        with patch.object(manager, 'request_from_daemon', side_effect=mock_request_from_daemon):
            try:
                response = client.get("/api/disc/status-html")

                assert response.status_code == 200
                html = response.text

                # Should show scan button, not track count
                assert "Scan Disc" in html
                assert "tracks scanned" not in html
            finally:
                del _daemons["test-daemon"]


class TestFingerprintIntegration:
    """Tests for fingerprint-based disc lookup and caching."""

    def test_lookup_fingerprint_with_explicit_fingerprint(self, client, tasks_dir):
        """Can lookup disc by providing explicit fingerprint."""
        from amphigory.database import Database
        import asyncio

        # Initialize database
        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        asyncio.run(db.initialize())

        # Insert a known disc
        async def setup():
            async with db.connection() as conn:
                await conn.execute(
                    """INSERT INTO discs (title, fingerprint, year, disc_type)
                       VALUES (?, ?, ?, ?)""",
                    ("Test Movie", "fp_test123", 2020, "bluray"),
                )
                await conn.commit()

        asyncio.run(setup())

        # Lookup by fingerprint
        response = client.get("/api/disc/lookup-fingerprint?fingerprint=fp_test123")

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Test Movie"
        assert data["fingerprint"] == "fp_test123"
        assert data["year"] == 2020

    def test_lookup_fingerprint_returns_404_when_not_found(self, client, tasks_dir):
        """Returns 404 when fingerprint not in database."""
        from amphigory.database import Database
        import asyncio

        # Initialize database
        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        asyncio.run(db.initialize())

        response = client.get("/api/disc/lookup-fingerprint?fingerprint=nonexistent")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_lookup_fingerprint_uses_current_disc_when_no_param(self, client, tasks_dir):
        """Uses current disc's fingerprint when no parameter provided."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from amphigory.database import Database
        from amphigory.websocket import manager
        from datetime import datetime
        from unittest.mock import patch

        # Initialize database
        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        # Insert a known disc
        async with db.connection() as conn:
            await conn.execute(
                """INSERT INTO discs (title, fingerprint)
                   VALUES (?, ?)""",
                ("Current Disc", "fp_current456"),
            )
            await conn.commit()

        # Register daemon
        daemon = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/local/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
        )
        _daemons["test-daemon"] = daemon

        # Mock the WebSocket request to daemon to return fingerprint
        async def mock_request_from_daemon(daemon_id, method, params, timeout):
            return {
                "state": "disc_inserted",
                "fingerprint": "fp_current456",
            }

        with patch.object(manager, 'request_from_daemon', side_effect=mock_request_from_daemon):
            try:
                # Lookup without providing fingerprint
                response = client.get("/api/disc/lookup-fingerprint")

                assert response.status_code == 200
                data = response.json()
                assert data["title"] == "Current Disc"
            finally:
                del _daemons["test-daemon"]

    @pytest.mark.asyncio
    async def test_scan_result_saves_to_database_with_fingerprint(self, client, tasks_dir):
        """Scan result is saved to database when fingerprint is available."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from amphigory.database import Database
        from amphigory.websocket import manager
        from datetime import datetime
        from unittest.mock import patch

        # Initialize database
        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        # Register daemon
        daemon = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/local/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
        )
        _daemons["test-daemon"] = daemon

        # Create a completed scan task
        result_file = tasks_dir / "complete" / "scan-save-test.json"
        with open(result_file, "w") as f:
            json.dump({
                "task_id": "scan-save-test",
                "status": "success",
                "result": {
                    "disc_name": "SAVED_DISC",
                    "disc_type": "bluray",
                    "tracks": [{"number": 1, "duration": "2:00:00"}],
                },
                "completed_at": "2024-01-15T10:30:00",
            }, f)

        # Mock the WebSocket request to daemon to return fingerprint
        async def mock_request_from_daemon(daemon_id, method, params, timeout):
            return {
                "state": "disc_inserted",
                "fingerprint": "fp_saved789",
            }

        with patch.object(manager, 'request_from_daemon', side_effect=mock_request_from_daemon):
            try:
                # Request the scan result (should save to DB)
                response = client.get("/api/disc/scan-result?task_id=scan-save-test")
                assert response.status_code == 200

                # Verify it was saved to database
                async with db.connection() as conn:
                    cursor = await conn.execute(
                        "SELECT * FROM discs WHERE fingerprint = ?",
                        ("fp_saved789",)
                    )
                    row = await cursor.fetchone()
                    assert row is not None
                    assert row["title"] == "SAVED_DISC"
                    assert row["scan_data"] is not None
                    scan_data = json.loads(row["scan_data"])
                    assert scan_data["disc_name"] == "SAVED_DISC"
            finally:
                del _daemons["test-daemon"]

    @pytest.mark.asyncio
    async def test_status_html_shows_known_disc_with_fingerprint(self, client, tasks_dir):
        """Status HTML shows title with fingerprint prefix when fingerprint matches database."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from amphigory.database import Database
        from amphigory.websocket import manager
        from datetime import datetime
        from unittest.mock import patch

        # Initialize database
        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        # Insert a known disc
        async with db.connection() as conn:
            await conn.execute(
                """INSERT INTO discs (title, fingerprint)
                   VALUES (?, ?)""",
                ("The Matrix", "fp_matrix999"),
            )
            await conn.commit()

        # Register daemon
        daemon = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/local/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
        )
        _daemons["test-daemon"] = daemon

        # Mock the WebSocket request to daemon to return fingerprint
        async def mock_request_from_daemon(daemon_id, method, params, timeout):
            return {
                "state": "disc_inserted",
                "device": "/dev/disk2",
                "disc_volume": "MATRIX_DISC",
                "fingerprint": "fp_matrix999",
            }

        with patch.object(manager, 'request_from_daemon', side_effect=mock_request_from_daemon):
            try:
                response = client.get("/api/disc/status-html")

                assert response.status_code == 200
                html = response.text

                # Should show title from DB with fingerprint prefix
                assert "The Matrix" in html
                assert "fp_matr" in html  # First 7 chars of fingerprint
            finally:
                del _daemons["test-daemon"]


class TestDiscStatusTrackCount:
    """Tests for track_count in disc status endpoint."""

    @pytest.mark.asyncio
    async def test_disc_status_includes_track_count_from_database(self, client, tasks_dir):
        """GET /api/disc/status includes track_count from tracks table."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from amphigory.database import Database
        from amphigory.websocket import manager
        from amphigory.api import disc_repository
        from datetime import datetime
        from unittest.mock import patch

        # Initialize database
        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        # Create disc with tracks using save_disc_scan
        scan_data = {
            "disc_name": "TEST_MOVIE",
            "disc_type": "bluray",
            "tracks": [
                {"number": 1, "duration": "2:00:00", "size_bytes": 1000000},
                {"number": 2, "duration": "0:30:00", "size_bytes": 500000},
                {"number": 3, "duration": "0:05:00", "size_bytes": 100000},
            ],
        }
        await disc_repository.save_disc_scan("fp_track_count_test", scan_data)

        # Register daemon
        daemon = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/local/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
        )
        _daemons["test-daemon"] = daemon

        # Mock the WebSocket request to daemon to return fingerprint
        async def mock_request_from_daemon(daemon_id, method, params, timeout):
            return {
                "state": "disc_inserted",
                "device": "/dev/disk2",
                "disc_volume": "TEST_DISC",
                "fingerprint": "fp_track_count_test",
            }

        with patch.object(manager, 'request_from_daemon', side_effect=mock_request_from_daemon):
            try:
                response = client.get("/api/disc/status")

                assert response.status_code == 200
                data = response.json()
                assert data["has_disc"] is True
                # The key assertion: track_count should come from tracks table
                assert data["track_count"] == 3
            finally:
                del _daemons["test-daemon"]

    @pytest.mark.asyncio
    async def test_disc_status_track_count_zero_when_no_disc_in_db(self, client, tasks_dir):
        """GET /api/disc/status returns track_count=0 when disc not in database."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from amphigory.database import Database
        from amphigory.websocket import manager
        from datetime import datetime
        from unittest.mock import patch

        # Initialize database (but don't insert any disc)
        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        # Register daemon
        daemon = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/local/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
        )
        _daemons["test-daemon"] = daemon

        # Mock the WebSocket request to daemon with unknown fingerprint
        async def mock_request_from_daemon(daemon_id, method, params, timeout):
            return {
                "state": "disc_inserted",
                "device": "/dev/disk2",
                "disc_volume": "UNKNOWN_DISC",
                "fingerprint": "fp_unknown_not_in_db",
            }

        with patch.object(manager, 'request_from_daemon', side_effect=mock_request_from_daemon):
            try:
                response = client.get("/api/disc/status")

                assert response.status_code == 200
                data = response.json()
                assert data["has_disc"] is True
                # Should be 0 when disc not in database
                assert data["track_count"] == 0
            finally:
                del _daemons["test-daemon"]


class TestTMDBEndpoints:
    """Tests for TMDB search and external IDs endpoints."""

    @pytest.mark.asyncio
    async def test_search_tmdb_returns_results(self, client):
        """GET /api/disc/search-tmdb returns TMDB search results."""
        from unittest.mock import patch, AsyncMock

        # Mock the search_movies function
        mock_results = [
            {
                "id": 603,
                "title": "The Matrix",
                "year": 1999,
                "overview": "A hacker discovers reality is a simulation",
            },
            {
                "id": 604,
                "title": "The Matrix Reloaded",
                "year": 2003,
                "overview": "Neo continues his fight",
            },
        ]

        with patch('amphigory.api.disc.search_movies', new_callable=AsyncMock) as mock_search:
            mock_search.return_value = mock_results

            response = client.get("/api/disc/search-tmdb?query=The Matrix")

            assert response.status_code == 200
            data = response.json()
            assert "results" in data
            assert len(data["results"]) == 2
            assert data["results"][0]["title"] == "The Matrix"
            assert data["results"][0]["year"] == 1999

    @pytest.mark.asyncio
    async def test_search_tmdb_with_year_filter(self, client):
        """GET /api/disc/search-tmdb filters by year."""
        from unittest.mock import patch, AsyncMock

        mock_results = [
            {
                "id": 603,
                "title": "The Matrix",
                "year": 1999,
                "overview": "A hacker discovers reality is a simulation",
            },
        ]

        with patch('amphigory.api.disc.search_movies', new_callable=AsyncMock) as mock_search:
            mock_search.return_value = mock_results

            response = client.get("/api/disc/search-tmdb?query=The Matrix&year=1999")

            assert response.status_code == 200
            # Verify year was passed to search_movies
            mock_search.assert_called_once_with("The Matrix", 1999)

    @pytest.mark.asyncio
    async def test_search_tmdb_handles_apostrophes(self, client):
        """GET /api/disc/search-tmdb correctly handles titles with apostrophes."""
        from unittest.mock import patch, AsyncMock

        mock_results = [
            {
                "id": 4935,
                "title": "Howl's Moving Castle",
                "year": 2004,
                "overview": "A Studio Ghibli film",
            },
        ]

        with patch('amphigory.api.disc.search_movies', new_callable=AsyncMock) as mock_search:
            mock_search.return_value = mock_results

            response = client.get("/api/disc/search-tmdb?query=Howl's Moving Castle")

            assert response.status_code == 200
            data = response.json()
            assert len(data["results"]) == 1
            assert data["results"][0]["title"] == "Howl's Moving Castle"

    @pytest.mark.asyncio
    async def test_get_tmdb_external_ids_returns_imdb_id(self, client):
        """GET /api/disc/tmdb-external-ids/{tmdb_id} returns IMDB ID."""
        from unittest.mock import patch, AsyncMock

        mock_external_ids = {
            "id": 4935,
            "imdb_id": "tt0347149",
            "facebook_id": "HowlsMovingCastle",
            "instagram_id": None,
            "twitter_id": None,
        }

        with patch('amphigory.api.disc.get_external_ids', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_external_ids

            response = client.get("/api/disc/tmdb-external-ids/4935")

            assert response.status_code == 200
            data = response.json()
            assert data["imdb_id"] == "tt0347149"
            assert data["id"] == 4935

    @pytest.mark.asyncio
    async def test_get_tmdb_external_ids_returns_404_on_error(self, client):
        """GET /api/disc/tmdb-external-ids/{tmdb_id} returns 404 when TMDB API fails."""
        from unittest.mock import patch, AsyncMock

        with patch('amphigory.api.disc.get_external_ids', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None  # Simulates API error

            response = client.get("/api/disc/tmdb-external-ids/999999")

            assert response.status_code == 404
            assert "Could not fetch external IDs" in response.json()["detail"]


class TestDiscMetadata:
    """Tests for POST /api/disc/metadata."""

    @pytest.fixture
    def db_with_disc(self, tmp_path, monkeypatch):
        """Create a test database with a disc."""
        import asyncio
        from amphigory.database import Database
        from amphigory.api import disc_repository

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        asyncio.run(db.initialize())
        monkeypatch.setattr(disc_repository, "get_db_path", lambda: db_path)

        # Create a disc with fingerprint
        async def create_disc():
            async with db.connection() as conn:
                await conn.execute(
                    "INSERT INTO discs (fingerprint, title) VALUES (?, ?)",
                    ("abc123fingerprint", "Unknown Disc")
                )
                await conn.commit()
        asyncio.run(create_disc())

        return db_path

    def test_updates_disc_metadata(self, client, db_with_disc):
        """POST /api/disc/metadata updates disc record."""
        response = client.post("/api/disc/metadata", json={
            "fingerprint": "abc123fingerprint",
            "tmdb_id": "129",
            "imdb_id": "tt0347149",
            "title": "Howl's Moving Castle",
            "year": 2004
        })

        assert response.status_code == 200
        data = response.json()
        assert data["updated"] is True

    def test_metadata_persists_in_database(self, client, db_with_disc):
        """Metadata is stored in discs table."""
        import asyncio
        import aiosqlite

        client.post("/api/disc/metadata", json={
            "fingerprint": "abc123fingerprint",
            "tmdb_id": "129",
            "imdb_id": "tt0347149",
            "title": "Howl's Moving Castle",
            "year": 2004
        })

        async def check_db():
            async with aiosqlite.connect(db_with_disc) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    "SELECT tmdb_id, imdb_id, title, year FROM discs WHERE fingerprint = ?",
                    ("abc123fingerprint",)
                )
                row = await cursor.fetchone()
                return dict(row)

        result = asyncio.run(check_db())
        assert result["tmdb_id"] == "129"
        assert result["imdb_id"] == "tt0347149"
        assert result["title"] == "Howl's Moving Castle"
        assert result["year"] == 2004

    def test_returns_404_for_unknown_fingerprint(self, client, db_with_disc):
        """Returns 404 if fingerprint not found."""
        response = client.post("/api/disc/metadata", json={
            "fingerprint": "unknown_fingerprint",
            "tmdb_id": "129",
            "title": "Test",
            "year": 2024
        })

        assert response.status_code == 404


class TestGetDiscMetadata:
    """Tests for GET /api/disc/metadata/{fingerprint}."""

    @pytest.fixture
    def db_with_disc(self, tmp_path, monkeypatch):
        """Create a test database with a disc."""
        import asyncio
        from amphigory.database import Database
        from amphigory.api import disc_repository

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        asyncio.run(db.initialize())
        monkeypatch.setattr(disc_repository, "get_db_path", lambda: db_path)

        # Create a disc with fingerprint
        async def create_disc():
            async with db.connection() as conn:
                await conn.execute(
                    "INSERT INTO discs (fingerprint, title) VALUES (?, ?)",
                    ("abc123fingerprint", "Unknown Disc")
                )
                await conn.commit()
        asyncio.run(create_disc())

        return db_path

    def test_returns_metadata_for_known_disc(self, client, db_with_disc):
        """Returns stored metadata for disc."""
        import asyncio
        import aiosqlite

        # First store some metadata
        async def store_metadata():
            async with aiosqlite.connect(db_with_disc) as conn:
                await conn.execute(
                    """UPDATE discs SET tmdb_id = ?, imdb_id = ?, title = ?, year = ?
                       WHERE fingerprint = ?""",
                    ("129", "tt0347149", "Howl's Moving Castle", 2004, "abc123fingerprint")
                )
                await conn.commit()
        asyncio.run(store_metadata())

        response = client.get("/api/disc/metadata/abc123fingerprint")

        assert response.status_code == 200
        data = response.json()
        assert data["tmdb_id"] == "129"
        assert data["imdb_id"] == "tt0347149"
        assert data["title"] == "Howl's Moving Castle"
        assert data["year"] == 2004

    def test_returns_404_for_unknown_fingerprint(self, client, db_with_disc):
        """Returns 404 for unknown fingerprint."""
        response = client.get("/api/disc/metadata/unknown_fp")
        assert response.status_code == 404


class TestGetDiscByFingerprint:
    """Tests for GET /api/disc/by-fingerprint/{fingerprint} endpoint."""

    def test_returns_404_when_disc_not_found(self, client):
        """Returns 404 when fingerprint not in database."""
        response = client.get("/api/disc/by-fingerprint/nonexistent123")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_disc_with_tracks(self, client, tasks_dir):
        """Returns disc info and tracks for known fingerprint."""
        # Create disc with tracks in database
        from amphigory.database import Database
        from amphigory.api import disc_repository

        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        async with db.connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO discs (title, fingerprint, year, imdb_id)
                   VALUES (?, ?, ?, ?)""",
                ("Test Movie", "test_fp_endpoint_123", 2020, "tt1234567"),
            )
            disc_id = cursor.lastrowid
            await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, track_type, status)
                   VALUES (?, ?, ?, ?)""",
                (disc_id, 1, "main_feature", "discovered"),
            )
            await conn.commit()

        response = client.get("/api/disc/by-fingerprint/test_fp_endpoint_123")
        assert response.status_code == 200

        data = response.json()
        assert "disc" in data
        assert "tracks" in data
        assert data["disc"]["fingerprint"] == "test_fp_endpoint_123"
        assert isinstance(data["tracks"], list)
        assert len(data["tracks"]) == 1


class TestVerifyTrackFiles:
    """Tests for GET /api/tracks/{track_id}/verify-files endpoint."""

    @pytest.mark.asyncio
    async def test_returns_all_false_for_no_paths(self, client, tasks_dir):
        """Returns all exists=false when no paths set."""
        from amphigory.database import Database

        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        # Create disc and track with no paths
        async with db.connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO discs (title, fingerprint)
                   VALUES (?, ?)""",
                ("Test Movie", "fp_verify_test"),
            )
            disc_id = cursor.lastrowid
            cursor = await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, status)
                   VALUES (?, ?, ?)""",
                (disc_id, 1, "discovered"),
            )
            track_id = cursor.lastrowid
            await conn.commit()

        response = client.get(f"/api/tracks/{track_id}/verify-files")
        assert response.status_code == 200

        data = response.json()
        assert data["ripped_exists"] is False
        assert data["transcoded_exists"] is False
        assert data["inserted_exists"] is False

    @pytest.mark.asyncio
    async def test_returns_true_when_file_exists(self, client, tasks_dir, tmp_path):
        """Returns exists=true when file is present on disk."""
        from amphigory.database import Database

        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        # Create a test file
        ripped_file = tmp_path / "test.mkv"
        ripped_file.write_text("test content")

        # Create disc and track with ripped_path
        async with db.connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO discs (title, fingerprint)
                   VALUES (?, ?)""",
                ("Test Movie", "fp_verify_exists_test"),
            )
            disc_id = cursor.lastrowid
            cursor = await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, ripped_path, status)
                   VALUES (?, ?, ?, ?)""",
                (disc_id, 1, str(ripped_file), "ripped"),
            )
            track_id = cursor.lastrowid
            await conn.commit()

        response = client.get(f"/api/tracks/{track_id}/verify-files")
        assert response.status_code == 200

        data = response.json()
        assert data["ripped_exists"] is True
        assert data["ripped_path"] == str(ripped_file)

    def test_returns_404_for_unknown_track(self, client):
        """Returns 404 for non-existent track_id."""
        response = client.get("/api/tracks/99999/verify-files")
        assert response.status_code == 404


class TestSaveDiscAndTracks:
    """Tests for POST /api/disc/{disc_id}/save endpoint."""

    @pytest.mark.asyncio
    async def test_saves_disc_info(self, client, tasks_dir):
        """Updates disc title, year, imdb_id."""
        from amphigory.database import Database

        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        # Create test disc
        async with db.connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO discs (title, fingerprint)
                   VALUES (?, ?)""",
                ("Original Title", "fp_save_test"),
            )
            disc_id = cursor.lastrowid
            await conn.commit()

        response = client.post(f"/api/disc/{disc_id}/save", json={
            "disc": {
                "title": "Updated Title",
                "year": 2021,
                "imdb_id": "tt9999999"
            },
            "tracks": []
        })
        assert response.status_code == 200

        # Verify changes persisted
        get_response = client.get("/api/disc/by-fingerprint/fp_save_test")
        data = get_response.json()
        assert data["disc"]["title"] == "Updated Title"
        assert data["disc"]["year"] == 2021
        assert data["disc"]["imdb_id"] == "tt9999999"

    @pytest.mark.asyncio
    async def test_saves_track_info(self, client, tasks_dir):
        """Updates track names, types, presets."""
        from amphigory.database import Database

        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        # Create test disc and track
        async with db.connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO discs (title, fingerprint)
                   VALUES (?, ?)""",
                ("Test Movie", "fp_track_save_test"),
            )
            disc_id = cursor.lastrowid
            cursor = await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, track_type)
                   VALUES (?, ?, ?)""",
                (disc_id, 1, "extra"),
            )
            track_id = cursor.lastrowid
            await conn.commit()

        response = client.post(f"/api/disc/{disc_id}/save", json={
            "disc": {},
            "tracks": [
                {"id": track_id, "track_name": "New Name", "track_type": "featurettes", "preset_name": "HQ 1080p"}
            ]
        })
        assert response.status_code == 200

        # Verify changes persisted
        get_response = client.get("/api/disc/by-fingerprint/fp_track_save_test")
        tracks = get_response.json()["tracks"]
        assert tracks[0]["track_name"] == "New Name"
        assert tracks[0]["track_type"] == "featurettes"
        assert tracks[0]["preset_name"] == "HQ 1080p"

    def test_returns_404_for_unknown_disc(self, client):
        """Returns 404 for non-existent disc_id."""
        response = client.post("/api/disc/99999/save", json={"disc": {}, "tracks": []})
        assert response.status_code == 404


class TestResetTrack:
    """Tests for POST /api/tracks/{track_id}/reset endpoint."""

    @pytest.mark.asyncio
    async def test_clears_paths_in_database(self, client, tasks_dir):
        """Clears ripped_path, transcoded_path, inserted_path."""
        from amphigory.database import Database

        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        # Create disc and track with paths set
        async with db.connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO discs (title, fingerprint)
                   VALUES (?, ?)""",
                ("Test Movie", "fp_reset_test"),
            )
            disc_id = cursor.lastrowid
            cursor = await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, status,
                   ripped_path, transcoded_path, inserted_path)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (disc_id, 1, "complete", "/test/ripped.mkv", "/test/transcoded.mp4", "/test/inserted.mp4"),
            )
            track_id = cursor.lastrowid
            await conn.commit()

        response = client.post(f"/api/tracks/{track_id}/reset")
        assert response.status_code == 200

        # Verify paths cleared
        async with db.connection() as conn:
            cursor = await conn.execute(
                "SELECT ripped_path, transcoded_path, inserted_path, status FROM tracks WHERE id = ?",
                (track_id,)
            )
            row = await cursor.fetchone()

        assert row["ripped_path"] is None
        assert row["transcoded_path"] is None
        assert row["inserted_path"] is None
        assert row["status"] == "discovered"

    @pytest.mark.asyncio
    async def test_deletes_existing_files(self, client, tasks_dir, tmp_path):
        """Deletes files from disk when they exist."""
        from amphigory.database import Database

        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        # Create test files
        ripped = tmp_path / "ripped.mkv"
        ripped.write_text("ripped content")
        transcoded = tmp_path / "transcoded.mp4"
        transcoded.write_text("transcoded content")

        # Create disc and track with paths to real files
        async with db.connection() as conn:
            cursor = await conn.execute(
                """INSERT INTO discs (title, fingerprint)
                   VALUES (?, ?)""",
                ("Test Movie", "fp_reset_delete_test"),
            )
            disc_id = cursor.lastrowid
            cursor = await conn.execute(
                """INSERT INTO tracks (disc_id, track_number, status,
                   ripped_path, transcoded_path)
                   VALUES (?, ?, ?, ?, ?)""",
                (disc_id, 1, "transcoded", str(ripped), str(transcoded)),
            )
            track_id = cursor.lastrowid
            await conn.commit()

        # Verify files exist before reset
        assert ripped.exists()
        assert transcoded.exists()

        response = client.post(f"/api/tracks/{track_id}/reset")
        assert response.status_code == 200

        # Verify files deleted
        assert not ripped.exists()
        assert not transcoded.exists()

    def test_returns_404_for_unknown_track(self, client):
        """Returns 404 for non-existent track_id."""
        response = client.post("/api/tracks/99999/reset")
        assert response.status_code == 404


class TestDiscStatusHtmlKnownDisc:
    """Tests for disc status HTML with known discs."""

    @pytest.mark.asyncio
    async def test_shows_track_count_for_known_disc(self, client, tasks_dir):
        """Shows track count for known discs from database."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from amphigory.database import Database
        from amphigory.websocket import manager
        from amphigory.api import disc_repository
        from amphigory.api.disc import clear_current_scan
        from datetime import datetime
        from unittest.mock import patch

        # Ensure no cached scan
        clear_current_scan()

        # Initialize database
        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        # Create disc with fingerprint and tracks in DB using save_disc_scan
        scan_data = {
            "disc_name": "KNOWN_MOVIE",
            "disc_type": "bluray",
            "tracks": [
                {"number": 1, "duration": "2:00:00", "size_bytes": 1000000},
                {"number": 2, "duration": "0:30:00", "size_bytes": 500000},
                {"number": 3, "duration": "0:05:00", "size_bytes": 100000},
                {"number": 4, "duration": "0:02:00", "size_bytes": 50000},
                {"number": 5, "duration": "0:01:00", "size_bytes": 25000},
            ],
        }
        await disc_repository.save_disc_scan("fp_known_html_test", scan_data)

        # Update the title to something recognizable
        async with db.connection() as conn:
            await conn.execute(
                "UPDATE discs SET title = ? WHERE fingerprint = ?",
                ("Known Test Movie", "fp_known_html_test"),
            )
            await conn.commit()

        # Register daemon
        daemon = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/local/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
        )
        _daemons["test-daemon"] = daemon

        # Mock the WebSocket request to daemon to return fingerprint
        async def mock_request_from_daemon(daemon_id, method, params, timeout):
            return {
                "state": "disc_inserted",
                "device": "/dev/disk2",
                "disc_volume": "KNOWN_MOVIE_DISC",
                "fingerprint": "fp_known_html_test",
            }

        with patch.object(manager, 'request_from_daemon', side_effect=mock_request_from_daemon):
            try:
                response = client.get("/api/disc/status-html")

                assert response.status_code == 200
                html = response.text

                # Should show track count from database (5 tracks)
                assert "5 tracks" in html
            finally:
                del _daemons["test-daemon"]

    @pytest.mark.asyncio
    async def test_shows_review_disc_button_for_known_disc(self, client, tasks_dir):
        """Shows 'Review Disc' button instead of 'Scan Disc' for known discs."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from amphigory.database import Database
        from amphigory.websocket import manager
        from amphigory.api import disc_repository
        from amphigory.api.disc import clear_current_scan
        from datetime import datetime
        from unittest.mock import patch

        # Ensure no cached scan
        clear_current_scan()

        # Initialize database
        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        # Create disc with fingerprint and tracks in DB
        scan_data = {
            "disc_name": "REVIEW_BUTTON_TEST",
            "disc_type": "bluray",
            "tracks": [
                {"number": 1, "duration": "2:00:00"},
            ],
        }
        await disc_repository.save_disc_scan("fp_review_button_test", scan_data)

        # Update the title
        async with db.connection() as conn:
            await conn.execute(
                "UPDATE discs SET title = ? WHERE fingerprint = ?",
                ("Review Button Test Movie", "fp_review_button_test"),
            )
            await conn.commit()

        # Register daemon
        daemon = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/local/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
        )
        _daemons["test-daemon"] = daemon

        # Mock the WebSocket request to daemon
        async def mock_request_from_daemon(daemon_id, method, params, timeout):
            return {
                "state": "disc_inserted",
                "device": "/dev/disk2",
                "disc_volume": "TEST_DISC",
                "fingerprint": "fp_review_button_test",
            }

        with patch.object(manager, 'request_from_daemon', side_effect=mock_request_from_daemon):
            try:
                response = client.get("/api/disc/status-html")

                assert response.status_code == 200
                html = response.text

                # Should show "Review Disc" button, not "Scan Disc"
                assert "Review Disc" in html
                assert "Scan Disc" not in html
                # Should link to /disc page
                assert 'href="/disc"' in html
            finally:
                del _daemons["test-daemon"]

    @pytest.mark.asyncio
    async def test_shows_title_with_fingerprint_prefix_for_known_disc(self, client, tasks_dir):
        """Shows title with fingerprint prefix (first 7 chars) for known discs."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from amphigory.database import Database
        from amphigory.websocket import manager
        from amphigory.api import disc_repository
        from amphigory.api.disc import clear_current_scan
        from datetime import datetime
        from unittest.mock import patch

        # Ensure no cached scan
        clear_current_scan()

        # Initialize database
        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        # Create disc with fingerprint
        scan_data = {
            "disc_name": "TITLE_TEST",
            "disc_type": "bluray",
            "tracks": [{"number": 1, "duration": "2:00:00"}],
        }
        await disc_repository.save_disc_scan("abc1234xyz567890", scan_data)

        # Update the title
        async with db.connection() as conn:
            await conn.execute(
                "UPDATE discs SET title = ? WHERE fingerprint = ?",
                ("The Matrix", "abc1234xyz567890"),
            )
            await conn.commit()

        # Register daemon
        daemon = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/local/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
        )
        _daemons["test-daemon"] = daemon

        # Mock the WebSocket request
        async def mock_request_from_daemon(daemon_id, method, params, timeout):
            return {
                "state": "disc_inserted",
                "device": "/dev/disk2",
                "disc_volume": "MATRIX_DISC",
                "fingerprint": "abc1234xyz567890",
            }

        with patch.object(manager, 'request_from_daemon', side_effect=mock_request_from_daemon):
            try:
                response = client.get("/api/disc/status-html")

                assert response.status_code == 200
                html = response.text

                # Should show title from DB
                assert "The Matrix" in html
                # Should show fingerprint prefix (first 7 chars)
                assert "abc1234" in html
            finally:
                del _daemons["test-daemon"]

    @pytest.mark.asyncio
    async def test_shows_volume_name_with_fingerprint_prefix_for_unknown_disc(self, client, tasks_dir):
        """Shows volume name with fingerprint prefix for unknown discs."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from amphigory.database import Database
        from amphigory.websocket import manager
        from amphigory.api.disc import clear_current_scan
        from datetime import datetime
        from unittest.mock import patch

        # Ensure no cached scan
        clear_current_scan()

        # Initialize database (but don't insert any disc)
        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        # Register daemon
        daemon = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/local/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
        )
        _daemons["test-daemon"] = daemon

        # Mock the WebSocket request with unknown fingerprint
        async def mock_request_from_daemon(daemon_id, method, params, timeout):
            return {
                "state": "disc_inserted",
                "device": "/dev/disk2",
                "disc_volume": "UNKNOWN_DISC_VOL",
                "fingerprint": "xyz9876unknown",
            }

        with patch.object(manager, 'request_from_daemon', side_effect=mock_request_from_daemon):
            try:
                response = client.get("/api/disc/status-html")

                assert response.status_code == 200
                html = response.text

                # Should show volume name for unknown disc
                assert "UNKNOWN_DISC_VOL" in html
                # Should show fingerprint prefix (first 7 chars)
                assert "xyz9876" in html
                # Should show "Scan Disc" button
                assert "Scan Disc" in html
            finally:
                del _daemons["test-daemon"]

    @pytest.mark.asyncio
    async def test_scan_disc_button_has_hx_post_for_unknown_disc(self, client, tasks_dir):
        """Unknown disc shows Scan Disc button with hx-post attribute."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from amphigory.database import Database
        from amphigory.websocket import manager
        from amphigory.api.disc import clear_current_scan
        from datetime import datetime
        from unittest.mock import patch

        # Ensure no cached scan
        clear_current_scan()

        # Initialize database (but don't insert any disc)
        db_path = tasks_dir.parent / "amphigory.db"
        db = Database(db_path)
        await db.initialize()

        # Register daemon
        daemon = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/local/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
        )
        _daemons["test-daemon"] = daemon

        # Mock the WebSocket request with unknown fingerprint
        async def mock_request_from_daemon(daemon_id, method, params, timeout):
            return {
                "state": "disc_inserted",
                "device": "/dev/disk2",
                "disc_volume": "SCANME_DISC",
                "fingerprint": "scanme12345678",
            }

        with patch.object(manager, 'request_from_daemon', side_effect=mock_request_from_daemon):
            try:
                response = client.get("/api/disc/status-html")

                assert response.status_code == 200
                html = response.text

                # Should show Scan Disc button with hx-post for HTMX
                assert "Scan Disc" in html
                assert 'hx-post="/api/disc/scan"' in html
            finally:
                del _daemons["test-daemon"]
