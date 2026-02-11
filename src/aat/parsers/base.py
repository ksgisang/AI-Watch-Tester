"""BaseParser ABC — document parsing interface.

MarkdownParser, PDFParser, DocxParser etc. implement this.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path  # noqa: TC003


class BaseParser(ABC):
    """Document parser abstract interface."""

    @abstractmethod
    async def parse(self, file_path: Path) -> tuple[str, list[bytes]]:
        """Parse document into (text, images).

        Args:
            file_path: Path to document file.

        Returns:
            Tuple of (extracted text, list of extracted image PNG bytes).
        """
        ...

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """Supported file extensions: ['.md', '.txt']."""
        ...
