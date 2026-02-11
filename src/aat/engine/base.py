"""BaseEngine ABC — test engine interface.

WebEngine(Playwright), DesktopEngine(PyAutoGUI) etc. implement this.
Provides screenshot capture, mouse/keyboard control, and navigation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path  # noqa: TC003


class BaseEngine(ABC):
    """Test engine abstract interface."""

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
