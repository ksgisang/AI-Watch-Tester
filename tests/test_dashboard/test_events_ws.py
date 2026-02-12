"""Tests for WebSocket EventHandler."""

from __future__ import annotations

import asyncio
from typing import Any

from aat.dashboard.events_ws import ConnectionManager, WebSocketEventHandler


class FakeWebSocket:
    """Minimal WebSocket mock for testing."""

    def __init__(self) -> None:
        self.accepted = False
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)


class TestConnectionManager:
    """ConnectionManager test suite."""

    async def test_connect_and_broadcast(self) -> None:
        mgr = ConnectionManager()
        ws = FakeWebSocket()
        await mgr.connect(ws)
        assert mgr.count == 1

        await mgr.broadcast({"type": "test"})
        assert len(ws.sent) == 1
        assert ws.sent[0]["type"] == "test"

    async def test_disconnect(self) -> None:
        mgr = ConnectionManager()
        ws = FakeWebSocket()
        await mgr.connect(ws)
        mgr.disconnect(ws)
        assert mgr.count == 0

    async def test_broadcast_removes_dead_connections(self) -> None:
        mgr = ConnectionManager()
        good_ws = FakeWebSocket()
        bad_ws = FakeWebSocket()

        async def fail_send(data: dict[str, Any]) -> None:
            msg = "connection closed"
            raise RuntimeError(msg)

        bad_ws.send_json = fail_send  # type: ignore[assignment]

        await mgr.connect(good_ws)
        await mgr.connect(bad_ws)
        assert mgr.count == 2

        await mgr.broadcast({"type": "test"})
        assert mgr.count == 1  # bad_ws removed
        assert len(good_ws.sent) == 1

    async def test_disconnect_nonexistent_is_safe(self) -> None:
        mgr = ConnectionManager()
        ws = FakeWebSocket()
        mgr.disconnect(ws)  # should not raise
        assert mgr.count == 0


class TestWebSocketEventHandler:
    """WebSocketEventHandler test suite."""

    async def test_prompt_async_and_resolve(self) -> None:
        mgr = ConnectionManager()
        ws = FakeWebSocket()
        await mgr.connect(ws)
        handler = WebSocketEventHandler(mgr)

        async def resolve_later() -> None:
            await asyncio.sleep(0.05)
            handler.resolve_prompt("approve")

        asyncio.create_task(resolve_later())
        result = await handler.prompt_async("Approve fix?", ["approve", "deny"])
        assert result == "approve"

    async def test_prompt_async_broadcasts(self) -> None:
        mgr = ConnectionManager()
        ws = FakeWebSocket()
        await mgr.connect(ws)
        handler = WebSocketEventHandler(mgr)

        async def resolve_later() -> None:
            await asyncio.sleep(0.05)
            handler.resolve_prompt("deny")

        asyncio.create_task(resolve_later())
        await handler.prompt_async("Test?")

        # Check that prompt was broadcast
        prompt_msgs = [m for m in ws.sent if m.get("type") == "prompt"]
        assert len(prompt_msgs) == 1
        assert prompt_msgs[0]["question"] == "Test?"

    async def test_send_screenshot(self) -> None:
        mgr = ConnectionManager()
        ws = FakeWebSocket()
        await mgr.connect(ws)
        handler = WebSocketEventHandler(mgr)

        # Create a minimal PNG image
        from io import BytesIO

        from PIL import Image

        img = Image.new("RGB", (100, 100), color="red")
        buf = BytesIO()
        img.save(buf, format="PNG")
        img_bytes = buf.getvalue()

        await handler.send_screenshot(img_bytes)

        ss_msgs = [m for m in ws.sent if m.get("type") == "screenshot"]
        assert len(ss_msgs) == 1
        assert "data" in ss_msgs[0]
        assert len(ss_msgs[0]["data"]) > 0  # base64 data

    def test_sync_methods_do_not_raise(self) -> None:
        """Sync methods should not raise even without event loop."""
        mgr = ConnectionManager()
        handler = WebSocketEventHandler(mgr)
        # These should not raise
        handler.info("test")
        handler.success("test")
        handler.warning("test")
        handler.error("test")
        handler.step_start(1, 5, "test")
        handler.step_result(1, True, "test")
        handler.progress("test", 1, 5)
        handler.section("test")
