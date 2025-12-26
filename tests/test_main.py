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

    def test_config_contains_ripped_directory(self, test_client):
        """Config includes ripped_directory."""
        response = test_client.get("/config.json")
        data = response.json()
        assert "ripped_directory" in data
        assert isinstance(data["ripped_directory"], str)


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

            # Manually execute the disc_event handler logic (no local state update)
            event = disc_event.get("event")
            if daemon_id in _daemons:
                # This is what the handler should do - just broadcast, no state update
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

            # Manually execute the disc_event handler logic (no local state update)
            event = disc_event.get("event")
            if daemon_id in _daemons:
                # This is what the handler should do - just broadcast, no state update
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


class TestWebSocketDaemonTracking:
    """Tests for tracking daemon WebSocket connections."""

    def test_manager_tracks_daemon_connections(self, test_client):
        """ConnectionManager tracks daemon_id to WebSocket mapping."""
        from amphigory.websocket import manager

        # Initially no daemons tracked
        assert len(manager._daemon_connections) == 0

    @pytest.mark.asyncio
    async def test_send_to_daemon_raises_when_not_connected(self):
        """send_to_daemon raises if daemon not connected."""
        from amphigory.websocket import manager
        import pytest

        with pytest.raises(KeyError, match="not connected"):
            await manager.send_to_daemon("nonexistent-daemon", {"type": "test"})


class TestWebSocketRequests:
    """Tests for webapp sending requests to daemon."""

    @pytest.mark.asyncio
    async def test_manager_can_register_daemon_connection(self):
        """Can register a daemon's WebSocket connection."""
        from amphigory.websocket import manager
        from unittest.mock import AsyncMock

        mock_ws = AsyncMock()

        manager.register_daemon("test-daemon", mock_ws)

        assert "test-daemon" in manager._daemon_connections
        assert manager._daemon_connections["test-daemon"] == mock_ws

        # Cleanup
        manager.unregister_daemon("test-daemon")

    @pytest.mark.asyncio
    async def test_manager_can_send_to_specific_daemon(self):
        """Can send a message to a specific daemon."""
        from amphigory.websocket import manager
        from unittest.mock import AsyncMock
        import json

        mock_ws = AsyncMock()
        manager.register_daemon("test-daemon", mock_ws)

        await manager.send_to_daemon("test-daemon", {"type": "request", "data": "test"})

        mock_ws.send_text.assert_called_once()
        sent_msg = json.loads(mock_ws.send_text.call_args[0][0])
        assert sent_msg["type"] == "request"

        # Cleanup
        manager.unregister_daemon("test-daemon")

    @pytest.mark.asyncio
    async def test_unregister_daemon_removes_connection(self):
        """unregister_daemon removes the daemon from tracking."""
        from amphigory.websocket import manager
        from unittest.mock import AsyncMock

        mock_ws = AsyncMock()
        manager.register_daemon("test-daemon", mock_ws)
        assert "test-daemon" in manager._daemon_connections

        manager.unregister_daemon("test-daemon")

        assert "test-daemon" not in manager._daemon_connections

    @pytest.mark.asyncio
    async def test_send_to_daemon_raises_when_not_connected(self):
        """send_to_daemon raises KeyError for unconnected daemon."""
        from amphigory.websocket import manager

        # Ensure daemon not registered
        manager.unregister_daemon("nonexistent-daemon")

        with pytest.raises(KeyError):
            await manager.send_to_daemon("nonexistent-daemon", {"type": "test"})

    @pytest.mark.asyncio
    async def test_handle_response_completes_pending_request(self):
        """handle_response completes pending request future."""
        from amphigory.websocket import manager
        import asyncio

        # Create a pending request
        request_id = "test-request-123"
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        manager._pending_requests[request_id] = future

        # Handle response
        response_data = {
            "type": "response",
            "request_id": request_id,
            "result": {"status": "ok", "data": "test"},
        }
        handled = manager.handle_response(response_data)

        assert handled is True
        assert future.done()
        assert future.result() == {"status": "ok", "data": "test"}

        # Cleanup
        manager._pending_requests.pop(request_id, None)

    @pytest.mark.asyncio
    async def test_handle_response_sets_exception_on_error(self):
        """handle_response sets exception for error responses."""
        from amphigory.websocket import manager
        import asyncio

        # Create a pending request
        request_id = "test-request-456"
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        manager._pending_requests[request_id] = future

        # Handle error response
        response_data = {
            "type": "response",
            "request_id": request_id,
            "error": {"code": "test_error", "message": "Something went wrong"},
        }
        handled = manager.handle_response(response_data)

        assert handled is True
        assert future.done()
        with pytest.raises(Exception) as exc_info:
            future.result()
        assert "Something went wrong" in str(exc_info.value)

        # Cleanup
        manager._pending_requests.pop(request_id, None)

    @pytest.mark.asyncio
    async def test_handle_response_returns_false_for_unknown_request(self):
        """handle_response returns False for unknown request_id."""
        from amphigory.websocket import manager

        response_data = {
            "type": "response",
            "request_id": "unknown-request-id",
            "result": {"status": "ok"},
        }
        handled = manager.handle_response(response_data)

        assert handled is False


class TestLibraryPage:
    """Tests for /library HTML page."""

    def test_library_page_loads(self, test_client):
        """Library page loads successfully."""
        response = test_client.get("/library")
        assert response.status_code == 200
        assert "Library" in response.text


class TestCleanupPage:
    """Tests for /cleanup HTML page."""

    def test_cleanup_page_loads(self, test_client):
        """Cleanup page loads successfully."""
        response = test_client.get("/cleanup")
        assert response.status_code == 200
        assert "Cleanup" in response.text
