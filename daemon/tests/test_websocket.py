"""Tests for WebSocket server - TDD: tests written first."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
import websockets


class TestWebSocketServer:
    @pytest.mark.asyncio
    async def test_server_starts_and_accepts_connection(self):
        """Server starts and accepts WebSocket connections."""
        from amphigory_daemon.websocket import WebSocketServer

        server = WebSocketServer(port=19847, heartbeat_interval=10)
        await server.start()

        try:
            async with websockets.connect("ws://localhost:19847") as ws:
                # Connection successful if we get here without exception
                assert ws is not None
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all_clients(self):
        """Broadcast sends message to all connected clients."""
        from amphigory_daemon.websocket import WebSocketServer

        server = WebSocketServer(port=19848, heartbeat_interval=10)
        await server.start()

        try:
            async with websockets.connect("ws://localhost:19848") as ws1:
                async with websockets.connect("ws://localhost:19848") as ws2:
                    # Give server time to register connections
                    await asyncio.sleep(0.1)

                    await server.broadcast({"type": "test", "data": "hello"})

                    # Both clients should receive the message
                    msg1 = await asyncio.wait_for(ws1.recv(), timeout=1.0)
                    msg2 = await asyncio.wait_for(ws2.recv(), timeout=1.0)

                    assert json.loads(msg1) == {"type": "test", "data": "hello"}
                    assert json.loads(msg2) == {"type": "test", "data": "hello"}
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_has_clients_returns_correct_state(self):
        """has_clients() returns True when clients connected."""
        from amphigory_daemon.websocket import WebSocketServer

        server = WebSocketServer(port=19849, heartbeat_interval=10)
        await server.start()

        try:
            assert not server.has_clients()

            async with websockets.connect("ws://localhost:19849"):
                await asyncio.sleep(0.1)
                assert server.has_clients()

            await asyncio.sleep(0.1)
            assert not server.has_clients()
        finally:
            await server.stop()


class TestWebSocketMessages:
    @pytest.mark.asyncio
    async def test_send_progress(self):
        """send_progress broadcasts progress update."""
        from amphigory_daemon.websocket import WebSocketServer

        server = WebSocketServer(port=19850, heartbeat_interval=10)
        await server.start()

        try:
            async with websockets.connect("ws://localhost:19850") as ws:
                await asyncio.sleep(0.1)

                await server.send_progress(
                    task_id="20251221-143052-001",
                    percent=47,
                    eta_seconds=412,
                    current_size_bytes=5356823040,
                    speed="42.3 MB/s",
                )

                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                data = json.loads(msg)

                assert data["type"] == "progress"
                assert data["task_id"] == "20251221-143052-001"
                assert data["percent"] == 47
                assert data["eta_seconds"] == 412
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_send_disc_event(self):
        """send_disc_event broadcasts disc inserted/ejected."""
        from amphigory_daemon.websocket import WebSocketServer

        server = WebSocketServer(port=19851, heartbeat_interval=10)
        await server.start()

        try:
            async with websockets.connect("ws://localhost:19851") as ws:
                await asyncio.sleep(0.1)

                await server.send_disc_event(
                    event="inserted",
                    device="/dev/rdisk4",
                    volume_name="THE_POLAR_EXPRESS",
                )

                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                data = json.loads(msg)

                assert data["type"] == "disc"
                assert data["event"] == "inserted"
                assert data["device"] == "/dev/rdisk4"
                assert data["volume_name"] == "THE_POLAR_EXPRESS"
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_send_fingerprint_event(self):
        """send_fingerprint_event broadcasts fingerprint generated event."""
        from amphigory_daemon.websocket import WebSocketServer

        server = WebSocketServer(port=19860, heartbeat_interval=10)
        await server.start()

        try:
            async with websockets.connect("ws://localhost:19860") as ws:
                await asyncio.sleep(0.1)

                await server.send_fingerprint_event(
                    fingerprint="abc123def456",
                    device="/dev/rdisk4",
                )

                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                data = json.loads(msg)

                assert data["type"] == "disc"
                assert data["event"] == "fingerprinted"
                assert data["fingerprint"] == "abc123def456"
                assert data["device"] == "/dev/rdisk4"
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_send_heartbeat(self):
        """send_heartbeat broadcasts daemon status."""
        from amphigory_daemon.websocket import WebSocketServer

        server = WebSocketServer(port=19852, heartbeat_interval=10)
        await server.start()

        try:
            async with websockets.connect("ws://localhost:19852") as ws:
                await asyncio.sleep(0.1)

                await server.send_heartbeat(
                    queue_depth=3,
                    current_task="20251221-143052-001",
                    paused=False,
                )

                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                data = json.loads(msg)

                assert data["type"] == "heartbeat"
                assert data["queue_depth"] == 3
                assert data["current_task"] == "20251221-143052-001"
                assert data["paused"] is False
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_send_sync(self):
        """send_sync broadcasts full state on reconnect."""
        from amphigory_daemon.websocket import WebSocketServer

        server = WebSocketServer(port=19853, heartbeat_interval=10)
        await server.start()

        try:
            async with websockets.connect("ws://localhost:19853") as ws:
                await asyncio.sleep(0.1)

                state = {
                    "disc": {
                        "inserted": True,
                        "device": "/dev/rdisk4",
                        "volume_name": "THE_POLAR_EXPRESS",
                    },
                    "current_task": {
                        "id": "20251221-143052-001",
                        "percent": 47,
                    },
                    "paused": False,
                    "queue_depth": 3,
                }

                await server.send_sync(state)

                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                data = json.loads(msg)

                assert data["type"] == "sync"
                assert data["disc"]["inserted"] is True
                assert data["queue_depth"] == 3
        finally:
            await server.stop()


class TestWebSocketConfigSync:
    """Tests for daemon/webapp config synchronization."""

    @pytest.mark.asyncio
    async def test_send_daemon_config(self):
        """send_daemon_config broadcasts daemon configuration."""
        from amphigory_daemon.websocket import WebSocketServer

        server = WebSocketServer(port=19854, heartbeat_interval=10)
        await server.start()

        try:
            async with websockets.connect("ws://localhost:19854") as ws:
                await asyncio.sleep(0.1)

                await server.send_daemon_config(
                    daemon_id="purp@beehive",
                    makemkvcon_path="/usr/local/bin/makemkvcon",
                    webapp_basedir="/opt/amphigory",
                )

                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                data = json.loads(msg)

                assert data["type"] == "daemon_config"
                assert data["daemon_id"] == "purp@beehive"
                assert data["makemkvcon_path"] == "/usr/local/bin/makemkvcon"
                assert data["webapp_basedir"] == "/opt/amphigory"
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_on_config_change_callback(self):
        """Server calls on_config_change when webapp_config_changed received."""
        from amphigory_daemon.websocket import WebSocketServer

        callback = AsyncMock()
        server = WebSocketServer(port=19855, heartbeat_interval=10)
        server.on_config_change = callback
        await server.start()

        try:
            async with websockets.connect("ws://localhost:19855") as ws:
                await asyncio.sleep(0.1)

                # Send config change message from "webapp"
                await ws.send(json.dumps({
                    "type": "webapp_config_changed",
                }))

                # Give server time to process
                await asyncio.sleep(0.1)

                callback.assert_called_once()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_on_config_change_not_called_for_other_messages(self):
        """on_config_change not called for non-config messages."""
        from amphigory_daemon.websocket import WebSocketServer

        callback = AsyncMock()
        server = WebSocketServer(port=19856, heartbeat_interval=10)
        server.on_config_change = callback
        await server.start()

        try:
            async with websockets.connect("ws://localhost:19856") as ws:
                await asyncio.sleep(0.1)

                # Send a different message type
                await ws.send(json.dumps({
                    "type": "some_other_message",
                }))

                await asyncio.sleep(0.1)

                callback.assert_not_called()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_send_daemon_config_includes_timestamp(self):
        """send_daemon_config includes timestamp."""
        from amphigory_daemon.websocket import WebSocketServer

        server = WebSocketServer(port=19857, heartbeat_interval=10)
        await server.start()

        try:
            async with websockets.connect("ws://localhost:19857") as ws:
                await asyncio.sleep(0.1)

                await server.send_daemon_config(
                    daemon_id="purp@beehive",
                    makemkvcon_path="/usr/local/bin/makemkvcon",
                    webapp_basedir="/opt/amphigory",
                )

                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                data = json.loads(msg)

                assert "timestamp" in data
        finally:
            await server.stop()


class TestWebAppClient:
    """Tests for WebSocket client connecting to webapp."""

    @pytest.mark.asyncio
    async def test_client_connects_to_webapp(self):
        """WebAppClient connects to webapp WebSocket endpoint."""
        from amphigory_daemon.websocket import WebAppClient

        # Start a mock WebSocket server to simulate webapp
        received_messages = []

        async def handler(websocket):
            async for message in websocket:
                received_messages.append(json.loads(message))

        async with websockets.serve(handler, "localhost", 19850):
            client = WebAppClient("ws://localhost:19850")
            await client.connect()

            try:
                assert client.is_connected()
            finally:
                await client.disconnect()

    @pytest.mark.asyncio
    async def test_client_sends_daemon_config_on_connect(self):
        """WebAppClient sends daemon_config message on connect."""
        from amphigory_daemon.websocket import WebAppClient

        received_messages = []

        async def handler(websocket):
            async for message in websocket:
                received_messages.append(json.loads(message))

        async with websockets.serve(handler, "localhost", 19851):
            client = WebAppClient("ws://localhost:19851")
            await client.connect()
            await client.send_daemon_config(
                daemon_id="testuser@testhost",
                makemkvcon_path="/usr/local/bin/makemkvcon",
                webapp_basedir="/data",
            )

            # Give time for message to be received
            await asyncio.sleep(0.1)

            try:
                assert len(received_messages) == 1
                msg = received_messages[0]
                assert msg["type"] == "daemon_config"
                assert msg["daemon_id"] == "testuser@testhost"
                assert msg["makemkvcon_path"] == "/usr/local/bin/makemkvcon"
            finally:
                await client.disconnect()

    @pytest.mark.asyncio
    async def test_client_sends_heartbeat(self):
        """WebAppClient can send heartbeat messages."""
        from amphigory_daemon.websocket import WebAppClient

        received_messages = []

        async def handler(websocket):
            async for message in websocket:
                received_messages.append(json.loads(message))

        async with websockets.serve(handler, "localhost", 19852):
            client = WebAppClient("ws://localhost:19852")
            await client.connect()
            await client.send_heartbeat()

            await asyncio.sleep(0.1)

            try:
                assert len(received_messages) == 1
                assert received_messages[0]["type"] == "heartbeat"
            finally:
                await client.disconnect()

    @pytest.mark.asyncio
    async def test_client_handles_disconnect(self):
        """WebAppClient handles server disconnect gracefully."""
        from amphigory_daemon.websocket import WebAppClient

        server_should_close = asyncio.Event()

        async def handler(websocket):
            await server_should_close.wait()
            await websocket.close()

        async with websockets.serve(handler, "localhost", 19853):
            client = WebAppClient("ws://localhost:19853")
            await client.connect()

            assert client.is_connected()

            # Trigger server close
            server_should_close.set()
            await asyncio.sleep(0.2)

            # Client should detect disconnection
            assert not client.is_connected()


class TestHeartbeatLoop:
    """Tests for the heartbeat loop functionality."""

    @pytest.mark.asyncio
    async def test_start_heartbeat_loop_sends_periodic_heartbeats(self):
        """start_heartbeat_loop sends heartbeats at configured interval."""
        from amphigory_daemon.websocket import WebAppClient

        received_messages = []

        async def handler(websocket):
            async for message in websocket:
                received_messages.append(json.loads(message))

        async with websockets.serve(handler, "localhost", 19860):
            client = WebAppClient("ws://localhost:19860")
            await client.connect()

            # Start heartbeat with 0.1 second interval
            loop_task = asyncio.create_task(client.start_heartbeat_loop(0.1))

            # Wait long enough for 2-3 heartbeats
            await asyncio.sleep(0.35)

            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass

            await client.disconnect()

        # Should have received at least 2 heartbeats
        heartbeats = [m for m in received_messages if m.get("type") == "heartbeat"]
        assert len(heartbeats) >= 2

    @pytest.mark.asyncio
    async def test_heartbeat_loop_stops_on_disconnect(self):
        """Heartbeat loop stops gracefully when disconnected."""
        from amphigory_daemon.websocket import WebAppClient

        server_should_close = asyncio.Event()
        received_count = 0

        async def handler(websocket):
            nonlocal received_count
            try:
                async for message in websocket:
                    received_count += 1
                    if received_count >= 2:
                        server_should_close.set()
                        await asyncio.sleep(0.1)
                        await websocket.close()
                        break
            except websockets.exceptions.ConnectionClosed:
                pass

        async with websockets.serve(handler, "localhost", 19861):
            client = WebAppClient("ws://localhost:19861")
            await client.connect()

            # Start heartbeat loop
            loop_task = asyncio.create_task(client.start_heartbeat_loop(0.05))

            # Wait for server to close connection
            await server_should_close.wait()
            await asyncio.sleep(0.3)

            # Loop should have exited (not hang indefinitely)
            assert loop_task.done() or loop_task.cancelled()

    @pytest.mark.asyncio
    async def test_heartbeat_loop_is_cancellable(self):
        """Heartbeat loop can be cancelled cleanly."""
        from amphigory_daemon.websocket import WebAppClient

        async def handler(websocket):
            async for message in websocket:
                pass

        async with websockets.serve(handler, "localhost", 19862):
            client = WebAppClient("ws://localhost:19862")
            await client.connect()

            loop_task = asyncio.create_task(client.start_heartbeat_loop(1.0))

            # Cancel almost immediately
            await asyncio.sleep(0.05)
            loop_task.cancel()

            # Should not raise
            try:
                await loop_task
            except asyncio.CancelledError:
                pass

            await client.disconnect()

        # Test passes if no exception raised


class TestWebAppClientRequestHandling:
    """Tests for handling requests from webapp."""

    @pytest.mark.asyncio
    async def test_registers_request_handler(self):
        """Can register a handler for incoming requests."""
        from amphigory_daemon.websocket import WebAppClient

        client = WebAppClient("ws://localhost:8000/ws")

        handler = AsyncMock(return_value={"status": "ok"})
        client.on_request("get_drive_status", handler)

        assert "get_drive_status" in client._request_handlers

    @pytest.mark.asyncio
    async def test_handles_request_and_sends_response(self):
        """Handles request message and sends response."""
        from amphigory_daemon.websocket import WebAppClient

        client = WebAppClient("ws://localhost:8000/ws")
        client._websocket = AsyncMock()
        client._connected = True

        # Register handler
        async def handle_get_status(params):
            return {"drive_id": "test:rdisk0", "state": "empty"}

        client.on_request("get_drive_status", handle_get_status)

        # Simulate incoming request
        request = {
            "type": "request",
            "request_id": "req-123",
            "method": "get_drive_status",
            "params": {},
        }

        await client._handle_message(request)

        # Verify response was sent
        client._websocket.send.assert_called_once()
        response = json.loads(client._websocket.send.call_args[0][0])
        assert response["type"] == "response"
        assert response["request_id"] == "req-123"
        assert response["result"]["drive_id"] == "test:rdisk0"

    @pytest.mark.asyncio
    async def test_handles_unknown_method(self):
        """Sends error response for unknown method."""
        from amphigory_daemon.websocket import WebAppClient

        client = WebAppClient("ws://localhost:8000/ws")
        client._websocket = AsyncMock()
        client._connected = True

        request = {
            "type": "request",
            "request_id": "req-456",
            "method": "unknown_method",
            "params": {},
        }

        await client._handle_message(request)

        # Verify error response was sent
        client._websocket.send.assert_called_once()
        response = json.loads(client._websocket.send.call_args[0][0])
        assert response["type"] == "response"
        assert response["request_id"] == "req-456"
        assert "error" in response

    @pytest.mark.asyncio
    async def test_handles_handler_exception(self):
        """Sends error response if handler raises exception."""
        from amphigory_daemon.websocket import WebAppClient

        client = WebAppClient("ws://localhost:8000/ws")
        client._websocket = AsyncMock()
        client._connected = True

        async def bad_handler(params):
            raise ValueError("Something went wrong")

        client.on_request("bad_method", bad_handler)

        request = {
            "type": "request",
            "request_id": "req-789",
            "method": "bad_method",
            "params": {},
        }

        await client._handle_message(request)

        # Verify error response was sent
        response = json.loads(client._websocket.send.call_args[0][0])
        assert response["type"] == "response"
        assert response["request_id"] == "req-789"
        assert "error" in response
        assert "Something went wrong" in response["error"]["message"]
