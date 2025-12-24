"""WebSocket server for Amphigory daemon communication with webapp."""

import asyncio
import json
from datetime import datetime
from typing import Any, Callable, Optional, Set

import websockets
from websockets.server import WebSocketServerProtocol, serve


class WebSocketServer:
    """
    WebSocket server for daemon-to-webapp communication.

    The daemon runs this server, and the webapp connects to it.
    Used for real-time progress updates, disc events, and heartbeats.
    """

    def __init__(self, port: int, heartbeat_interval: int):
        """
        Initialize WebSocket server.

        Args:
            port: Port to listen on
            heartbeat_interval: Seconds between heartbeat messages
        """
        self.port = port
        self.heartbeat_interval = heartbeat_interval
        self.clients: Set[WebSocketServerProtocol] = set()
        self._server = None
        # Callback for when webapp config changes
        self.on_config_change: Optional[Callable[[], Any]] = None

    async def start(self) -> None:
        """Start WebSocket server."""
        self._server = await serve(
            self._handle_connection,
            "localhost",
            self.port,
        )

    async def stop(self) -> None:
        """Stop WebSocket server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_connection(
        self,
        websocket: WebSocketServerProtocol,
    ) -> None:
        """Handle a new WebSocket connection."""
        self.clients.add(websocket)
        try:
            # Keep connection open, handle incoming messages
            async for message in websocket:
                # Process incoming messages (e.g., config_updated)
                try:
                    data = json.loads(message)
                    await self._handle_message(websocket, data)
                except json.JSONDecodeError:
                    pass
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)

    async def _handle_message(
        self,
        websocket: WebSocketServerProtocol,
        data: dict[str, Any],
    ) -> None:
        """Handle an incoming message from webapp."""
        msg_type = data.get("type")

        if msg_type == "webapp_config_changed":
            # Signal to refetch config from webapp
            if self.on_config_change is not None:
                result = self.on_config_change()
                # Handle both sync and async callbacks
                if asyncio.iscoroutine(result):
                    await result

    async def broadcast(self, message: dict[str, Any]) -> None:
        """
        Send message to all connected clients.

        Args:
            message: Dict to send as JSON
        """
        if not self.clients:
            return

        msg_json = json.dumps(message)
        await asyncio.gather(
            *[client.send(msg_json) for client in self.clients],
            return_exceptions=True,
        )

    def has_clients(self) -> bool:
        """Check if any clients are connected."""
        return len(self.clients) > 0

    async def send_progress(
        self,
        task_id: str,
        percent: int,
        eta_seconds: Optional[int],
        current_size_bytes: Optional[int],
        speed: Optional[str],
    ) -> None:
        """
        Send progress update.

        Args:
            task_id: ID of task being processed
            percent: Progress percentage (0-100)
            eta_seconds: Estimated seconds remaining
            current_size_bytes: Current bytes processed
            speed: Human-readable speed string
        """
        await self.broadcast({
            "type": "progress",
            "task_id": task_id,
            "percent": percent,
            "eta_seconds": eta_seconds,
            "current_size_bytes": current_size_bytes,
            "speed": speed,
        })

    async def send_disc_event(
        self,
        event: str,
        device: str,
        volume_name: Optional[str] = None,
    ) -> None:
        """
        Send disc inserted/ejected event.

        Args:
            event: "inserted" or "ejected"
            device: Device path (e.g., "/dev/rdisk4")
            volume_name: Volume name for inserted disc
        """
        message = {
            "type": "disc",
            "event": event,
            "device": device,
        }
        if volume_name is not None:
            message["volume_name"] = volume_name

        await self.broadcast(message)

    async def send_heartbeat(
        self,
        queue_depth: int,
        current_task: Optional[str],
        paused: bool,
    ) -> None:
        """
        Send periodic heartbeat.

        Args:
            queue_depth: Number of tasks in queue
            current_task: ID of currently processing task
            paused: Whether daemon is paused
        """
        await self.broadcast({
            "type": "heartbeat",
            "timestamp": datetime.now().isoformat(),
            "queue_depth": queue_depth,
            "current_task": current_task,
            "paused": paused,
        })

    async def send_sync(self, state: dict[str, Any]) -> None:
        """
        Send full state sync on reconnect.

        Args:
            state: Complete daemon state dict
        """
        message = {
            "type": "sync",
            "timestamp": datetime.now().isoformat(),
            **state,
        }
        await self.broadcast(message)

    async def send_status(self, task_id: str, status: str) -> None:
        """
        Send task status change.

        Args:
            task_id: ID of task
            status: New status ("started", "completed")
        """
        await self.broadcast({
            "type": "status",
            "task_id": task_id,
            "status": status,
        })

    async def send_daemon_config(
        self,
        daemon_id: str,
        makemkvcon_path: Optional[str],
        webapp_basedir: str,
    ) -> None:
        """
        Send daemon configuration to webapp.

        Called on connection and when daemon config changes.

        Args:
            daemon_id: Unique daemon identifier (e.g., "purp@beehive")
            makemkvcon_path: Path to makemkvcon binary
            webapp_basedir: Local path to webapp data directory
        """
        await self.broadcast({
            "type": "daemon_config",
            "timestamp": datetime.now().isoformat(),
            "daemon_id": daemon_id,
            "makemkvcon_path": makemkvcon_path,
            "webapp_basedir": webapp_basedir,
        })


class WebAppClient:
    """WebSocket client for connecting to the webapp."""

    def __init__(self, url: str):
        """
        Initialize WebSocket client.

        Args:
            url: WebSocket URL to connect to (e.g., ws://localhost:8000/ws)
        """
        self.url = url
        self._websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._receive_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        """Connect to the webapp WebSocket endpoint."""
        self._websocket = await websockets.connect(self.url)
        self._connected = True
        # Start background task to detect disconnection
        self._receive_task = asyncio.create_task(self._receive_loop())

    async def _receive_loop(self) -> None:
        """Background loop to receive messages and detect disconnection."""
        try:
            async for message in self._websocket:
                # Could handle incoming messages here if needed
                pass
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._connected = False

    async def disconnect(self) -> None:
        """Disconnect from the webapp."""
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self._websocket:
            await self._websocket.close()
        self._connected = False

    def is_connected(self) -> bool:
        """Check if client is connected."""
        return self._connected and self._websocket is not None

    async def _send(self, message: dict) -> None:
        """Send a JSON message to the webapp."""
        if self._websocket and self._connected:
            await self._websocket.send(json.dumps(message))

    async def send_daemon_config(
        self,
        daemon_id: str,
        makemkvcon_path: Optional[str],
        webapp_basedir: str,
    ) -> None:
        """
        Send daemon configuration to the webapp.

        Args:
            daemon_id: Unique daemon identifier
            makemkvcon_path: Path to makemkvcon binary
            webapp_basedir: Local path to webapp data directory
        """
        await self._send({
            "type": "daemon_config",
            "timestamp": datetime.now().isoformat(),
            "daemon_id": daemon_id,
            "makemkvcon_path": makemkvcon_path,
            "webapp_basedir": webapp_basedir,
        })

    async def send_heartbeat(self) -> None:
        """Send heartbeat to the webapp."""
        await self._send({
            "type": "heartbeat",
            "timestamp": datetime.now().isoformat(),
        })

    async def start_heartbeat_loop(self, interval: float) -> None:
        """
        Run a heartbeat loop that sends periodic heartbeats.

        Args:
            interval: Seconds between heartbeats

        This method runs until:
        - The connection is lost
        - The task is cancelled
        """
        try:
            while self.is_connected():
                await self.send_heartbeat()
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Connection lost or other error - exit loop
            pass
