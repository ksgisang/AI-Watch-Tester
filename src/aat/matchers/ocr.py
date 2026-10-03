"""OCRMatcher — pytesseract based text matching (no pandas required)."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
import pytesseract  # type: ignore[import-untyped]

from aat.core.models import MatchingConfig, MatchMethod, MatchResult
from aat.matchers.base import BaseMatcher

if TYPE_CHECKING:
    from aat.core.models import TargetSpec

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG = MatchingConfig()


def preprocess_for_ocr(screen_bgr: np.ndarray) -> np.ndarray:
    """Prepare a BGR screenshot for Tesseract.

    Canvas-rendered text (Flutter CanvasKit, WebGL) is anti-aliased pixels
    rather than glyphs, and small grey-on-white labels are the first thing
    Tesseract drops. CLAHE lifts the contrast, the sharpen kernel restores the
    edges anti-aliasing softened, and the 2x upscale buys Tesseract the pixel
    height it wants.

    This lives here, outside ``OCRMatcher``, because the Comparator's
    ``text_visible`` fallback needs exactly the same preparation. It ran for
    months with none of it -- plain greyscale, no upscale -- which is one of
    the four reasons that fallback never once read a Korean Flutter screen.
    """
    gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)

    # 1. CLAHE with stronger contrast (clipLimit=3.0 for Canvas text)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # 2. Sharpening filter (enhances edges of pixel-rendered text)
    sharpen_kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    gray = cv2.filter2D(gray, -1, sharpen_kernel)

    # 3. Upscale 2x for small text
    h_img, w_img = gray.shape
    return cv2.resize(gray, (w_img * 2, h_img * 2), interpolation=cv2.INTER_CUBIC)


class OCRMatcher(BaseMatcher):
    """Find text on screen using Tesseract OCR.

    Uses ``pytesseract.image_to_data`` with ``Output.DICT`` (no pandas)
    to locate every word/phrase on screen, then searches for the target
    text within those results.
    """

    def __init__(self, config: MatchingConfig | None = None) -> None:
        self._config = config or _DEFAULT_CONFIG

    @property
    def name(self) -> str:
        return "ocr"

    def can_handle(self, target: TargetSpec) -> bool:
        return target.text is not None

    async def find(
        self,
        target: TargetSpec,
        screenshot: bytes,
    ) -> MatchResult | None:
        """Find target text in screenshot using OCR."""
        if target.text is None:
            return None

        start = time.monotonic()

        try:
            screen_arr = np.frombuffer(screenshot, dtype=np.uint8)
            screen_bgr = cv2.imdecode(screen_arr, cv2.IMREAD_COLOR)
        except Exception:
            logger.debug("Failed to decode screenshot for OCR")
            return None

        if screen_bgr is None:
            return None

        # Preprocessing — enhanced for Canvas/CanvasKit rendered text
        gray = preprocess_for_ocr(screen_bgr)

        lang = "+".join(self._config.ocr_languages)

        try:
            data: dict[str, list[Any]] = pytesseract.image_to_data(
                gray,
                lang=lang,
                config="--oem 3",
                output_type=pytesseract.Output.DICT,
            )
        except Exception as e:
            logger.warning("pytesseract OCR failed: %s", e)
            return None

        search_text = target.text.strip().lower()
        threshold = (
            target.confidence
            if target.confidence is not None
            else self._config.confidence_threshold
        )

        # Collect all candidates (for debug log + match_index)
        candidates = self._find_all_candidates(data, search_text, threshold)

        # Debug log: show all candidates
        if candidates:
            for i, (cx, cy, _cw, _ch, cc) in enumerate(candidates):
                logger.debug(
                    "[OCR] candidate %d: '%s' x=%d y=%d conf=%.2f",
                    i,
                    target.text,
                    cx,
                    cy,
                    cc,
                )

        # Select by match_index (stored in self._match_index)
        idx = getattr(self, "_match_index", 0)
        if candidates:
            if idx == -1:
                result = candidates[-1]
            elif 0 <= idx < len(candidates):
                result = candidates[idx]
            else:
                result = candidates[0]
        else:
            result = None

        if result is None:
            return None

        x, y, w, h, conf = result
        elapsed = (time.monotonic() - start) * 1000

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

    def set_match_index(self, index: int) -> None:
        """Set which match to return when multiple found."""
        self._match_index = index

    def _find_all_candidates(
        self,
        data: dict[str, list[Any]],
        search_text: str,
        threshold: float,
    ) -> list[tuple[int, int, int, int, float]]:
        """Find all matching candidates, sorted by confidence desc."""
        candidates: list[tuple[int, int, int, int, float]] = []

        # Single-token candidates
        n = len(data.get("text", []))
        for i in range(n):
            conf_val = data["conf"][i]
            if not isinstance(conf_val, (int, float)) or conf_val <= 0:
                continue
            text = str(data["text"][i]).strip().lower()
            if not text or search_text not in text:
                continue
            conf = float(conf_val) / 100.0
            if conf < threshold:
                continue
            left = int(data["left"][i]) // 2
            top = int(data["top"][i]) // 2
            w = int(data["width"][i]) // 2
            h = int(data["height"][i]) // 2
            cx = left + w // 2
            cy = top + h // 2
            candidates.append((cx, cy, w, h, conf))

        # Phrase candidates (if no single-token hits)
        if not candidates:
            phrase = self._find_phrase(data, search_text, threshold)
            if phrase:
                candidates.append(phrase)

        # Sort by confidence descending
        candidates.sort(key=lambda c: c[4], reverse=True)
        return candidates

    def _find_single_token(
        self,
        data: dict[str, list[Any]],
        search_text: str,
        threshold: float,
    ) -> tuple[int, int, int, int, float] | None:
        """Look for search_text as a substring of individual OCR tokens."""
        n = len(data.get("text", []))
        if n == 0:
            return None

        best: tuple[int, int, int, int, float] | None = None
        best_conf = -1.0

        for i in range(n):
            conf_val = data["conf"][i]
            if not isinstance(conf_val, (int, float)) or conf_val <= 0:
                continue

            text = str(data["text"][i]).strip().lower()
            if not text or search_text not in text:
                continue

            conf = float(conf_val) / 100.0
            if conf < threshold:
                continue

            if conf > best_conf:
                # 2x upscale coordinates → original resolution
                left = int(data["left"][i]) // 2
                top = int(data["top"][i]) // 2
                w = int(data["width"][i]) // 2
                h = int(data["height"][i]) // 2
                cx = left + w // 2
                cy = top + h // 2
                best = (cx, cy, w, h, conf)
                best_conf = conf

        return best

    def _find_phrase(
        self,
        data: dict[str, list[Any]],
        search_text: str,
        threshold: float,
    ) -> tuple[int, int, int, int, float] | None:
        """Concatenate words per text line and search for the phrase."""
        n = len(data.get("text", []))
        if n == 0:
            return None

        # Group by (block_num, par_num, line_num)
        lines: dict[tuple[int, int, int], list[int]] = {}
        for i in range(n):
            conf_val = data["conf"][i]
            if not isinstance(conf_val, (int, float)) or conf_val <= 0:
                continue
            key = (
                int(data["block_num"][i]),
                int(data["par_num"][i]),
                int(data["line_num"][i]),
            )
            if key not in lines:
                lines[key] = []
            lines[key].append(i)

        best: tuple[int, int, int, int, float] | None = None
        best_conf = -1.0

        for _key, indices in lines.items():
            line_text = " ".join(str(data["text"][i]).strip() for i in indices).lower()
            if search_text not in line_text:
                continue

            confs = [float(data["conf"][i]) for i in indices]
            avg_conf = sum(confs) / len(confs) / 100.0
            if avg_conf < threshold:
                continue

            # Bounding box (2x upscale → original resolution)
            lefts = [int(data["left"][i]) for i in indices]
            tops = [int(data["top"][i]) for i in indices]
            rights = [int(data["left"][i]) + int(data["width"][i]) for i in indices]
            bottoms = [int(data["top"][i]) + int(data["height"][i]) for i in indices]
            left = min(lefts) // 2
            top = min(tops) // 2
            right = max(rights) // 2
            bottom = max(bottoms) // 2
            w = right - left
            h = bottom - top
            cx = left + w // 2
            cy = top + h // 2

            if avg_conf > best_conf:
                best_conf = avg_conf
                best = (cx, cy, w, h, avg_conf)

        return best
