"""WebEngine — Playwright-based web test engine.

Implements BaseEngine using Playwright async API.
"""

from __future__ import annotations

import contextlib
from pathlib import Path  # noqa: TC003
from typing import Any

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


def _as_box(rect: Any) -> dict[str, float]:
    """Playwright's bounding box as a plain dict of four floats.

    ``bounding_box()`` returns a ``FloatRect``, which is not a ``dict[str,
    float]`` as far as the type checker is concerned. Copying the four keys we
    actually use keeps the return type honest and stops a Playwright type
    detail from leaking into every caller that wants to crop a screenshot.
    """
    return {
        "x": float(rect["x"]),
        "y": float(rect["y"]),
        "width": float(rect["width"]),
        "height": float(rect["height"]),
    }


class WebEngine(BaseEngine):
    """Playwright-based web test engine."""

    def __init__(self, config: EngineConfig | None = None) -> None:
        self._config = config or EngineConfig()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        # Start at viewport center (not 0,0 which is a bot signal)
        self._mouse_x: int = self._config.viewport_width // 2
        self._mouse_y: int = self._config.viewport_height // 2

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

            launch_args = getattr(self, "_launch_args", None)
            launch_kwargs: dict[str, Any] = {
                "headless": self._config.headless,
                "args": launch_args or [],
            }
            if self._config.slow_mo:
                launch_kwargs["slow_mo"] = self._config.slow_mo
            self._browser = await browser_type.launch(**launch_kwargs)
            self._context = await self._browser.new_context(
                viewport={
                    "width": self._config.viewport_width,
                    "height": self._config.viewport_height,
                },
                ignore_https_errors=True,
            )
            self._context.set_default_timeout(self._config.timeout_ms)
            self._page = await self._context.new_page()

            # Inject visual cursor for headed mode
            if not self._config.headless:
                await self._inject_cursor()
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

    async def save_session(self, path: str) -> None:
        """Save browser session (cookies, localStorage) to file."""
        from pathlib import Path

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if self._context:
            await self._context.storage_state(path=str(p))

    async def load_session(self, path: str) -> None:
        """Reload browser context with saved session state."""
        from pathlib import Path

        p = Path(path)
        if not p.exists():
            return

        # Recreate context with stored session
        old_page = self._page
        old_context = self._context
        try:
            self._context = await self._browser.new_context(  # type: ignore[union-attr]
                viewport={
                    "width": self._config.viewport_width,
                    "height": self._config.viewport_height,
                },
                ignore_https_errors=True,
                storage_state=str(p),
            )
            self._context.set_default_timeout(self._config.timeout_ms)
            self._page = await self._context.new_page()
            if not self._config.headless:
                await self._inject_cursor()
        except Exception:
            # Restore old context on failure
            self._page = old_page
            self._context = old_context
            raise
        else:
            # Close old context
            if old_context:
                with __import__("contextlib").suppress(Exception):
                    await old_context.close()

    async def screenshot(self) -> bytes:
        """Capture current page as PNG bytes."""
        try:
            return await self.page.screenshot(type="png", full_page=False)
        except Exception as e:
            msg = f"Screenshot failed: {e}"
            raise EngineError(msg) from e

    async def click(self, x: int, y: int) -> None:
        """Click at coordinates."""
        if not self._config.headless:
            await self._click_effect(x, y)
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
            await self._ensure_cursor()
        except EngineError:
            raise
        except Exception as e:
            msg = f"Navigation to {url} failed: {e}"
            raise EngineError(msg) from e

    async def go_back(self) -> None:
        """Go back."""
        await self.page.go_back()
        await self._ensure_cursor()

    async def refresh(self) -> None:
        """Refresh page."""
        await self.page.reload()
        await self._ensure_cursor()

    async def scroll(self, x: int, y: int, delta: int) -> None:
        """Scroll at coordinates. delta > 0: down, delta < 0: up."""
        await self.page.mouse.move(x, y)
        await self.page.mouse.wheel(0, delta)
        self._mouse_x, self._mouse_y = x, y

    async def move_mouse(self, x: int, y: int) -> None:
        """Move mouse pointer (no click)."""
        await self.page.mouse.move(x, y)
        self._mouse_x, self._mouse_y = x, y
        # Update visual cursor position
        if not self._config.headless:
            await self._move_cursor(x, y)

    # -- Visual cursor for headed mode --------------------------------------

    async def _inject_cursor(self) -> None:
        """Inject a visual cursor element into the page."""
        # Page might not be ready yet
        with contextlib.suppress(Exception):
            await self.page.evaluate("""() => {
                if (document.getElementById('awt-cursor')) return;
                const cursor = document.createElement('div');
                cursor.id = 'awt-cursor';
                cursor.style.cssText = `
                    position: fixed; z-index: 2147483647;
                    width: 20px; height: 20px;
                    margin-left: -10px; margin-top: -10px;
                    border-radius: 50%;
                    border: 2px solid #22d3ee;
                    background: rgba(34, 211, 238, 0.15);
                    pointer-events: none;
                    transition: left 0.016s linear, top 0.016s linear;
                    left: -50px; top: -50px;
                    box-shadow: 0 0 8px rgba(34, 211, 238, 0.4);
                `;
                document.body.appendChild(cursor);
            }""")

    async def _move_cursor(self, x: int, y: int) -> None:
        """Update visual cursor position."""
        with contextlib.suppress(Exception):
            await self.page.evaluate(f"""() => {{
                const c = document.getElementById('awt-cursor');
                if (c) {{ c.style.left = '{x}px'; c.style.top = '{y}px'; }}
            }}""")

    async def _click_effect(self, x: int, y: int) -> None:
        """Show a click ripple effect at coordinates."""
        with contextlib.suppress(Exception):
            await self.page.evaluate(f"""() => {{
                const ring = document.createElement('div');
                ring.style.cssText = `
                    position: fixed; z-index: 2147483646;
                    left: {x}px; top: {y}px;
                    width: 0; height: 0;
                    margin-left: 0; margin-top: 0;
                    border-radius: 50%;
                    border: 2px solid #22d3ee;
                    pointer-events: none;
                    opacity: 1;
                    transition: all 0.4s ease-out;
                `;
                document.body.appendChild(ring);
                requestAnimationFrame(() => {{
                    ring.style.width = '40px';
                    ring.style.height = '40px';
                    ring.style.marginLeft = '-20px';
                    ring.style.marginTop = '-20px';
                    ring.style.opacity = '0';
                }});
                setTimeout(() => ring.remove(), 500);
            }}""")

    async def _ensure_cursor(self) -> None:
        """Re-inject cursor after page navigation."""
        if not self._config.headless:
            await self._inject_cursor()

    async def get_url(self) -> str:
        """Return current URL."""
        return self.page.url

    async def get_page_text(self) -> str:
        """Return visible text of current page."""
        return await self.page.inner_text("body")

    async def get_element_text(self, selector: str) -> str | None:
        """Visible text of the first element matching ``selector``, or ``None``.

        ``None`` means no element matched, which is a different answer from an
        element that matched and is empty (``""``). Callers asserting on text
        need to tell those apart: the first is a stale scenario, the second is
        a page that rendered nothing.

        Not on :class:`~aat.engine.base.BaseEngine`. Scoping to a selector is a
        DOM capability, so callers probe for it the same way they probe for
        :meth:`find_text_box` -- an engine driving a native window has nothing
        truthful to return here.
        """
        locator = self.page.locator(selector).first
        if await locator.count() == 0:
            return None
        return await locator.inner_text()

    async def find_text_position(self, text: str) -> tuple[int, int] | None:
        """Centre of the element matching ``text``, or ``None``.

        A thin view over :meth:`find_text_box` so the search strategy has one
        implementation. The box itself matters to callers that want to bank a
        picture of the element for self-healing, which a centre point cannot
        describe.
        """
        box = await self.find_text_box(text)
        if box is None:
            return None
        return (
            int(box["x"] + box["width"] / 2),
            int(box["y"] + box["height"] / 2),
        )

    async def find_text_box(self, text: str) -> dict[str, float] | None:
        """Find element on page and scroll into view if needed.

        Strategy:
        1. get_by_label — input/textarea linked to label (highest priority)
        2. get_by_placeholder — placeholder text
        3. get_by_role("button") — buttons
        4. get_by_role("link") — links
        5. get_by_text — general text fallback

        Automatically scrolls elements into the viewport before returning the
        bounding box (CSS pixels, as Playwright reports it), or ``None``.
        """
        # If text looks like a CSS selector, try it directly first
        if text.startswith(("#", "[", ".")) or text.startswith("input"):
            try:
                locator = self.page.locator(text).first
                if await locator.count() > 0:
                    await locator.scroll_into_view_if_needed(timeout=3000)
                    box = await locator.bounding_box()
                    if box:
                        return _as_box(box)
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
                    return _as_box(box)
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
