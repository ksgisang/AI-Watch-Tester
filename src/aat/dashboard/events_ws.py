"""WebSocket-based EventHandler for real-time dashboard updates."""

from __future__ import annotations

import asyncio
import base64
import json
from io import BytesIO
from typing import Any

from aat.core.events import EventEmitter

try:
    from fastapi import WebSocket  # type: ignore[import-not-found]  # noqa: TC002
    from PIL import Image
except ImportError as e:
    msg = "Dashboard requires 'web' extras: pip install aat-devqa[web]"
    raise ImportError(msg) from e


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Send JSON message to all connected clients."""
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_json(data)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def count(self) -> int:
        return len(self._connections)


class WebSocketEventHandler(EventEmitter):
    """EventEmitter that broadcasts events via WebSocket.

    Sends structured JSON messages to all connected dashboard clients.
    Supports async prompt for approval modal (AI fix approve/deny).
    """

    def __init__(self, manager: ConnectionManager) -> None:
        self._manager = manager
        self._prompt_event: asyncio.Event | None = None
        self._prompt_response: str = ""
        self._screenshot_size = (960, 540)
        self._jpeg_quality = 60

    def info(self, message: str) -> None:
        self._send_sync({"type": "info", "message": message})

    def success(self, message: str) -> None:
        self._send_sync({"type": "success", "message": message})

    def warning(self, message: str) -> None:
        self._send_sync({"type": "warning", "message": message})

    def error(self, message: str) -> None:
        self._send_sync({"type": "error", "message": message})

    def step_start(self, step_num: int, total: int, description: str) -> None:
        self._send_sync({
            "type": "step_start",
            "step": step_num,
            "total": total,
            "description": description,
        })

    def step_result(
        self,
        step_num: int,
        passed: bool,
        description: str,
        error: str | None = None,
    ) -> None:
        self._send_sync({
            "type": "step_result",
            "step": step_num,
            "passed": passed,
            "description": description,
            "error": error,
        })

    def progress(self, label: str, current: int, total: int) -> None:
        self._send_sync({
            "type": "progress",
            "label": label,
            "current": current,
            "total": total,
        })

    def section(self, title: str) -> None:
        self._send_sync({"type": "section", "message": title})

    def prompt(self, question: str, options: list[str] | None = None) -> str:
        """Synchronous prompt — returns empty string.

        Use prompt_async() from the dashboard app for real async prompts.
        """
        self._send_sync({
            "type": "prompt",
            "question": question,
            "options": options or [],
        })
        return ""

    async def prompt_async(
        self,
        question: str,
        options: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Async prompt that waits for user response via WebSocket.

        Used for approval modal in the dashboard.
        """
        self._prompt_event = asyncio.Event()
        self._prompt_response = ""

        await self._manager.broadcast({
            "type": "prompt",
            "question": question,
            "options": options or [],
            "context": context or {},
        })

        await self._prompt_event.wait()
        return self._prompt_response

    def resolve_prompt(self, response: str) -> None:
        """Resolve a pending prompt with user's response."""
        self._prompt_response = response
        if self._prompt_event:
            self._prompt_event.set()

    async def send_screenshot(self, image_data: bytes) -> None:
        """Send screenshot as base64 JPEG via WebSocket.

        Resizes to 960x540 and compresses to JPEG 60% quality.
        """
        img = Image.open(BytesIO(image_data))
        img = img.resize(self._screenshot_size, Image.Resampling.LANCZOS)  # type: ignore[assignment]

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=self._jpeg_quality)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        await self._manager.broadcast({
            "type": "screenshot",
            "data": b64,
        })

    def _send_sync(self, data: dict[str, Any]) -> None:
        """Fire-and-forget broadcast from synchronous methods."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._manager.broadcast(data))
        except RuntimeError:
            pass  # no event loop — skip (e.g. during testing)

    def to_json(self, data: dict[str, Any]) -> str:
        """Serialize event data to JSON string."""
        return json.dumps(data, ensure_ascii=False)
