"""Tests for Waiter — screen stabilization detection."""

from __future__ import annotations

import pytest

from aat.engine.waiter import Waiter


class MockEngine:
    """Mock engine that returns configurable screenshots."""

    def __init__(self, screenshots: list[bytes]) -> None:
        self._screenshots = screenshots
        self._index = 0

    async def screenshot(self) -> bytes:
        if self._index < len(self._screenshots):
            data = self._screenshots[self._index]
            self._index += 1
            return data
        return self._screenshots[-1]


class TestWaiter:
    @pytest.mark.asyncio
    async def test_stable_immediately(self) -> None:
        """Same screenshot from the start → stable after stable_count polls."""
        same = b"same_screenshot_data"
        engine = MockEngine([same, same, same])
        waiter = Waiter(poll_interval_ms=10, stable_count=2, max_wait_ms=5000)
        result = await waiter.wait_until_stable(engine)
        assert result is True

    @pytest.mark.asyncio
    async def test_stable_after_change(self) -> None:
        """Screen changes then stabilizes."""
        engine = MockEngine([b"frame1", b"frame2", b"frame3", b"frame3", b"frame3"])
        waiter = Waiter(poll_interval_ms=10, stable_count=2, max_wait_ms=5000)
        result = await waiter.wait_until_stable(engine)
        assert result is True

    @pytest.mark.asyncio
    async def test_never_stable(self) -> None:
        """Screen keeps changing → returns False after max_wait."""
        frames = [f"frame{i}".encode() for i in range(100)]
        engine = MockEngine(frames)
        waiter = Waiter(poll_interval_ms=10, stable_count=2, max_wait_ms=50)
        result = await waiter.wait_until_stable(engine)
        assert result is False

    @pytest.mark.asyncio
    async def test_default_params(self) -> None:
        waiter = Waiter()
        assert waiter._poll_interval == 0.5
        assert waiter._stable_count == 2
        assert waiter._max_wait == 10.0

    @pytest.mark.asyncio
    async def test_custom_stable_count(self) -> None:
        """Requires 3 consecutive matches."""
        same = b"stable"
        engine = MockEngine([b"changing", same, same, same, same])
        waiter = Waiter(poll_interval_ms=10, stable_count=3, max_wait_ms=5000)
        result = await waiter.wait_until_stable(engine)
        assert result is True
