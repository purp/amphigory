"""Tests for drives API endpoints."""

import pytest
import asyncio
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock


class TestDrivesEndpoints:
    """Tests for /api/drives endpoints."""

    def test_get_drives_returns_empty_list_when_no_daemons(self, test_client):
        """GET /api/drives returns empty list when no daemons connected."""
        from amphigory.api.settings import _daemons
        _daemons.clear()

        response = test_client.get("/api/drives")

        assert response.status_code == 200
        assert response.json() == {"drives": []}

    def test_get_drive_by_id_returns_404_when_not_found(self, test_client):
        """GET /api/drives/{drive_id} returns 404 for unknown drive."""
        from amphigory.api.settings import _daemons
        _daemons.clear()

        response = test_client.get("/api/drives/unknown:rdisk0")

        assert response.status_code == 404

    def test_get_drives_list_returns_drive_info(self, test_client):
        """GET /api/drives returns fresh drive info via WebSocket query."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from datetime import datetime

        # Register a daemon with a drive
        _daemons["test-daemon"] = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
            disc_inserted=False,  # Old stale data
            disc_device="/dev/rdisk4",
            disc_volume=None,  # Old stale data
        )

        # Mock the WebSocket manager's request_from_daemon to return fresh data
        mock_drive_data = {
            "drive_id": "test-daemon:rdisk4",
            "daemon_id": "test-daemon",
            "device": "/dev/rdisk4",
            "state": "disc_inserted",
            "disc_volume": "MY_MOVIE",
            "disc_type": "dvd",
            "fingerprint": "abc123",
            "scan_status": "completed",
            "scan_task_id": None,
            "scan_result": None,
            "scan_error": None,
            "rip_task_id": None,
            "rip_track_number": None,
            "rip_progress": None,
            "disc_inserted_at": "2024-12-24T10:00:00",
            "last_updated": "2024-12-24T10:00:00",
        }

        try:
            with patch("amphigory.api.drives.manager") as mock_manager:
                # Setup async mock for request_from_daemon
                mock_manager.request_from_daemon = AsyncMock(return_value=mock_drive_data)

                response = test_client.get("/api/drives")

                assert response.status_code == 200
                data = response.json()
                assert len(data["drives"]) == 1

                # Verify we got fresh data from WebSocket, not stale _daemons data
                drive = data["drives"][0]
                assert drive["daemon_id"] == "test-daemon"
                assert drive["drive_id"] == "test-daemon:rdisk4"
                assert drive["disc_inserted"] == True
                assert drive["disc_volume"] == "MY_MOVIE"
                assert drive["disc_type"] == "dvd"
                assert drive["fingerprint"] == "abc123"
                assert drive["scan_status"] == "completed"
                assert drive["state"] == "disc_inserted"

                # Verify WebSocket was queried
                mock_manager.request_from_daemon.assert_called_once_with(
                    "test-daemon", "get_drive_status", {}, timeout=5.0
                )
        finally:
            _daemons.clear()

    def test_get_drive_by_id_returns_drive_info(self, test_client):
        """GET /api/drives/{drive_id} returns fresh drive info via WebSocket query."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from datetime import datetime

        # Register a daemon with a drive
        _daemons["test-daemon"] = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
            disc_inserted=False,  # Old stale data
            disc_device="/dev/rdisk4",
            disc_volume=None,  # Old stale data
        )

        # Mock the WebSocket manager's request_from_daemon to return fresh data
        mock_drive_data = {
            "drive_id": "test-daemon:rdisk4",
            "daemon_id": "test-daemon",
            "device": "/dev/rdisk4",
            "state": "disc_inserted",
            "disc_volume": "MY_MOVIE",
            "disc_type": "dvd",
            "fingerprint": "abc123",
            "scan_status": "completed",
            "scan_task_id": None,
            "scan_result": None,
            "scan_error": None,
            "rip_task_id": None,
            "rip_track_number": None,
            "rip_progress": None,
            "disc_inserted_at": "2024-12-24T10:00:00",
            "last_updated": "2024-12-24T10:00:00",
        }

        try:
            with patch("amphigory.api.drives.manager") as mock_manager:
                # Setup async mock for request_from_daemon
                mock_manager.request_from_daemon = AsyncMock(return_value=mock_drive_data)

                response = test_client.get("/api/drives/test-daemon:rdisk4")

                assert response.status_code == 200
                data = response.json()
                assert data["daemon_id"] == "test-daemon"
                assert data["drive_id"] == "test-daemon:rdisk4"
                assert data["disc_inserted"] == True
                assert data["disc_volume"] == "MY_MOVIE"
                assert data["disc_type"] == "dvd"
                assert data["fingerprint"] == "abc123"
                assert data["scan_status"] == "completed"

                # Verify WebSocket was queried
                mock_manager.request_from_daemon.assert_called_once_with(
                    "test-daemon", "get_drive_status", {}, timeout=5.0
                )
        finally:
            _daemons.clear()

    def test_get_drives_list_skips_daemon_on_websocket_timeout(self, test_client):
        """GET /api/drives skips daemon when WebSocket query times out."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from datetime import datetime

        # Register two daemons
        _daemons["daemon1"] = RegisteredDaemon(
            daemon_id="daemon1",
            makemkvcon_path="/usr/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
            disc_inserted=False,
            disc_device="/dev/rdisk4",
            disc_volume=None,
        )
        _daemons["daemon2"] = RegisteredDaemon(
            daemon_id="daemon2",
            makemkvcon_path="/usr/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
            disc_inserted=False,
            disc_device="/dev/rdisk5",
            disc_volume=None,
        )

        mock_drive_data = {
            "drive_id": "daemon2:rdisk5",
            "daemon_id": "daemon2",
            "device": "/dev/rdisk5",
            "state": "disc_inserted",
            "disc_volume": "GOOD_DISC",
            "disc_type": "dvd",
            "fingerprint": "xyz789",
            "scan_status": None,
            "scan_task_id": None,
            "scan_result": None,
            "scan_error": None,
            "rip_task_id": None,
            "rip_track_number": None,
            "rip_progress": None,
            "disc_inserted_at": "2024-12-24T10:00:00",
            "last_updated": "2024-12-24T10:00:00",
        }

        try:
            with patch("amphigory.api.drives.manager") as mock_manager:
                # First call times out, second call succeeds
                mock_manager.request_from_daemon = AsyncMock(
                    side_effect=[asyncio.TimeoutError(), mock_drive_data]
                )

                response = test_client.get("/api/drives")

                assert response.status_code == 200
                data = response.json()
                # Only daemon2 should be returned (daemon1 timed out)
                assert len(data["drives"]) == 1
                assert data["drives"][0]["daemon_id"] == "daemon2"
                assert data["drives"][0]["disc_volume"] == "GOOD_DISC"
        finally:
            _daemons.clear()

    def test_get_drives_list_skips_daemon_on_websocket_error(self, test_client):
        """GET /api/drives skips daemon when WebSocket query raises KeyError."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from datetime import datetime

        # Register a daemon
        _daemons["test-daemon"] = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
            disc_inserted=False,
            disc_device="/dev/rdisk4",
            disc_volume=None,
        )

        try:
            with patch("amphigory.api.drives.manager") as mock_manager:
                # Daemon not connected
                mock_manager.request_from_daemon = AsyncMock(
                    side_effect=KeyError("Daemon test-daemon not connected")
                )

                response = test_client.get("/api/drives")

                assert response.status_code == 200
                data = response.json()
                # Daemon skipped due to connection error
                assert len(data["drives"]) == 0
        finally:
            _daemons.clear()

    def test_get_drive_by_id_returns_404_on_websocket_error(self, test_client):
        """GET /api/drives/{drive_id} returns 404 when WebSocket query fails."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from datetime import datetime

        # Register a daemon
        _daemons["test-daemon"] = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
            disc_inserted=False,
            disc_device="/dev/rdisk4",
            disc_volume=None,
        )

        try:
            with patch("amphigory.api.drives.manager") as mock_manager:
                # Daemon not connected
                mock_manager.request_from_daemon = AsyncMock(
                    side_effect=KeyError("Daemon test-daemon not connected")
                )

                response = test_client.get("/api/drives/test-daemon:rdisk4")

                assert response.status_code == 404
        finally:
            _daemons.clear()
