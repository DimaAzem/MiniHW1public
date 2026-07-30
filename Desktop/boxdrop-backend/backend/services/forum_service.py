"""
WebSocket connection management for the real-time forum.

A single process-local ConnectionManager instance (module-level singleton,
same pattern as `mongo_manager`) tracks every currently-open forum
WebSocket and broadcasts new posts to all of them. This only works within a
single backend process/container - fine for this project's single-instance
deployment. Called out explicitly as a scaling limitation rather than
silently assumed away: a multi-instance deployment would need a pub/sub
layer (e.g. Redis) to fan broadcasts out across processes.
"""

import logging
from typing import Dict

from fastapi import WebSocket

logger = logging.getLogger("boxdrop.forum")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: Dict[str, WebSocket] = {}

    async def connect(self, connection_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[connection_id] = websocket

    def disconnect(self, connection_id: str) -> None:
        self._connections.pop(connection_id, None)

    async def broadcast(self, message: dict) -> None:
        """Sends `message` as JSON to every currently-connected client, dropping any that fail."""
        dead_connections = []
        for connection_id, websocket in self._connections.items():
            try:
                await websocket.send_json(message)
            except Exception:
                dead_connections.append(connection_id)
        for connection_id in dead_connections:
            self.disconnect(connection_id)

    @property
    def active_count(self) -> int:
        return len(self._connections)


# Module-level singleton, mirroring backend.database.connection.mongo_manager.
connection_manager = ConnectionManager()
