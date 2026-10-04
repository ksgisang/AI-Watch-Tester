"""BaseEngine ABC — test engine interface.

WebEngine(Playwright), DesktopEngine(PyAutoGUI) etc. implement this.
Provides screenshot capture, mouse/keyboard control, and navigation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path  # noqa: TC003

from aat.core.models import ScreenshotSpace


class BaseEngine(ABC):
    """Test engine abstract interface."""

    # -- Coordinate spaces -------------------------------------------------
    #
    # ``click()`` takes viewport coordinates. ``screenshot()`` returns
    # whatever pixels the engine can capture, which for an engine driving the
    # OS is the whole display at its physical resolution. Those are different
    # spaces, and a point found in the second is not a valid argument to the
    # first.
    #
    # The conversion has to be the engine's answer rather than the executor's,
    # because the engine is the only object that knows where its window sits
    # on the display and how many physical pixels a logical point is worth.
    # The defaults below are the identity, which is correct for any engine
    # that screenshots its own viewport -- so an engine that does not think
    # about this gets the behaviour it already had.

    @property
    def screenshot_space(self) -> ScreenshotSpace:
        """Which space the pixels of :meth:`screenshot` are measured in.

        Defaults to the viewport. Override it when ``screenshot()`` captures
        something wider than the page, and override the two conversions below
        with it -- a space declared without a conversion is worse than no
        declaration, because callers will start trusting it.
        """
        return ScreenshotSpace.VIEWPORT

    def screenshot_to_click(self, x: int, y: int) -> tuple[int, int]:
        """Convert a point found in :meth:`screenshot` to click coordinates.

        For a screen-space engine the result is in logical screen points --
        what the OS pointer API expects -- not viewport coordinates, because
        there is no viewport the point is guaranteed to fall inside.
        """
        return (x, y)

    def viewport_to_screenshot(self, x: float, y: float) -> tuple[float, float]:
        """Convert a viewport (CSS pixel) point to :meth:`screenshot` pixels.

        The direction needed when a DOM lookup produced the element's
        rectangle and something has to be cut out of the screenshot at that
        spot -- banking a picture for self-healing, for instance.
        """
        return (x, y)

    @abstractmethod
    async def start(self) -> None:
        """Initialize engine (launch browser etc.)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Shut down engine (close browser etc.)."""
        ...

    @abstractmethod
    async def screenshot(self) -> bytes:
        """Capture current screen as PNG bytes."""
        ...

    @abstractmethod
    async def click(self, x: int, y: int) -> None:
        """Click at coordinates."""
        ...

    @abstractmethod
    async def double_click(self, x: int, y: int) -> None:
        """Double-click at coordinates."""
        ...

    @abstractmethod
    async def right_click(self, x: int, y: int) -> None:
        """Right-click at coordinates."""
        ...

    @abstractmethod
    async def type_text(self, text: str) -> None:
        """Type text at current focus."""
        ...

    @abstractmethod
    async def press_key(self, key: str) -> None:
        """Press a single key (Enter, Tab, Escape etc.)."""
        ...

    @abstractmethod
    async def key_combo(self, *keys: str) -> None:
        """Press key combination (Ctrl+A, Cmd+C etc.)."""
        ...

    @abstractmethod
    async def navigate(self, url: str) -> None:
        """Navigate to URL."""
        ...

    @abstractmethod
    async def go_back(self) -> None:
        """Go back."""
        ...

    @abstractmethod
    async def refresh(self) -> None:
        """Refresh page."""
        ...

    @abstractmethod
    async def scroll(self, x: int, y: int, delta: int) -> None:
        """Scroll at coordinates. delta > 0: down, delta < 0: up."""
        ...

    @abstractmethod
    async def move_mouse(self, x: int, y: int) -> None:
        """Move mouse pointer (no click)."""
        ...

    @abstractmethod
    async def get_url(self) -> str:
        """Return current URL."""
        ...

    @abstractmethod
    async def get_page_text(self) -> str:
        """Return visible text of current page."""
        ...

    @abstractmethod
    async def save_screenshot(self, path: Path) -> Path:
        """Save screenshot to file and return path."""
        ...

    @abstractmethod
    async def find_text_position(self, text: str) -> tuple[int, int] | None:
        """Find screen position of visible text. Returns (x, y) or None."""
        ...
