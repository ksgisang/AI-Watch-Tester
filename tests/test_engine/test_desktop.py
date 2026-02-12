"""Tests for DesktopEngine — PyAutoGUI + Playwright hybrid engine.

Uses mock-based unit tests. PyAutoGUI calls are mocked to avoid
requiring a real display.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aat.core.exceptions import EngineError
from aat.core.models import EngineConfig
from aat.engine.desktop import DesktopEngine

if TYPE_CHECKING:
    from pathlib import Path


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
    @patch("aat.engine.desktop.pyautogui")
    def test_mouse_position_from_pyautogui(self, mock_pag: MagicMock) -> None:
        mock_pag.position.return_value = MagicMock(x=150, y=250)
        engine = DesktopEngine()
        assert engine.mouse_position == (150, 250)


class TestDesktopEngineActions:
    """Test engine actions with mocked PyAutoGUI and Playwright."""

    @pytest.fixture
    def engine_with_mocks(self) -> DesktopEngine:
        """Create a DesktopEngine with a mock Playwright page."""
        engine = DesktopEngine()
        mock_page = MagicMock()
        mock_page.goto = AsyncMock()
        mock_page.go_back = AsyncMock()
        mock_page.reload = AsyncMock()
        mock_page.inner_text = AsyncMock(return_value="Page text")
        mock_page.url = "https://example.com/page"
        engine._page = mock_page
        return engine

    # -- Mouse (PyAutoGUI) --

    @pytest.mark.asyncio
    @patch("aat.engine.desktop.pyautogui")
    async def test_click(self, mock_pag: MagicMock, engine_with_mocks: DesktopEngine) -> None:
        engine = engine_with_mocks
        await engine.click(100, 200)
        mock_pag.click.assert_called_once_with(100, 200)

    @pytest.mark.asyncio
    @patch("aat.engine.desktop.pyautogui")
    async def test_double_click(
        self, mock_pag: MagicMock, engine_with_mocks: DesktopEngine,
    ) -> None:
        engine = engine_with_mocks
        await engine.double_click(50, 75)
        mock_pag.doubleClick.assert_called_once_with(50, 75)

    @pytest.mark.asyncio
    @patch("aat.engine.desktop.pyautogui")
    async def test_right_click(
        self, mock_pag: MagicMock, engine_with_mocks: DesktopEngine,
    ) -> None:
        engine = engine_with_mocks
        await engine.right_click(10, 20)
        mock_pag.rightClick.assert_called_once_with(10, 20)

    @pytest.mark.asyncio
    @patch("aat.engine.desktop.pyautogui")
    async def test_move_mouse(
        self, mock_pag: MagicMock, engine_with_mocks: DesktopEngine,
    ) -> None:
        engine = engine_with_mocks
        await engine.move_mouse(300, 400)
        mock_pag.moveTo.assert_called_once_with(300, 400)

    @pytest.mark.asyncio
    @patch("aat.engine.desktop.pyautogui")
    async def test_scroll(
        self, mock_pag: MagicMock, engine_with_mocks: DesktopEngine,
    ) -> None:
        engine = engine_with_mocks
        await engine.scroll(100, 200, 300)
        mock_pag.moveTo.assert_called_once_with(100, 200)
        # delta > 0 means down in our convention; pyautogui uses negative for down
        mock_pag.scroll.assert_called_once_with(-300)

    # -- Keyboard (PyAutoGUI) --

    @pytest.mark.asyncio
    @patch("aat.engine.desktop.pyautogui")
    async def test_type_text(
        self, mock_pag: MagicMock, engine_with_mocks: DesktopEngine,
    ) -> None:
        engine = engine_with_mocks
        await engine.type_text("hello")
        mock_pag.write.assert_called_once_with("hello", interval=0.05)

    @pytest.mark.asyncio
    @patch("aat.engine.desktop.pyautogui")
    async def test_press_key(
        self, mock_pag: MagicMock, engine_with_mocks: DesktopEngine,
    ) -> None:
        engine = engine_with_mocks
        await engine.press_key("Enter")
        mock_pag.press.assert_called_once_with("enter")

    @pytest.mark.asyncio
    @patch("aat.engine.desktop.pyautogui")
    async def test_key_combo(
        self, mock_pag: MagicMock, engine_with_mocks: DesktopEngine,
    ) -> None:
        engine = engine_with_mocks
        await engine.key_combo("Control", "A")
        mock_pag.hotkey.assert_called_once_with("control", "a")

    # -- Screenshot (PyAutoGUI) --

    @pytest.mark.asyncio
    @patch("aat.engine.desktop.pyautogui")
    async def test_screenshot(
        self, mock_pag: MagicMock, engine_with_mocks: DesktopEngine,
    ) -> None:
        engine = engine_with_mocks
        # Mock screenshot to return a PIL Image-like object
        mock_img = MagicMock()
        mock_img.save = MagicMock()
        mock_pag.screenshot.return_value = mock_img
        data = await engine.screenshot()
        assert isinstance(data, bytes)
        mock_pag.screenshot.assert_called_once()

    @pytest.mark.asyncio
    @patch("aat.engine.desktop.pyautogui")
    async def test_save_screenshot(
        self, mock_pag: MagicMock, engine_with_mocks: DesktopEngine, tmp_path: Path,
    ) -> None:
        engine = engine_with_mocks
        out = tmp_path / "shots" / "test.png"
        result = await engine.save_screenshot(out)
        assert result == out
        assert out.parent.exists()
        mock_pag.screenshot.assert_called_once_with(str(out))

    # -- Navigation (Playwright) --

    @pytest.mark.asyncio
    async def test_navigate(self, engine_with_mocks: DesktopEngine) -> None:
        engine = engine_with_mocks
        await engine.navigate("https://test.com")
        engine.page.goto.assert_awaited_once_with(
            "https://test.com", wait_until="domcontentloaded",
        )

    @pytest.mark.asyncio
    async def test_go_back(self, engine_with_mocks: DesktopEngine) -> None:
        engine = engine_with_mocks
        await engine.go_back()
        engine.page.go_back.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_refresh(self, engine_with_mocks: DesktopEngine) -> None:
        engine = engine_with_mocks
        await engine.refresh()
        engine.page.reload.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_url(self, engine_with_mocks: DesktopEngine) -> None:
        engine = engine_with_mocks
        url = await engine.get_url()
        assert url == "https://example.com/page"

    @pytest.mark.asyncio
    async def test_get_page_text(self, engine_with_mocks: DesktopEngine) -> None:
        engine = engine_with_mocks
        text = await engine.get_page_text()
        assert text == "Page text"

    @pytest.mark.asyncio
    async def test_navigate_failure_raises_engine_error(
        self, engine_with_mocks: DesktopEngine,
    ) -> None:
        engine = engine_with_mocks
        engine.page.goto.side_effect = Exception("Network error")
        with pytest.raises(EngineError, match="Navigation.*failed"):
            await engine.navigate("https://fail.com")


class TestDesktopEngineRegistry:
    def test_registered(self) -> None:
        from aat.engine import ENGINE_REGISTRY

        assert "desktop" in ENGINE_REGISTRY
        assert ENGINE_REGISTRY["desktop"] is DesktopEngine
