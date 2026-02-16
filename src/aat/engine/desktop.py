"""DesktopEngine — PyAutoGUI + Playwright hybrid engine.

Mouse movement and screenshots use PyAutoGUI (OS-level).
Clicks and keyboard use Playwright (viewport-accurate, IME-safe).
Navigation uses Playwright.
"""

from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    import types

_log = logging.getLogger(__name__)


def _get_pyautogui() -> Any:
    """Lazy import pyautogui to avoid DISPLAY errors on headless Linux."""
    try:
        import pyautogui  # type: ignore[import-untyped]
    except KeyError as e:
        msg = f"pyautogui requires a display (DISPLAY env var): {e}"
        raise EngineError(msg) from e
    return pyautogui


class DesktopEngine(BaseEngine):
    """PyAutoGUI + Playwright hybrid test engine.

    Mouse movement and screenshots use PyAutoGUI (OS-level).
    Clicks and keyboard input use Playwright (viewport-accurate, IME-safe).
    """

    def __init__(self, config: EngineConfig | None = None) -> None:
        self._config = config or EngineConfig()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._mouse_x: int = 0
        self._mouse_y: int = 0
        self._pag: types.ModuleType | None = None
        # Viewport-to-screen coordinate offset
        self._window_offset_x: int = 0
        self._window_offset_y: int = 0
        self._device_pixel_ratio: float = 1.0

    @property
    def page(self) -> Page:
        """Current Playwright page. Raises EngineError if not started."""
        if self._page is None:
            msg = "DesktopEngine not started. Call start() first."
            raise EngineError(msg)
        return self._page

    @property
    def pag(self) -> Any:
        """Lazy-loaded pyautogui module."""
        if self._pag is None:
            self._pag = _get_pyautogui()
        return self._pag

    @property
    def mouse_position(self) -> tuple[int, int]:
        """Current mouse position in viewport coordinates (for Humanizer)."""
        return (self._mouse_x, self._mouse_y)

    async def start(self) -> None:
        """Launch browser via Playwright and configure PyAutoGUI."""
        try:
            pag = self.pag
            pag.FAILSAFE = True
            pag.PAUSE = 0.1

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

            # Move browser window to configured position (CDP, Chromium only)
            if self._config.window_x is not None or self._config.window_y is not None:
                x = self._config.window_x or 0
                y = self._config.window_y or 0
                try:
                    cdp = await self._page.context.new_cdp_session(self._page)
                    window = await cdp.send("Browser.getWindowForTarget")
                    await cdp.send(
                        "Browser.setWindowBounds",
                        {
                            "windowId": window["windowId"],
                            "bounds": {"left": x, "top": y},
                        },
                    )
                    await cdp.detach()
                except Exception:  # noqa: BLE001
                    _log.debug("CDP window positioning not supported")

            await self._update_window_offset()
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
    # Coordinate conversion (viewport → screen)
    # ------------------------------------------------------------------

    async def _update_window_offset(self) -> None:
        """Detect browser window position to compute viewport-to-screen offset."""
        if not self._page:
            return
        try:
            info = await self._page.evaluate(
                """() => ({
                    screenX: window.screenX,
                    screenY: window.screenY,
                    chromeX: (window.outerWidth - window.innerWidth) / 2,
                    chromeY: window.outerHeight - window.innerHeight,
                    devicePixelRatio: window.devicePixelRatio,
                })"""
            )
            self._window_offset_x = int(info["screenX"] + info["chromeX"])
            self._window_offset_y = int(info["screenY"] + info["chromeY"])
            self._device_pixel_ratio = info.get("devicePixelRatio", 1.0)
            _log.debug(
                "Window offset: x=%d, y=%d, dpr=%.1f",
                self._window_offset_x,
                self._window_offset_y,
                self._device_pixel_ratio,
            )
        except Exception:
            self._window_offset_x = 0
            self._window_offset_y = 80  # sensible fallback for typical browser chrome
            self._device_pixel_ratio = 1.0

    def _viewport_to_screen(self, x: int, y: int) -> tuple[int, int]:
        """Convert Playwright viewport coordinates to OS screen coordinates."""
        return (x + self._window_offset_x, y + self._window_offset_y)

    # ------------------------------------------------------------------
    # Screenshot — PyAutoGUI (OS-level full screen)
    # ------------------------------------------------------------------

    async def screenshot(self) -> bytes:
        """Capture full screen as PNG bytes via PyAutoGUI."""
        try:
            img = await asyncio.to_thread(self.pag.screenshot)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            msg = f"Screenshot failed: {e}"
            raise EngineError(msg) from e

    async def save_screenshot(self, path: Path) -> Path:
        """Save full screen screenshot to file via PyAutoGUI."""
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self.pag.screenshot, str(path))
        return path

    # ------------------------------------------------------------------
    # Mouse — movement via PyAutoGUI, clicks via Playwright
    # ------------------------------------------------------------------

    async def click(self, x: int, y: int) -> None:
        """Click at viewport coordinates via Playwright."""
        await self.page.mouse.click(x, y)
        self._mouse_x, self._mouse_y = x, y

    async def double_click(self, x: int, y: int) -> None:
        """Double-click at viewport coordinates via Playwright."""
        await self.page.mouse.dblclick(x, y)
        self._mouse_x, self._mouse_y = x, y

    async def right_click(self, x: int, y: int) -> None:
        """Right-click at viewport coordinates via Playwright."""
        await self.page.mouse.click(x, y, button="right")
        self._mouse_x, self._mouse_y = x, y

    async def move_mouse(self, x: int, y: int) -> None:
        """Move mouse pointer via PyAutoGUI (viewport → screen conversion)."""
        sx, sy = self._viewport_to_screen(x, y)
        await asyncio.to_thread(self.pag.moveTo, sx, sy)
        self._mouse_x, self._mouse_y = x, y

    async def scroll(self, x: int, y: int, delta: int) -> None:
        """Scroll at viewport coordinates via PyAutoGUI."""
        sx, sy = self._viewport_to_screen(x, y)
        await asyncio.to_thread(self.pag.moveTo, sx, sy)
        # PyAutoGUI scroll: positive = up, negative = down (opposite convention)
        await asyncio.to_thread(self.pag.scroll, -delta)
        self._mouse_x, self._mouse_y = x, y

    # ------------------------------------------------------------------
    # Screen-coordinate operations (for PyAutoGUI image matching)
    # ------------------------------------------------------------------

    async def find_on_screen(
        self, image_path: str, confidence: float = 0.8
    ) -> tuple[int, int] | None:
        """Find image on screen via PyAutoGUI, return screen coordinates."""
        try:
            location = await asyncio.to_thread(
                self.pag.locateOnScreen, image_path, confidence=confidence
            )
            if location is not None:
                center = self.pag.center(location)
                return (center.x, center.y)
        except Exception:
            pass
        return None

    async def click_on_screen(self, x: int, y: int) -> None:
        """Click at screen coordinates via PyAutoGUI (no conversion)."""
        await asyncio.to_thread(self.pag.click, x, y)

    async def double_click_on_screen(self, x: int, y: int) -> None:
        """Double-click at screen coordinates via PyAutoGUI (no conversion)."""
        await asyncio.to_thread(self.pag.doubleClick, x, y)

    async def right_click_on_screen(self, x: int, y: int) -> None:
        """Right-click at screen coordinates via PyAutoGUI (no conversion)."""
        await asyncio.to_thread(self.pag.rightClick, x, y)

    async def move_mouse_screen(self, x: int, y: int) -> None:
        """Move mouse to screen coordinates via PyAutoGUI (no conversion)."""
        await asyncio.to_thread(self.pag.moveTo, x, y)

    # ------------------------------------------------------------------
    # Keyboard — Playwright (IME-safe, works with Korean/Japanese input)
    # ------------------------------------------------------------------

    async def type_text(self, text: str) -> None:
        """Type text via Playwright (handles Korean/CJK input correctly)."""
        await self.page.keyboard.type(text, delay=0)

    async def press_key(self, key: str) -> None:
        """Press a single key via Playwright."""
        await self.page.keyboard.press(key)

    async def key_combo(self, *keys: str) -> None:
        """Press key combination via Playwright."""
        combo = "+".join(keys)
        await self.page.keyboard.press(combo)

    # ------------------------------------------------------------------
    # Navigation — Playwright (browser control)
    # ------------------------------------------------------------------

    async def navigate(self, url: str) -> None:
        """Navigate to URL via Playwright."""
        try:
            await self.page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(0.5)
            await self._update_window_offset()
        except EngineError:
            raise
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

    async def find_text_position(self, text: str) -> tuple[int, int] | None:
        """Find element on page, prioritizing input fields over labels.

        Strategy:
        1. get_by_label — input/textarea linked to label (highest priority)
        2. get_by_placeholder — placeholder text
        3. get_by_role("button") — buttons
        4. get_by_role("link") — links
        5. get_by_text — general text fallback

        Returns (x, y) center coordinates in viewport pixels, or None.
        """
        if not self._page:
            return None

        strategies = [
            lambda: self._page.get_by_label(text, exact=False).first,
            lambda: self._page.get_by_placeholder(text, exact=False).first,
            lambda: self._page.get_by_role("button", name=text, exact=False).first,
            lambda: self._page.get_by_role("link", name=text, exact=False).first,
            lambda: self._page.get_by_text(text, exact=False).first,
        ]

        for strategy in strategies:
            try:
                locator = strategy()  # type: ignore[no-untyped-call]
                if await locator.is_visible(timeout=1000):
                    box = await locator.bounding_box()
                    if box:
                        return (
                            int(box["x"] + box["width"] / 2),
                            int(box["y"] + box["height"] / 2),
                        )
            except Exception:  # noqa: BLE001
                continue

        return None
