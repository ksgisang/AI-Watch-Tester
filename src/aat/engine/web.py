"""WebEngine — Playwright-based web test engine.

Implements BaseEngine using Playwright async API.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

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


class WebEngine(BaseEngine):
    """Playwright-based web test engine."""

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
            msg = "WebEngine not started. Call start() first."
            raise EngineError(msg)
        return self._page

    @property
    def mouse_position(self) -> tuple[int, int]:
        """Current tracked mouse position."""
        return (self._mouse_x, self._mouse_y)

    async def start(self) -> None:
        """Launch browser and create page."""
        try:
            pw = await async_playwright().start()
            self._playwright = pw

            browser_type = getattr(pw, self._config.browser, None)
            if browser_type is None:
                msg = f"Unknown browser: {self._config.browser}"
                raise EngineError(msg)

            self._browser = await browser_type.launch(headless=self._config.headless)
            self._context = await self._browser.new_context(
                viewport={
                    "width": self._config.viewport_width,
                    "height": self._config.viewport_height,
                },
                ignore_https_errors=True,
            )
            self._context.set_default_timeout(self._config.timeout_ms)
            self._page = await self._context.new_page()
        except EngineError:
            raise
        except Exception as e:
            msg = f"Failed to start WebEngine: {e}"
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
            msg = f"Failed to stop WebEngine: {e}"
            raise EngineError(msg) from e
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None

    async def screenshot(self) -> bytes:
        """Capture current page as PNG bytes."""
        try:
            return await self.page.screenshot(type="png", full_page=False)
        except Exception as e:
            msg = f"Screenshot failed: {e}"
            raise EngineError(msg) from e

    async def click(self, x: int, y: int) -> None:
        """Click at coordinates."""
        await self.page.mouse.click(x, y)
        self._mouse_x, self._mouse_y = x, y

    async def double_click(self, x: int, y: int) -> None:
        """Double-click at coordinates."""
        await self.page.mouse.dblclick(x, y)
        self._mouse_x, self._mouse_y = x, y

    async def right_click(self, x: int, y: int) -> None:
        """Right-click at coordinates."""
        await self.page.mouse.click(x, y, button="right")
        self._mouse_x, self._mouse_y = x, y

    async def type_text(self, text: str) -> None:
        """Type text at current focus."""
        await self.page.keyboard.type(text)

    async def press_key(self, key: str) -> None:
        """Press a single key."""
        await self.page.keyboard.press(key)

    async def key_combo(self, *keys: str) -> None:
        """Press key combination (e.g. 'Control', 'a')."""
        combo = "+".join(keys)
        await self.page.keyboard.press(combo)

    async def navigate(self, url: str) -> None:
        """Navigate to URL."""
        try:
            await self.page.goto(url, wait_until="domcontentloaded")
        except Exception as e:
            msg = f"Navigation to {url} failed: {e}"
            raise EngineError(msg) from e

    async def go_back(self) -> None:
        """Go back."""
        await self.page.go_back()

    async def refresh(self) -> None:
        """Refresh page."""
        await self.page.reload()

    async def scroll(self, x: int, y: int, delta: int) -> None:
        """Scroll at coordinates. delta > 0: down, delta < 0: up."""
        await self.page.mouse.move(x, y)
        await self.page.mouse.wheel(0, delta)
        self._mouse_x, self._mouse_y = x, y

    async def move_mouse(self, x: int, y: int) -> None:
        """Move mouse pointer (no click)."""
        await self.page.mouse.move(x, y)
        self._mouse_x, self._mouse_y = x, y

    async def get_url(self) -> str:
        """Return current URL."""
        return self.page.url

    async def get_page_text(self) -> str:
        """Return visible text of current page."""
        return await self.page.inner_text("body")

    async def find_text_position(self, text: str) -> tuple[int, int] | None:
        """Find element on page and scroll into view if needed.

        Strategy:
        1. get_by_label — input/textarea linked to label (highest priority)
        2. get_by_placeholder — placeholder text
        3. get_by_role("button") — buttons
        4. get_by_role("link") — links
        5. get_by_text — general text fallback

        Automatically scrolls elements into the viewport before returning
        coordinates. Returns (x, y) center coordinates, or None.
        """
        # If text looks like a CSS selector, try it directly first
        if text.startswith(("#", "[", ".")) or text.startswith("input"):
            try:
                locator = self.page.locator(text).first
                if await locator.count() > 0:
                    await locator.scroll_into_view_if_needed(timeout=3000)
                    box = await locator.bounding_box()
                    if box:
                        return (
                            int(box["x"] + box["width"] / 2),
                            int(box["y"] + box["height"] / 2),
                        )
            except Exception:
                pass

        strategies = [
            lambda: self.page.get_by_label(text, exact=False).first,
            lambda: self.page.get_by_placeholder(text, exact=False).first,
            lambda: self.page.get_by_role("button", name=text, exact=False).first,
            lambda: self.page.get_by_role("link", name=text, exact=False).first,
            lambda: self.page.get_by_text(text, exact=False).first,
        ]

        for strategy in strategies:
            try:
                locator = strategy()  # type: ignore[no-untyped-call]
                # Check element exists in DOM (even if off-screen)
                if await locator.count() == 0:
                    continue
                # Scroll into viewport so we can click it
                await locator.scroll_into_view_if_needed(timeout=3000)
                box = await locator.bounding_box()
                if box:
                    return (
                        int(box["x"] + box["width"] / 2),
                        int(box["y"] + box["height"] / 2),
                    )
            except Exception:
                continue

        return None

    async def scroll_to_top(self) -> None:
        """Scroll page to top (0, 0)."""
        await self.page.evaluate("window.scrollTo(0, 0)")

    async def force_click_by_text(self, text: str) -> bool:
        """Find element by text strategies and force-click it.

        Uses Playwright's force option to bypass actionability checks
        (e.g. element hidden behind sticky header). Returns True if clicked.
        """
        strategies = [
            lambda: self.page.get_by_label(text, exact=False).first,
            lambda: self.page.get_by_placeholder(text, exact=False).first,
            lambda: self.page.get_by_role("button", name=text, exact=False).first,
            lambda: self.page.get_by_role("link", name=text, exact=False).first,
            lambda: self.page.get_by_text(text, exact=False).first,
        ]
        for strategy in strategies:
            try:
                locator = strategy()  # type: ignore[no-untyped-call]
                if await locator.count() > 0:
                    await locator.click(force=True, timeout=3000)
                    return True
            except Exception:
                continue

        # CSS selector fallback
        if text.startswith(("#", "[", ".")) or text.startswith("input"):
            try:
                locator = self.page.locator(text).first
                if await locator.count() > 0:
                    await locator.click(force=True, timeout=3000)
                    return True
            except Exception:
                pass

        return False

    async def save_screenshot(self, path: Path) -> Path:
        """Save screenshot to file and return path."""
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=str(path), type="png", full_page=False)
        return path
