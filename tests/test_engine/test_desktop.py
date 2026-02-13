"""Tests for DesktopEngine — PyAutoGUI + Playwright hybrid engine.

Uses mock-based unit tests. PyAutoGUI calls are mocked to avoid
requiring a real display.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from aat.core.exceptions import EngineError
from aat.core.models import EngineConfig
from aat.engine.desktop import DesktopEngine

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def mock_pag() -> MagicMock:
    """Create a mock pyautogui module."""
    pag = MagicMock()
    pag.position.return_value = MagicMock(x=0, y=0)
    return pag


class TestDesktopEngineInit:
    def test_default_config(self) -> None:
        engine = DesktopEngine()
        assert engine._config.browser == "chromium"
        assert engine._page is None

    def test_custom_config(self) -> None:
        config = EngineConfig(browser="firefox", viewport_width=1920)
        engine = DesktopEngine(config)
        assert engine._config.browser == "firefox"
        assert engine._config.viewport_width == 1920

    def test_page_property_raises_before_start(self) -> None:
        engine = DesktopEngine()
        with pytest.raises(EngineError, match="not started"):
            _ = engine.page

    def test_is_base_engine(self) -> None:
        from aat.engine.base import BaseEngine

        assert issubclass(DesktopEngine, BaseEngine)


class TestDesktopEngineMousePosition:
    def test_mouse_position_returns_viewport_coords(self) -> None:
        engine = DesktopEngine()
        assert engine.mouse_position == (0, 0)
        engine._mouse_x, engine._mouse_y = 150, 250
        assert engine.mouse_position == (150, 250)


class TestDesktopEngineActions:
    """Test engine actions with mocked PyAutoGUI and Playwright."""

    @pytest.fixture
    def engine_with_mocks(self, mock_pag: MagicMock) -> DesktopEngine:
        """Create a DesktopEngine with mock Playwright page and pyautogui."""
        engine = DesktopEngine()
        engine._pag = mock_pag
        mock_page = MagicMock()
        mock_page.goto = AsyncMock()
        mock_page.go_back = AsyncMock()
        mock_page.reload = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="Page text")
        mock_page.url = "https://example.com/page"
        mock_page.evaluate = AsyncMock(return_value={
            "screenX": 0, "screenY": 0,
            "chromeWidth": 0, "chromeHeight": 0,
            "devicePixelRatio": 1.0,
        })
        # Playwright mouse/keyboard mocks
        mock_page.mouse = MagicMock()
        mock_page.mouse.click = AsyncMock()
        mock_page.mouse.dblclick = AsyncMock()
        mock_page.keyboard = MagicMock()
        mock_page.keyboard.type = AsyncMock()
        mock_page.keyboard.press = AsyncMock()
        engine._page = mock_page
        return engine

    # -- Clicks (Playwright) --

    async def test_click(self, engine_with_mocks: DesktopEngine) -> None:
        await engine_with_mocks.click(100, 200)
        engine_with_mocks.page.mouse.click.assert_awaited_once_with(100, 200)

    async def test_double_click(self, engine_with_mocks: DesktopEngine) -> None:
        await engine_with_mocks.double_click(50, 75)
        engine_with_mocks.page.mouse.dblclick.assert_awaited_once_with(50, 75)

    async def test_right_click(self, engine_with_mocks: DesktopEngine) -> None:
        await engine_with_mocks.right_click(10, 20)
        engine_with_mocks.page.mouse.click.assert_awaited_once_with(
            10, 20, button="right",
        )

    # -- Mouse movement (PyAutoGUI) --

    async def test_move_mouse(
        self, engine_with_mocks: DesktopEngine, mock_pag: MagicMock,
    ) -> None:
        await engine_with_mocks.move_mouse(300, 400)
        mock_pag.moveTo.assert_called_once_with(300, 400)

    async def test_scroll(
        self, engine_with_mocks: DesktopEngine, mock_pag: MagicMock,
    ) -> None:
        await engine_with_mocks.scroll(100, 200, 300)
        mock_pag.moveTo.assert_called_once_with(100, 200)
        mock_pag.scroll.assert_called_once_with(-300)

    # -- Keyboard (Playwright) --

    async def test_type_text(self, engine_with_mocks: DesktopEngine) -> None:
        await engine_with_mocks.type_text("hello")
        engine_with_mocks.page.keyboard.type.assert_awaited_once_with(
            "hello", delay=0,
        )

    async def test_press_key(self, engine_with_mocks: DesktopEngine) -> None:
        await engine_with_mocks.press_key("Enter")
        engine_with_mocks.page.keyboard.press.assert_awaited_once_with("Enter")

    async def test_key_combo(self, engine_with_mocks: DesktopEngine) -> None:
        await engine_with_mocks.key_combo("Control", "A")
        engine_with_mocks.page.keyboard.press.assert_awaited_once_with(
            "Control+A",
        )

    # -- Screenshot (PyAutoGUI) --

    async def test_screenshot(
        self, engine_with_mocks: DesktopEngine, mock_pag: MagicMock,
    ) -> None:
        mock_img = MagicMock()
        mock_img.save = MagicMock()
        mock_pag.screenshot.return_value = mock_img
        data = await engine_with_mocks.screenshot()
        assert isinstance(data, bytes)
        mock_pag.screenshot.assert_called_once()

    async def test_save_screenshot(
        self, engine_with_mocks: DesktopEngine, mock_pag: MagicMock, tmp_path: Path,
    ) -> None:
        out = tmp_path / "shots" / "test.png"
        result = await engine_with_mocks.save_screenshot(out)
        assert result == out
        assert out.parent.exists()
        mock_pag.screenshot.assert_called_once_with(str(out))

    # -- Navigation (Playwright) --

    async def test_navigate(self, engine_with_mocks: DesktopEngine) -> None:
        await engine_with_mocks.navigate("https://test.com")
        engine_with_mocks.page.goto.assert_awaited_once_with(
            "https://test.com", wait_until="domcontentloaded",
        )

    async def test_go_back(self, engine_with_mocks: DesktopEngine) -> None:
        await engine_with_mocks.go_back()
        engine_with_mocks.page.go_back.assert_awaited_once()

    async def test_refresh(self, engine_with_mocks: DesktopEngine) -> None:
        await engine_with_mocks.refresh()
        engine_with_mocks.page.reload.assert_awaited_once()

    async def test_get_url(self, engine_with_mocks: DesktopEngine) -> None:
        url = await engine_with_mocks.get_url()
        assert url == "https://example.com/page"

    async def test_get_page_text(self, engine_with_mocks: DesktopEngine) -> None:
        text = await engine_with_mocks.get_page_text()
        assert text == "Page text"

    async def test_navigate_failure_raises_engine_error(
        self, engine_with_mocks: DesktopEngine,
    ) -> None:
        engine_with_mocks.page.goto.side_effect = Exception("Network error")
        with pytest.raises(EngineError, match="Navigation.*failed"):
            await engine_with_mocks.navigate("https://fail.com")


class TestDesktopEngineCoordinateConversion:
    """Test viewport-to-screen coordinate conversion."""

    def test_viewport_to_screen_no_offset(self) -> None:
        engine = DesktopEngine()
        assert engine._viewport_to_screen(100, 200) == (100, 200)

    def test_viewport_to_screen_with_offset(self) -> None:
        engine = DesktopEngine()
        engine._window_offset_x = 50
        engine._window_offset_y = 80
        assert engine._viewport_to_screen(100, 200) == (150, 280)

    async def test_move_mouse_applies_offset(self, mock_pag: MagicMock) -> None:
        engine = DesktopEngine()
        engine._pag = mock_pag
        engine._window_offset_x = 30
        engine._window_offset_y = 60
        await engine.move_mouse(200, 300)
        mock_pag.moveTo.assert_called_once_with(230, 360)
        assert engine.mouse_position == (200, 300)

    @pytest.mark.asyncio
    async def test_update_window_offset(self, mock_pag: MagicMock) -> None:
        engine = DesktopEngine()
        engine._pag = mock_pag
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value={
            "screenX": 100, "screenY": 50,
            "chromeWidth": 0, "chromeHeight": 72,
            "devicePixelRatio": 2.0,
        })
        engine._page = mock_page
        await engine._update_window_offset()
        assert engine._window_offset_x == 100
        assert engine._window_offset_y == 122  # 50 + 72
        assert engine._device_pixel_ratio == 2.0

    @pytest.mark.asyncio
    async def test_update_window_offset_fallback(self, mock_pag: MagicMock) -> None:
        engine = DesktopEngine()
        engine._pag = mock_pag
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(side_effect=Exception("no JS"))
        engine._page = mock_page
        await engine._update_window_offset()
        assert engine._window_offset_x == 0
        assert engine._window_offset_y == 80  # sensible fallback


class TestDesktopEngineScreenOps:
    """Test screen-coordinate operations for PyAutoGUI image matching."""

    async def test_find_on_screen_found(self, mock_pag: MagicMock) -> None:
        engine = DesktopEngine()
        engine._pag = mock_pag
        mock_location = MagicMock()
        mock_pag.locateOnScreen.return_value = mock_location
        mock_pag.center.return_value = MagicMock(x=500, y=300)
        result = await engine.find_on_screen("button.png", confidence=0.9)
        assert result == (500, 300)
        mock_pag.locateOnScreen.assert_called_once_with(
            "button.png", confidence=0.9,
        )

    async def test_find_on_screen_not_found(self, mock_pag: MagicMock) -> None:
        engine = DesktopEngine()
        engine._pag = mock_pag
        mock_pag.locateOnScreen.return_value = None
        result = await engine.find_on_screen("missing.png")
        assert result is None

    async def test_find_on_screen_error(self, mock_pag: MagicMock) -> None:
        engine = DesktopEngine()
        engine._pag = mock_pag
        mock_pag.locateOnScreen.side_effect = Exception("no display")
        result = await engine.find_on_screen("broken.png")
        assert result is None

    async def test_click_on_screen(self, mock_pag: MagicMock) -> None:
        engine = DesktopEngine()
        engine._pag = mock_pag
        await engine.click_on_screen(500, 300)
        mock_pag.click.assert_called_once_with(500, 300)

    async def test_double_click_on_screen(self, mock_pag: MagicMock) -> None:
        engine = DesktopEngine()
        engine._pag = mock_pag
        await engine.double_click_on_screen(500, 300)
        mock_pag.doubleClick.assert_called_once_with(500, 300)

    async def test_right_click_on_screen(self, mock_pag: MagicMock) -> None:
        engine = DesktopEngine()
        engine._pag = mock_pag
        await engine.right_click_on_screen(500, 300)
        mock_pag.rightClick.assert_called_once_with(500, 300)

    async def test_move_mouse_screen(self, mock_pag: MagicMock) -> None:
        engine = DesktopEngine()
        engine._pag = mock_pag
        await engine.move_mouse_screen(500, 300)
        mock_pag.moveTo.assert_called_once_with(500, 300)


class TestDesktopEngineFindTextPosition:
    """Test find_text_position using Playwright locator."""

    @pytest.fixture
    def engine_with_page(self) -> DesktopEngine:
        engine = DesktopEngine()
        mock_page = MagicMock()
        engine._page = mock_page
        return engine

    @pytest.mark.asyncio
    async def test_find_text_position_found(self, engine_with_page: DesktopEngine) -> None:
        mock_locator = MagicMock()
        mock_locator.is_visible = AsyncMock(return_value=True)
        mock_locator.bounding_box = AsyncMock(
            return_value={"x": 100, "y": 200, "width": 80, "height": 30},
        )
        mock_first = MagicMock()
        mock_first.first = mock_locator
        engine_with_page._page.get_by_text = MagicMock(return_value=mock_first)
        result = await engine_with_page.find_text_position("Email")
        assert result == (140, 215)

    @pytest.mark.asyncio
    async def test_find_text_position_not_visible(self, engine_with_page: DesktopEngine) -> None:
        mock_locator = MagicMock()
        mock_locator.is_visible = AsyncMock(return_value=False)
        mock_first = MagicMock()
        mock_first.first = mock_locator
        engine_with_page._page.get_by_text = MagicMock(return_value=mock_first)
        result = await engine_with_page.find_text_position("NonExistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_text_position_no_page(self) -> None:
        engine = DesktopEngine()
        engine._page = None
        result = await engine.find_text_position("Email")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_text_position_exception(self, engine_with_page: DesktopEngine) -> None:
        engine_with_page._page.get_by_text = MagicMock(side_effect=Exception("fail"))
        result = await engine_with_page.find_text_position("Email")
        assert result is None


class TestDesktopEngineRegistry:
    def test_registered(self) -> None:
        from aat.engine import ENGINE_REGISTRY

        assert "desktop" in ENGINE_REGISTRY
        assert ENGINE_REGISTRY["desktop"] is DesktopEngine
