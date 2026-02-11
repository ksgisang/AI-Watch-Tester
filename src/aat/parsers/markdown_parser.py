"""MarkdownParser — .md/.txt file parser."""

from __future__ import annotations

import logging
import re
from pathlib import Path  # noqa: TC003

from aat.core.exceptions import ParserError
from aat.parsers.base import BaseParser

logger = logging.getLogger(__name__)

# Regex: ![alt text](image_path)
_IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


class MarkdownParser(BaseParser):
    """Parse markdown and plain-text files.

    Extracts text content and referenced images from ``![alt](path)`` patterns.
    """

    @property
    def supported_extensions(self) -> list[str]:
        """Supported file extensions."""
        return [".md", ".txt"]

    async def parse(self, file_path: Path) -> tuple[str, list[bytes]]:
        """Parse markdown/text file.

        Args:
            file_path: Path to the .md or .txt file.

        Returns:
            Tuple of (extracted text, list of referenced image bytes).

        Raises:
            ParserError: If the file cannot be read.
        """
        try:
            text = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            msg = f"Cannot read file: {file_path}"
            raise ParserError(msg) from exc

        # For .txt files, skip image extraction
        if file_path.suffix.lower() == ".txt":
            return text, []

        images: list[bytes] = []
        for match in _IMAGE_REF_RE.finditer(text):
            img_rel = match.group(1).strip()
            img_path = (file_path.parent / img_rel).resolve()
            try:
                img_bytes = img_path.read_bytes()
                images.append(img_bytes)
            except OSError:
                logger.warning("Referenced image not found, skipping: %s", img_path)

        return text, images
