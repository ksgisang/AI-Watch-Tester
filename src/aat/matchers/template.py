"""TemplateMatcher — cv2.matchTemplate based matching."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import cv2
import numpy as np

from aat.core.models import MatchingConfig, MatchMethod, MatchResult
from aat.matchers.base import BaseMatcher

if TYPE_CHECKING:
    from aat.core.models import TargetSpec

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG = MatchingConfig()


class TemplateMatcher(BaseMatcher):
    """OpenCV template-matching implementation.

    Uses ``cv2.matchTemplate`` with ``TM_CCOEFF_NORMED``.
    Optionally performs multi-scale matching when *config.multi_scale* is True.
    """

    def __init__(self, config: MatchingConfig | None = None) -> None:
        self._config = config or _DEFAULT_CONFIG

    # -- BaseMatcher interface ------------------------------------------------

    @property
    def name(self) -> str:
        return "template"

    def can_handle(self, target: TargetSpec) -> bool:
        """Template matching requires a reference image."""
        return target.image is not None

    async def find(
        self,
        target: TargetSpec,
        screenshot: bytes,
    ) -> MatchResult | None:
        """Find *target.image* inside *screenshot* using template matching."""
        start = time.perf_counter()
        try:
            return self._match(target, screenshot, start)
        except Exception:
            logger.exception("TemplateMatcher.find failed")
            return None

    # -- internal helpers -----------------------------------------------------

    def _decode_image(self, raw: bytes) -> np.ndarray:
        """Decode raw PNG/JPEG bytes into a numpy array (BGR)."""
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            msg = "Failed to decode image bytes"
            raise ValueError(msg)
        return img

    def _to_gray(self, img: np.ndarray) -> np.ndarray:
        if len(img.shape) == 2:
            return img
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    def _match(
        self,
        target: TargetSpec,
        screenshot: bytes,
        start: float,
    ) -> MatchResult | None:
        assert target.image is not None  # guaranteed by can_handle  # noqa: S101

        # Load template from file path
        tmpl_bgr = cv2.imread(target.image, cv2.IMREAD_COLOR)
        if tmpl_bgr is None:
            logger.warning("Cannot read template image: %s", target.image)
            return None

        screen_bgr = self._decode_image(screenshot)

        if self._config.grayscale:
            screen = self._to_gray(screen_bgr)
            tmpl = self._to_gray(tmpl_bgr)
        else:
            screen = screen_bgr
            tmpl = tmpl_bgr

        threshold = (
            target.confidence
            if target.confidence is not None
            else self._config.confidence_threshold
        )

        if self._config.multi_scale:
            result = self._multi_scale_match(screen, tmpl, tmpl_bgr, threshold)
        else:
            result = self._single_scale_match(screen, tmpl, tmpl_bgr, threshold)

        elapsed = (time.perf_counter() - start) * 1000.0

        if result is None:
            return None

        x, y, w, h, confidence = result
        return MatchResult(
            found=True,
            x=x,
            y=y,
            width=w,
            height=h,
            confidence=confidence,
            method=MatchMethod.TEMPLATE,
            elapsed_ms=elapsed,
        )

    def _single_scale_match(
        self,
        screen: np.ndarray,
        tmpl: np.ndarray,
        tmpl_bgr: np.ndarray,
        threshold: float,
    ) -> tuple[int, int, int, int, float] | None:
        th, tw = tmpl.shape[:2]
        sh, sw = screen.shape[:2]
        if th > sh or tw > sw:
            return None

        res = cv2.matchTemplate(screen, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        if max_val < threshold:
            logger.debug(
                "Template single-scale: best=%.3f < threshold=%.3f",
                max_val,
                threshold,
            )
            return None

        cx = max_loc[0] + tw // 2
        cy = max_loc[1] + th // 2
        return cx, cy, tw, th, float(max_val)

    def _multi_scale_match(
        self,
        screen: np.ndarray,
        tmpl: np.ndarray,
        tmpl_bgr: np.ndarray,
        threshold: float,
    ) -> tuple[int, int, int, int, float] | None:
        th, tw = tmpl.shape[:2]
        sh, sw = screen.shape[:2]

        # Always try original scale (1.0x) first — no resize artifacts.
        original = self._single_scale_match(screen, tmpl, tmpl_bgr, threshold)
        if original is not None:
            return original

        # Build scale set, excluding 1.0 (already tried).
        best: tuple[int, int, int, int, float] | None = None
        best_conf = -1.0

        num_scales = 11
        scales = np.linspace(
            self._config.scale_range_min,
            self._config.scale_range_max,
            num_scales,
        )

        for scale in scales:
            if abs(scale - 1.0) < 0.05:
                continue  # skip near-1.0 (already tried original)

            new_w = int(tw * scale)
            new_h = int(th * scale)
            if new_w < 4 or new_h < 4 or new_w > sw or new_h > sh:
                continue

            resized = cv2.resize(tmpl, (new_w, new_h), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(screen, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            if max_val > best_conf:
                best_conf = max_val
                cx = max_loc[0] + new_w // 2
                cy = max_loc[1] + new_h // 2
                best = (cx, cy, new_w, new_h, float(max_val))

        if best is None or best[4] < threshold:
            logger.debug(
                "Template multi-scale: best=%.3f < threshold=%.3f",
                best[4] if best else 0.0,
                threshold,
            )
            return None
        return best
