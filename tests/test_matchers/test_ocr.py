"""Tests for OCRMatcher."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pandas as pd
import pytest

from aat.core.models import MatchingConfig, MatchMethod, TargetSpec
from aat.matchers.ocr import OCRMatcher

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_screenshot(width: int = 640, height: int = 480) -> bytes:
    img = np.full((height, width, 3), 255, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok  # noqa: S101
    return bytes(buf)


def _make_ocr_dataframe(
    words: list[dict[str, object]],
) -> pd.DataFrame:
    """Build a DataFrame that looks like pytesseract.image_to_data output."""
    columns = [
        "level",
        "page_num",
        "block_num",
        "par_num",
        "line_num",
        "word_num",
        "left",
        "top",
        "width",
        "height",
        "conf",
        "text",
    ]
    rows: list[dict[str, object]] = []
    for w in words:
        row: dict[str, object] = {
            "level": 5,
            "page_num": 1,
            "block_num": w.get("block_num", 1),
            "par_num": w.get("par_num", 1),
            "line_num": w.get("line_num", 1),
            "word_num": w.get("word_num", 1),
            "left": w.get("left", 100),
            "top": w.get("top", 50),
            "width": w.get("width", 80),
            "height": w.get("height", 20),
            "conf": w.get("conf", 95),
            "text": w.get("text", ""),
        }
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def screenshot_bytes() -> bytes:
    return _make_screenshot()


# ── can_handle ───────────────────────────────────────────────────────────────


class TestCanHandle:
    def test_true_when_text_provided(self) -> None:
        matcher = OCRMatcher()
        assert matcher.can_handle(TargetSpec(text="Login")) is True

    def test_false_when_no_text(self) -> None:
        matcher = OCRMatcher()
        assert matcher.can_handle(TargetSpec(image="btn.png")) is False


# ── find ─────────────────────────────────────────────────────────────────────


class TestFind:
    @pytest.mark.asyncio()
    @patch("aat.matchers.ocr.pytesseract")
    async def test_single_word_match(
        self,
        mock_tess: MagicMock,
        screenshot_bytes: bytes,
    ) -> None:
        """Single-word match returns center of bounding box."""
        df = _make_ocr_dataframe(
            [
                {
                    "text": "Login",
                    "left": 100,
                    "top": 50,
                    "width": 80,
                    "height": 20,
                    "conf": 95,
                },
            ]
        )
        mock_tess.image_to_data.return_value = df
        mock_tess.Output.DATAFRAME = "data.frame"

        config = MatchingConfig(confidence_threshold=0.5)
        matcher = OCRMatcher(config=config)
        target = TargetSpec(text="Login")
        result = await matcher.find(target, screenshot_bytes)

        assert result is not None
        assert result.found is True
        assert result.method == MatchMethod.OCR
        assert result.x == 140  # 100 + 80//2
        assert result.y == 60  # 50 + 20//2
        assert result.confidence == pytest.approx(0.95)
        assert result.elapsed_ms > 0

    @pytest.mark.asyncio()
    @patch("aat.matchers.ocr.pytesseract")
    async def test_phrase_match(
        self,
        mock_tess: MagicMock,
        screenshot_bytes: bytes,
    ) -> None:
        """Multi-word phrase match groups words on the same line."""
        df = _make_ocr_dataframe(
            [
                {
                    "text": "Sign",
                    "left": 100,
                    "top": 50,
                    "width": 40,
                    "height": 20,
                    "conf": 90,
                    "word_num": 1,
                },
                {
                    "text": "In",
                    "left": 145,
                    "top": 50,
                    "width": 30,
                    "height": 20,
                    "conf": 92,
                    "word_num": 2,
                },
            ]
        )
        mock_tess.image_to_data.return_value = df
        mock_tess.Output.DATAFRAME = "data.frame"

        config = MatchingConfig(confidence_threshold=0.5)
        matcher = OCRMatcher(config=config)
        target = TargetSpec(text="sign in")
        result = await matcher.find(target, screenshot_bytes)

        assert result is not None
        assert result.found is True

    @pytest.mark.asyncio()
    @patch("aat.matchers.ocr.pytesseract")
    async def test_no_match(
        self,
        mock_tess: MagicMock,
        screenshot_bytes: bytes,
    ) -> None:
        """Text not present in OCR output returns None."""
        df = _make_ocr_dataframe(
            [{"text": "Logout", "conf": 95}],
        )
        mock_tess.image_to_data.return_value = df
        mock_tess.Output.DATAFRAME = "data.frame"

        matcher = OCRMatcher()
        target = TargetSpec(text="Login")
        result = await matcher.find(target, screenshot_bytes)

        assert result is None

    @pytest.mark.asyncio()
    @patch("aat.matchers.ocr.pytesseract")
    async def test_low_confidence_filtered(
        self,
        mock_tess: MagicMock,
        screenshot_bytes: bytes,
    ) -> None:
        """Matches below confidence threshold are filtered out."""
        df = _make_ocr_dataframe(
            [{"text": "Login", "conf": 50}],
        )
        mock_tess.image_to_data.return_value = df
        mock_tess.Output.DATAFRAME = "data.frame"

        config = MatchingConfig(confidence_threshold=0.9)
        matcher = OCRMatcher(config=config)
        target = TargetSpec(text="Login")
        result = await matcher.find(target, screenshot_bytes)

        assert result is None

    @pytest.mark.asyncio()
    async def test_corrupt_screenshot_returns_none(self) -> None:
        """Bad screenshot bytes should not crash."""
        matcher = OCRMatcher()
        target = TargetSpec(text="Login")
        result = await matcher.find(target, b"bad-data")
        assert result is None


# ── name ─────────────────────────────────────────────────────────────────────


class TestName:
    def test_name_is_ocr(self) -> None:
        assert OCRMatcher().name == "ocr"
