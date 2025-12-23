"""WebSocket server for Amphigory daemon communication with webapp."""

import asyncio
import json
from datetime import datetime
from typing import Any, Optional, Set

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

        if msg_type == "config_updated":
            # Signal to refetch config - handled by main app
            pass

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
