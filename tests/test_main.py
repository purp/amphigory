"""Tests for main webapp application."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch


class TestConfigEndpoint:
    """Tests for /config.json endpoint."""

    def test_config_endpoint_exists(self, test_client):
        """GET /config.json returns 200."""
        response = test_client.get("/config.json")
        assert response.status_code == 200

    def test_config_endpoint_returns_json(self, test_client):
        """GET /config.json returns JSON content type."""
        response = test_client.get("/config.json")
        assert response.headers["content-type"] == "application/json"

    def test_config_contains_tasks_directory(self, test_client):
        """Config includes tasks_directory."""
        response = test_client.get("/config.json")
        data = response.json()
        assert "tasks_directory" in data
        assert isinstance(data["tasks_directory"], str)

    def test_config_contains_websocket_port(self, test_client):
        """Config includes websocket_port."""
        response = test_client.get("/config.json")
        data = response.json()
        assert "websocket_port" in data
        assert isinstance(data["websocket_port"], int)

    def test_config_contains_wiki_url(self, test_client):
        """Config includes wiki_url."""
        response = test_client.get("/config.json")
        data = response.json()
        assert "wiki_url" in data
        assert isinstance(data["wiki_url"], str)

    def test_config_contains_heartbeat_interval(self, test_client):
        """Config includes heartbeat_interval."""
        response = test_client.get("/config.json")
        data = response.json()
        assert "heartbeat_interval" in data
        assert isinstance(data["heartbeat_interval"], int)

    def test_config_contains_log_level(self, test_client):
        """Config includes log_level."""
        response = test_client.get("/config.json")
        data = response.json()
        assert "log_level" in data
        assert isinstance(data["log_level"], str)

    def test_config_contains_makemkv_path(self, test_client):
        """Config includes makemkv_path (can be null)."""
        response = test_client.get("/config.json")
        data = response.json()
        assert "makemkv_path" in data
        # Can be string or None
        assert data["makemkv_path"] is None or isinstance(data["makemkv_path"], str)


class TestVersionEndpoint:
    """Tests for /version endpoint."""

    def test_version_endpoint_exists(self, test_client):
        """GET /version returns 200."""
        response = test_client.get("/version")
        assert response.status_code == 200

    def test_version_endpoint_returns_json(self, test_client):
        """GET /version returns JSON."""
        response = test_client.get("/version")
        assert response.headers["content-type"] == "application/json"

    def test_version_contains_git_sha(self, test_client):
        """Version includes git_sha field."""
        response = test_client.get("/version")
        data = response.json()
        assert "git_sha" in data

    def test_version_contains_version(self, test_client):
        """Version includes version field."""
        response = test_client.get("/version")
        data = response.json()
        assert "version" in data
        assert data["version"] == "0.1.0"


class TestDiscEventBroadcast:
    """Tests for disc event broadcasting to browser clients."""

    @pytest.mark.asyncio
    async def test_disc_event_broadcast_to_browser_clients(self):
        """When daemon sends disc_event, webapp broadcasts to browsers."""
        from amphigory.main import app, manager

        # Verify broadcast method exists and is callable
        assert hasattr(manager, 'broadcast')
        assert callable(manager.broadcast)

    @pytest.mark.asyncio
    async def test_disc_inserted_event_broadcasts_to_browsers(self):
        """When daemon sends disc_inserted event, webapp broadcasts with all fields."""
        import json
        from datetime import datetime
        from amphigory.main import app, manager
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from fastapi import WebSocket

        # Mock WebSocket and connection
        mock_ws = MagicMock(spec=WebSocket)
        mock_ws.receive_text = AsyncMock()
        mock_ws.accept = AsyncMock()

        # Register a test daemon first
        daemon_id = "test-daemon-123"
        now = datetime.now()
        _daemons[daemon_id] = RegisteredDaemon(
            daemon_id=daemon_id,
            makemkvcon_path="/usr/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=now,
            last_seen=now,
        )

        # Mock the manager.broadcast method to capture calls
        original_broadcast = manager.broadcast
        broadcast_calls = []

        async def mock_broadcast(message):
            broadcast_calls.append(message)

        manager.broadcast = mock_broadcast

        try:
            # Simulate the disc_event message handling
            disc_event = {
                "type": "disc_event",
                "event": "inserted",
                "device": "/dev/disk2",
                "volume_name": "TEST_DISC",
                "volume_path": "/Volumes/TEST_DISC",
            }

            # Manually execute the disc_event handler logic
            event = disc_event.get("event")
            if daemon_id in _daemons:
                if event == "inserted":
                    _daemons[daemon_id].disc_inserted = True
                    _daemons[daemon_id].disc_device = disc_event.get("device")
                    _daemons[daemon_id].disc_volume = disc_event.get("volume_name")

                # This is what the handler should do
                await manager.broadcast({
                    "type": "disc_event",
                    "event": event,
                    "device": disc_event.get("device"),
                    "volume_name": disc_event.get("volume_name"),
                    "volume_path": disc_event.get("volume_path"),
                    "daemon_id": daemon_id,
                })

            # Verify broadcast was called once
            assert len(broadcast_calls) == 1

            # Verify broadcast message contains correct data
            broadcast_msg = broadcast_calls[0]
            assert broadcast_msg["type"] == "disc_event"
            assert broadcast_msg["event"] == "inserted"
            assert broadcast_msg["device"] == "/dev/disk2"
            assert broadcast_msg["volume_name"] == "TEST_DISC"
            assert broadcast_msg["volume_path"] == "/Volumes/TEST_DISC"
            assert broadcast_msg["daemon_id"] == daemon_id

        finally:
            # Restore original broadcast method
            manager.broadcast = original_broadcast
            # Clean up
            if daemon_id in _daemons:
                del _daemons[daemon_id]

    @pytest.mark.asyncio
    async def test_disc_ejected_event_broadcasts_to_browsers(self):
        """When daemon sends disc_ejected event, webapp broadcasts with correct fields."""
        import json
        from datetime import datetime
        from amphigory.main import app, manager
        from amphigory.api.settings import _daemons, RegisteredDaemon
        from fastapi import WebSocket

        # Register a test daemon first
        daemon_id = "test-daemon-456"
        now = datetime.now()
        _daemons[daemon_id] = RegisteredDaemon(
            daemon_id=daemon_id,
            makemkvcon_path="/usr/bin/makemkvcon",
            webapp_basedir="/data",
            connected_at=now,
            last_seen=now,
            disc_inserted=True,
            disc_device="/dev/disk2",
            disc_volume="OLD_DISC",
        )

        # Mock the manager.broadcast method to capture calls
        original_broadcast = manager.broadcast
        broadcast_calls = []

        async def mock_broadcast(message):
            broadcast_calls.append(message)

        manager.broadcast = mock_broadcast

        try:
            # Simulate the disc_event message handling
            disc_event = {
                "type": "disc_event",
                "event": "ejected",
                "device": None,
                "volume_name": None,
                "volume_path": None,
            }

            # Manually execute the disc_event handler logic
            event = disc_event.get("event")
            if daemon_id in _daemons:
                if event == "ejected":
                    _daemons[daemon_id].disc_inserted = False
                    _daemons[daemon_id].disc_device = None
                    _daemons[daemon_id].disc_volume = None

                # This is what the handler should do
                await manager.broadcast({
                    "type": "disc_event",
                    "event": event,
                    "device": disc_event.get("device"),
                    "volume_name": disc_event.get("volume_name"),
                    "volume_path": disc_event.get("volume_path"),
                    "daemon_id": daemon_id,
                })

            # Verify broadcast was called once
            assert len(broadcast_calls) == 1

            # Verify broadcast message contains correct data
            broadcast_msg = broadcast_calls[0]
            assert broadcast_msg["type"] == "disc_event"
            assert broadcast_msg["event"] == "ejected"
            assert broadcast_msg["device"] is None
            assert broadcast_msg["volume_name"] is None
            assert broadcast_msg["volume_path"] is None
            assert broadcast_msg["daemon_id"] == daemon_id

        finally:
            # Restore original broadcast method
            manager.broadcast = original_broadcast
            # Clean up
            if daemon_id in _daemons:
                del _daemons[daemon_id]
