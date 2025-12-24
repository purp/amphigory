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
