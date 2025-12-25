"""WebSocket connection management."""

from fastapi import WebSocket
from typing import Any, Optional
import json
import asyncio
import uuid


class ConnectionManager:
    """Manages WebSocket connections."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        # Map daemon_id to WebSocket for daemon connections
        self._daemon_connections: dict[str, WebSocket] = {}
        # Pending request responses: request_id -> Future
        self._pending_requests: dict[str, asyncio.Future] = {}

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    def register_daemon(self, daemon_id: str, websocket: WebSocket) -> None:
        """Register a daemon's WebSocket connection.

        Args:
            daemon_id: Unique identifier for the daemon
            websocket: The daemon's WebSocket connection
        """
        self._daemon_connections[daemon_id] = websocket

    def unregister_daemon(self, daemon_id: str) -> None:
        """Unregister a daemon's WebSocket connection.

        Args:
            daemon_id: Daemon identifier to unregister
        """
        self._daemon_connections.pop(daemon_id, None)

    async def send_to_daemon(self, daemon_id: str, message: dict[str, Any]) -> None:
        """Send a message to a specific daemon.

        Args:
            daemon_id: Target daemon identifier
            message: Message dict to send

        Raises:
            KeyError: If daemon is not connected
        """
        if daemon_id not in self._daemon_connections:
            raise KeyError(f"Daemon {daemon_id} not connected")

        websocket = self._daemon_connections[daemon_id]
        await websocket.send_text(json.dumps(message))

    async def request_from_daemon(
        self,
        daemon_id: str,
        method: str,
        params: dict[str, Any] = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Send a request to daemon and wait for response.

        Args:
            daemon_id: Target daemon identifier
            method: Request method name
            params: Request parameters
            timeout: Timeout in seconds

        Returns:
            Response result dict

        Raises:
            KeyError: If daemon not connected
            TimeoutError: If no response within timeout
            Exception: If daemon returns error
        """
        request_id = str(uuid.uuid4())

        request = {
            "type": "request",
            "request_id": request_id,
            "method": method,
            "params": params or {},
        }

        # Create future for response
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_requests[request_id] = future

        try:
            await self.send_to_daemon(daemon_id, request)
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        finally:
            self._pending_requests.pop(request_id, None)

    def handle_response(self, data: dict[str, Any]) -> bool:
        """Handle a response message from daemon.

        Args:
            data: Response message data

        Returns:
            True if response was handled, False if no pending request
        """
        if data.get("type") != "response":
            return False

        request_id = data.get("request_id")
        if not request_id or request_id not in self._pending_requests:
            return False

        future = self._pending_requests[request_id]

        if "error" in data:
            future.set_exception(Exception(data["error"].get("message", "Unknown error")))
        else:
            future.set_result(data.get("result", {}))

        return True

    async def broadcast(self, message: dict[str, Any]):
        """Send a message to all connected clients."""
        json_message = json.dumps(message)
        for connection in self.active_connections:
            try:
                await connection.send_text(json_message)
            except Exception:
                self.disconnect(connection)

    async def send_personal(self, websocket: WebSocket, message: dict[str, Any]):
        """Send a message to a specific client."""
        await websocket.send_text(json.dumps(message))


# Global connection manager
manager = ConnectionManager()
