"""Tests for MarkdownParser."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from aat.core.exceptions import ParserError
from aat.parsers.markdown_parser import MarkdownParser


def _make_minimal_png() -> bytes:
    """Create a minimal valid 1x1 red PNG in pure Python."""
    # IHDR
    width = 1
    height = 1
    bit_depth = 8
    color_type = 2  # RGB
    ihdr_data = struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
    ihdr_chunk = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)

    # IDAT — one row: filter byte (0) + R G B
    raw_row = b"\x00\xff\x00\x00"
    compressed = zlib.compress(raw_row)
    idat_crc = zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
    idat_chunk = (
        struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", idat_crc)
    )

    # IEND
    iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
    iend_chunk = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)

    # Signature + chunks
    return b"\x89PNG\r\n\x1a\n" + ihdr_chunk + idat_chunk + iend_chunk


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def parser() -> MarkdownParser:
    return MarkdownParser()


# ── supported_extensions ─────────────────────────────────────────────────────


class TestSupportedExtensions:
    def test_extensions(self, parser: MarkdownParser) -> None:
        assert ".md" in parser.supported_extensions
        assert ".txt" in parser.supported_extensions


# ── parse markdown ───────────────────────────────────────────────────────────


class TestParseMarkdown:
    @pytest.mark.asyncio()
    async def test_text_extraction(self, parser: MarkdownParser, tmp_path: Path) -> None:
        md_file = tmp_path / "doc.md"
        md_file.write_text("# Hello\n\nSome paragraph.", encoding="utf-8")

        text, images = await parser.parse(md_file)

        assert "# Hello" in text
        assert "Some paragraph." in text
        assert images == []

    @pytest.mark.asyncio()
    async def test_image_extraction(self, parser: MarkdownParser, tmp_path: Path) -> None:
        """Image references are loaded as bytes."""
        png_data = _make_minimal_png()
        img_file = tmp_path / "logo.png"
        img_file.write_bytes(png_data)

        md_file = tmp_path / "doc.md"
        md_file.write_text("![Logo](logo.png)\n\nText here.", encoding="utf-8")

        text, images = await parser.parse(md_file)

        assert "![Logo](logo.png)" in text
        assert len(images) == 1
        assert images[0] == png_data

    @pytest.mark.asyncio()
    async def test_multiple_images(self, parser: MarkdownParser, tmp_path: Path) -> None:
        png1 = _make_minimal_png()
        png2 = _make_minimal_png()
        (tmp_path / "a.png").write_bytes(png1)
        (tmp_path / "b.png").write_bytes(png2)

        md_file = tmp_path / "multi.md"
        md_file.write_text(
            "![A](a.png)\n![B](b.png)\n",
            encoding="utf-8",
        )

        _, images = await parser.parse(md_file)
        assert len(images) == 2

    @pytest.mark.asyncio()
    async def test_missing_image_skipped(self, parser: MarkdownParser, tmp_path: Path) -> None:
        """Missing image references are silently skipped."""
        md_file = tmp_path / "doc.md"
        md_file.write_text("![Missing](does_not_exist.png)", encoding="utf-8")

        text, images = await parser.parse(md_file)

        assert "![Missing](does_not_exist.png)" in text
        assert images == []


# ── parse txt ────────────────────────────────────────────────────────────────


class TestParseTxt:
    @pytest.mark.asyncio()
    async def test_txt_returns_text_no_images(
        self, parser: MarkdownParser, tmp_path: Path
    ) -> None:
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("Plain text content.\n![fake](img.png)", encoding="utf-8")

        text, images = await parser.parse(txt_file)

        assert "Plain text content." in text
        # .txt files should not extract images
        assert images == []


# ── error handling ───────────────────────────────────────────────────────────


class TestErrors:
    @pytest.mark.asyncio()
    async def test_nonexistent_file_raises_parser_error(self, parser: MarkdownParser) -> None:
        with pytest.raises(ParserError, match="Cannot read file"):
            await parser.parse(Path("/tmp/nonexistent_aat_test_file.md"))
