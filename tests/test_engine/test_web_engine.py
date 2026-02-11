"""Tests for WebEngine — Playwright-based web test engine.

Uses mock-based unit tests to avoid requiring an actual browser.
Integration tests with real Playwright are in tests/integration/.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003
from unittest.mock import AsyncMock, MagicMock

import pytest

from aat.core.exceptions import EngineError
from aat.core.models import EngineConfig
from aat.engine.web import WebEngine


class TestWebEngineInit:
    def test_default_config(self) -> None:
        engine = WebEngine()
        assert engine._config.browser == "chromium"
        assert engine._config.headless is False
        assert engine._page is None

    def test_custom_config(self) -> None:
        config = EngineConfig(browser="firefox", headless=True, viewport_width=1920)
        engine = WebEngine(config)
        assert engine._config.browser == "firefox"
        assert engine._config.headless is True
        assert engine._config.viewport_width == 1920

    def test_page_property_raises_before_start(self) -> None:
        engine = WebEngine()
        with pytest.raises(EngineError, match="not started"):
            _ = engine.page

    def test_mouse_position_default(self) -> None:
        engine = WebEngine()
        assert engine.mouse_position == (0, 0)

    def test_is_base_engine(self) -> None:
        from aat.engine.base import BaseEngine

        assert issubclass(WebEngine, BaseEngine)


class TestWebEngineActions:
    """Test engine actions with a mock Playwright page."""

    @pytest.fixture
    def engine_with_mock_page(self) -> WebEngine:
        engine = WebEngine()
        mock_page = MagicMock()
        mock_page.mouse = MagicMock()
        mock_page.mouse.click = AsyncMock()
        mock_page.mouse.dblclick = AsyncMock()
        mock_page.mouse.move = AsyncMock()
        mock_page.mouse.wheel = AsyncMock()
        mock_page.keyboard = MagicMock()
        mock_page.keyboard.type = AsyncMock()
        mock_page.keyboard.press = AsyncMock()
        mock_page.screenshot = AsyncMock(return_value=b"png_data")
        mock_page.goto = AsyncMock()
        mock_page.go_back = AsyncMock()
        mock_page.reload = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="Page text")
        mock_page.url = "https://example.com/page"
        engine._page = mock_page
        return engine

    @pytest.mark.asyncio
    async def test_click(self, engine_with_mock_page: WebEngine) -> None:
        engine = engine_with_mock_page
        await engine.click(100, 200)
        engine.page.mouse.click.assert_awaited_once_with(100, 200)
        assert engine.mouse_position == (100, 200)

    @pytest.mark.asyncio
    async def test_double_click(self, engine_with_mock_page: WebEngine) -> None:
        engine = engine_with_mock_page
        await engine.double_click(50, 75)
        engine.page.mouse.dblclick.assert_awaited_once_with(50, 75)
        assert engine.mouse_position == (50, 75)

    @pytest.mark.asyncio
    async def test_right_click(self, engine_with_mock_page: WebEngine) -> None:
        engine = engine_with_mock_page
        await engine.right_click(10, 20)
        engine.page.mouse.click.assert_awaited_once_with(10, 20, button="right")

    @pytest.mark.asyncio
    async def test_type_text(self, engine_with_mock_page: WebEngine) -> None:
        engine = engine_with_mock_page
        await engine.type_text("hello")
        engine.page.keyboard.type.assert_awaited_once_with("hello")

    @pytest.mark.asyncio
    async def test_press_key(self, engine_with_mock_page: WebEngine) -> None:
        engine = engine_with_mock_page
        await engine.press_key("Enter")
        engine.page.keyboard.press.assert_awaited_once_with("Enter")

    @pytest.mark.asyncio
    async def test_key_combo(self, engine_with_mock_page: WebEngine) -> None:
        engine = engine_with_mock_page
        await engine.key_combo("Control", "a")
        engine.page.keyboard.press.assert_awaited_once_with("Control+a")

    @pytest.mark.asyncio
    async def test_navigate(self, engine_with_mock_page: WebEngine) -> None:
        engine = engine_with_mock_page
        await engine.navigate("https://test.com")
        engine.page.goto.assert_awaited_once_with(
            "https://test.com", wait_until="domcontentloaded"
        )

    @pytest.mark.asyncio
    async def test_go_back(self, engine_with_mock_page: WebEngine) -> None:
        engine = engine_with_mock_page
        await engine.go_back()
        engine.page.go_back.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_refresh(self, engine_with_mock_page: WebEngine) -> None:
        engine = engine_with_mock_page
        await engine.refresh()
        engine.page.reload.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_screenshot(self, engine_with_mock_page: WebEngine) -> None:
        engine = engine_with_mock_page
        data = await engine.screenshot()
        assert data == b"png_data"
        engine.page.screenshot.assert_awaited_once_with(type="png", full_page=False)

    @pytest.mark.asyncio
    async def test_scroll(self, engine_with_mock_page: WebEngine) -> None:
        engine = engine_with_mock_page
        await engine.scroll(100, 200, 300)
        engine.page.mouse.move.assert_awaited_once_with(100, 200)
        engine.page.mouse.wheel.assert_awaited_once_with(0, 300)

    @pytest.mark.asyncio
    async def test_move_mouse(self, engine_with_mock_page: WebEngine) -> None:
        engine = engine_with_mock_page
        await engine.move_mouse(50, 60)
        engine.page.mouse.move.assert_awaited_once_with(50, 60)
        assert engine.mouse_position == (50, 60)

    @pytest.mark.asyncio
    async def test_get_url(self, engine_with_mock_page: WebEngine) -> None:
        engine = engine_with_mock_page
        url = await engine.get_url()
        assert url == "https://example.com/page"

    @pytest.mark.asyncio
    async def test_get_page_text(self, engine_with_mock_page: WebEngine) -> None:
        engine = engine_with_mock_page
        text = await engine.get_page_text()
        assert text == "Page text"

    @pytest.mark.asyncio
    async def test_save_screenshot(self, engine_with_mock_page: WebEngine, tmp_path: Path) -> None:
        engine = engine_with_mock_page
        out = tmp_path / "shots" / "test.png"
        result = await engine.save_screenshot(out)
        assert result == out
        assert out.parent.exists()

    @pytest.mark.asyncio
    async def test_navigate_failure_raises_engine_error(
        self, engine_with_mock_page: WebEngine
    ) -> None:
        engine = engine_with_mock_page
        engine.page.goto.side_effect = Exception("Network error")
        with pytest.raises(EngineError, match="Navigation.*failed"):
            await engine.navigate("https://fail.com")


class TestWebEngineRegistry:
    def test_registered(self) -> None:
        from aat.engine import ENGINE_REGISTRY

        assert "web" in ENGINE_REGISTRY
        assert ENGINE_REGISTRY["web"] is WebEngine
