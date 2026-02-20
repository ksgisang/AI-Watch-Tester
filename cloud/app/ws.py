"""WebSocket connection manager for per-test live progress."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSManager:
    """Manage WebSocket connections per test_id."""

    def __init__(self) -> None:
        self._connections: dict[int, list[WebSocket]] = defaultdict(list)

    async def connect(self, test_id: int, ws: WebSocket) -> None:
        await ws.accept()
        self._connections[test_id].append(ws)
        logger.debug(
            "WS connected: test_id=%d (total=%d)", test_id, len(self._connections[test_id])
        )

    def disconnect(self, test_id: int, ws: WebSocket) -> None:
        conns = self._connections.get(test_id)
        if conns and ws in conns:
            conns.remove(ws)
            if not conns:
                del self._connections[test_id]

    async def broadcast(self, test_id: int, data: dict[str, Any]) -> None:
        """Send JSON event to all WebSocket clients watching a test."""
        conns = self._connections.get(test_id)
        if not conns:
            return

        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(test_id, ws)


ws_manager = WSManager()
