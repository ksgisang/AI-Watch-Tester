"""DesktopEngine — PyAutoGUI + Playwright hybrid engine.

Uses PyAutoGUI for OS-level mouse/keyboard/screenshot control.
Playwright handles browser lifecycle and navigation (navigate, go_back, refresh).
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path  # noqa: TC003

import pyautogui
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from aat.core.exceptions import EngineError
from aat.core.models import EngineConfig
from aat.engine.base import BaseEngine


class DesktopEngine(BaseEngine):
    """PyAutoGUI + Playwright hybrid test engine.

    Mouse, keyboard, and screenshot operations use PyAutoGUI (OS-level).
    Browser navigation (navigate, go_back, refresh) uses Playwright.
    """

    def __init__(self, config: EngineConfig | None = None) -> None:
        self._config = config or EngineConfig()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._mouse_x: int = 0
        self._mouse_y: int = 0

    @property
    def page(self) -> Page:
        """Current Playwright page. Raises EngineError if not started."""
        if self._page is None:
            msg = "DesktopEngine not started. Call start() first."
            raise EngineError(msg)
        return self._page

    @property
    def mouse_position(self) -> tuple[int, int]:
        """Current mouse position from PyAutoGUI."""
        pos = pyautogui.position()
        return (pos.x, pos.y)

    async def start(self) -> None:
        """Launch browser via Playwright and configure PyAutoGUI."""
        try:
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.0

            pw = await async_playwright().start()
            self._playwright = pw

            browser_type = getattr(pw, self._config.browser, None)
            if browser_type is None:
                msg = f"Unknown browser: {self._config.browser}"
                raise EngineError(msg)

            self._browser = await browser_type.launch(headless=False)
            self._context = await self._browser.new_context(
                viewport={
                    "width": self._config.viewport_width,
                    "height": self._config.viewport_height,
                },
            )
            self._context.set_default_timeout(self._config.timeout_ms)
            self._page = await self._context.new_page()
        except EngineError:
            raise
        except Exception as e:
            msg = f"Failed to start DesktopEngine: {e}"
            raise EngineError(msg) from e

    async def stop(self) -> None:
        """Close browser and cleanup."""
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            msg = f"Failed to stop DesktopEngine: {e}"
            raise EngineError(msg) from e
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None

    # ------------------------------------------------------------------
    # Screenshot — PyAutoGUI (OS-level full screen)
    # ------------------------------------------------------------------

    async def screenshot(self) -> bytes:
        """Capture full screen as PNG bytes via PyAutoGUI."""
        try:
            img = await asyncio.to_thread(pyautogui.screenshot)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            msg = f"Screenshot failed: {e}"
            raise EngineError(msg) from e

    async def save_screenshot(self, path: Path) -> Path:
        """Save full screen screenshot to file via PyAutoGUI."""
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(pyautogui.screenshot, str(path))
        return path

    # ------------------------------------------------------------------
    # Mouse — PyAutoGUI (OS-level)
    # ------------------------------------------------------------------

    async def click(self, x: int, y: int) -> None:
        """Click at coordinates via PyAutoGUI."""
        await asyncio.to_thread(pyautogui.click, x, y)
        self._mouse_x, self._mouse_y = x, y

    async def double_click(self, x: int, y: int) -> None:
        """Double-click at coordinates via PyAutoGUI."""
        await asyncio.to_thread(pyautogui.doubleClick, x, y)
        self._mouse_x, self._mouse_y = x, y

    async def right_click(self, x: int, y: int) -> None:
        """Right-click at coordinates via PyAutoGUI."""
        await asyncio.to_thread(pyautogui.rightClick, x, y)
        self._mouse_x, self._mouse_y = x, y

    async def move_mouse(self, x: int, y: int) -> None:
        """Move mouse pointer via PyAutoGUI (no click)."""
        await asyncio.to_thread(pyautogui.moveTo, x, y)
        self._mouse_x, self._mouse_y = x, y

    async def scroll(self, x: int, y: int, delta: int) -> None:
        """Scroll at coordinates via PyAutoGUI. delta > 0: down, delta < 0: up."""
        await asyncio.to_thread(pyautogui.moveTo, x, y)
        # PyAutoGUI scroll: positive = up, negative = down (opposite convention)
        await asyncio.to_thread(pyautogui.scroll, -delta)
        self._mouse_x, self._mouse_y = x, y

    # ------------------------------------------------------------------
    # Keyboard — PyAutoGUI (OS-level)
    # ------------------------------------------------------------------

    async def type_text(self, text: str) -> None:
        """Type text via PyAutoGUI with slight interval."""
        await asyncio.to_thread(pyautogui.write, text, interval=0.05)

    async def press_key(self, key: str) -> None:
        """Press a single key via PyAutoGUI."""
        await asyncio.to_thread(pyautogui.press, key.lower())

    async def key_combo(self, *keys: str) -> None:
        """Press key combination via PyAutoGUI."""
        await asyncio.to_thread(pyautogui.hotkey, *[k.lower() for k in keys])

    # ------------------------------------------------------------------
    # Navigation — Playwright (browser control)
    # ------------------------------------------------------------------

    async def navigate(self, url: str) -> None:
        """Navigate to URL via Playwright."""
        try:
            await self.page.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            msg = f"Navigation to {url} failed: {e}"
            raise EngineError(msg) from e

    async def go_back(self) -> None:
        """Go back via Playwright."""
        await self.page.go_back()

    async def refresh(self) -> None:
        """Refresh page via Playwright."""
        await self.page.reload()

    async def get_url(self) -> str:
        """Return current URL from Playwright."""
        return self.page.url

    async def get_page_text(self) -> str:
        """Return visible text of current page from Playwright."""
        return await self.page.inner_text("body")
