"""Tests for drives API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock


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
        """GET /api/drives returns drive info when daemons connected."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from datetime import datetime

        # Register a daemon with a drive
        _daemons["test-daemon"] = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
            disc_inserted=True,
            disc_device="/dev/rdisk4",
            disc_volume="MY_MOVIE",
        )

        try:
            response = test_client.get("/api/drives")

            assert response.status_code == 200
            data = response.json()
            assert len(data["drives"]) == 1
            assert data["drives"][0]["daemon_id"] == "test-daemon"
            assert data["drives"][0]["disc_inserted"] == True
            assert data["drives"][0]["disc_volume"] == "MY_MOVIE"
        finally:
            _daemons.clear()

    def test_get_drive_by_id_returns_drive_info(self, test_client):
        """GET /api/drives/{drive_id} returns drive info when found."""
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from datetime import datetime

        # Register a daemon with a drive
        _daemons["test-daemon"] = RegisteredDaemon(
            daemon_id="test-daemon",
            makemkvcon_path="/usr/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=datetime.now(),
            last_seen=datetime.now(),
            disc_inserted=True,
            disc_device="/dev/rdisk4",
            disc_volume="MY_MOVIE",
        )

        try:
            response = test_client.get("/api/drives/test-daemon:rdisk4")

            assert response.status_code == 200
            data = response.json()
            assert data["daemon_id"] == "test-daemon"
            assert data["drive_id"] == "test-daemon:rdisk4"
            assert data["disc_inserted"] == True
            assert data["disc_volume"] == "MY_MOVIE"
        finally:
            _daemons.clear()
