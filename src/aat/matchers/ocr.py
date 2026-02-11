"""OCRMatcher — pytesseract based text matching."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import cv2
import numpy as np
import pytesseract  # type: ignore[import-untyped]

from aat.core.models import MatchingConfig, MatchMethod, MatchResult
from aat.matchers.base import BaseMatcher

if TYPE_CHECKING:
    import pandas as pd  # type: ignore[import-untyped]

    from aat.core.models import TargetSpec

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG = MatchingConfig()


class OCRMatcher(BaseMatcher):
    """Find text on screen using Tesseract OCR.

    Uses ``pytesseract.image_to_data`` to locate every word/phrase
    on screen, then searches for the target text within those results.
    """

    def __init__(self, config: MatchingConfig | None = None) -> None:
        self._config = config or _DEFAULT_CONFIG

    # -- BaseMatcher interface ------------------------------------------------

    @property
    def name(self) -> str:
        return "ocr"

    def can_handle(self, target: TargetSpec) -> bool:
        """OCR matching requires target text."""
        return target.text is not None

    async def find(
        self,
        target: TargetSpec,
        screenshot: bytes,
    ) -> MatchResult | None:
        """Find *target.text* in *screenshot* via OCR."""
        start = time.perf_counter()
        try:
            return self._match(target, screenshot, start)
        except Exception:
            logger.exception("OCRMatcher.find failed")
            return None

    # -- internal helpers -----------------------------------------------------

    def _decode_image(self, raw: bytes) -> np.ndarray:
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            msg = "Failed to decode screenshot bytes"
            raise ValueError(msg)
        return img

    def _match(
        self,
        target: TargetSpec,
        screenshot: bytes,
        start: float,
    ) -> MatchResult | None:
        assert target.text is not None  # noqa: S101

        screen_bgr = self._decode_image(screenshot)
        gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)

        lang = "+".join(self._config.ocr_languages)
        data: pd.DataFrame = pytesseract.image_to_data(
            gray,
            lang=lang,
            output_type=pytesseract.Output.DATAFRAME,
        )

        search_text = target.text.strip().lower()
        threshold = (
            target.confidence
            if target.confidence is not None
            else self._config.confidence_threshold
        )

        # Try exact single-token match first
        result = self._find_single_token(data, search_text, threshold)

        # Fall back to multi-word phrase match
        if result is None:
            result = self._find_phrase(data, search_text, threshold)

        elapsed = (time.perf_counter() - start) * 1000.0

        if result is None:
            return None

        x, y, w, h, conf = result
        return MatchResult(
            found=True,
            x=x,
            y=y,
            width=w,
            height=h,
            confidence=conf,
            method=MatchMethod.OCR,
            elapsed_ms=elapsed,
        )

    def _find_single_token(
        self,
        data: pd.DataFrame,
        search_text: str,
        threshold: float,
    ) -> tuple[int, int, int, int, float] | None:
        """Look for *search_text* as a substring of individual OCR tokens."""
        valid = data[data["conf"] > 0].copy()
        if valid.empty:
            return None

        valid["text_lower"] = valid["text"].astype(str).str.strip().str.lower()

        matches = valid[valid["text_lower"].str.contains(search_text, na=False)]
        if matches.empty:
            return None

        best_idx = matches["conf"].idxmax()
        row = matches.loc[best_idx]

        conf = float(row["conf"]) / 100.0
        if conf < threshold:
            return None

        left = int(row["left"])
        top = int(row["top"])
        w = int(row["width"])
        h = int(row["height"])
        cx = left + w // 2
        cy = top + h // 2
        return cx, cy, w, h, conf

    def _find_phrase(
        self,
        data: pd.DataFrame,
        search_text: str,
        threshold: float,
    ) -> tuple[int, int, int, int, float] | None:
        """Concatenate words per text line and search for the phrase."""
        valid = data[data["conf"] > 0].copy()
        if valid.empty:
            return None

        # Group by (block_num, par_num, line_num)
        group_cols = ["block_num", "par_num", "line_num"]
        for col in group_cols:
            if col not in valid.columns:
                return None

        best: tuple[int, int, int, int, float] | None = None
        best_conf = -1.0

        for _key, group in valid.groupby(group_cols):
            line_text = " ".join(group["text"].astype(str).str.strip()).lower()
            if search_text not in line_text:
                continue

            avg_conf = float(group["conf"].mean()) / 100.0
            if avg_conf < threshold:
                continue

            left = int(group["left"].min())
            top = int(group["top"].min())
            right = int((group["left"] + group["width"]).max())
            bottom = int((group["top"] + group["height"]).max())
            w = right - left
            h = bottom - top
            cx = left + w // 2
            cy = top + h // 2

            if avg_conf > best_conf:
                best_conf = avg_conf
                best = (cx, cy, w, h, avg_conf)

        return best
