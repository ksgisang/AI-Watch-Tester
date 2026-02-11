"""FeatureMatcher — ORB/SIFT feature point matching."""

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

# Lowe's ratio test threshold
_RATIO_THRESHOLD = 0.75
# Minimum number of good matches to consider a detection valid
_MIN_GOOD_MATCHES = 8


class FeatureMatcher(BaseMatcher):
    """ORB feature-based matching with brute-force matcher.

    Detects ORB keypoints in both the template and the screenshot,
    matches them using ``cv2.BFMatcher``, and applies the ratio test
    to filter good matches.  The matched position is estimated from
    the average of matched keypoint coordinates.
    """

    def __init__(self, config: MatchingConfig | None = None) -> None:
        self._config = config or _DEFAULT_CONFIG
        self._orb = cv2.ORB_create(nfeatures=1000)  # type: ignore[attr-defined]
        self._bf = cv2.BFMatcher(cv2.NORM_HAMMING)

    # -- BaseMatcher interface ------------------------------------------------

    @property
    def name(self) -> str:
        return "feature"

    def can_handle(self, target: TargetSpec) -> bool:
        """Feature matching requires a reference image."""
        return target.image is not None

    async def find(
        self,
        target: TargetSpec,
        screenshot: bytes,
    ) -> MatchResult | None:
        """Find *target.image* in *screenshot* using ORB feature matching."""
        start = time.perf_counter()
        try:
            return self._match(target, screenshot, start)
        except Exception:
            logger.exception("FeatureMatcher.find failed")
            return None

    # -- internal helpers -----------------------------------------------------

    def _decode_image(self, raw: bytes) -> np.ndarray:
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
        assert target.image is not None  # noqa: S101

        tmpl_bgr = cv2.imread(target.image, cv2.IMREAD_COLOR)
        if tmpl_bgr is None:
            logger.warning("Cannot read template image: %s", target.image)
            return None

        screen_bgr = self._decode_image(screenshot)

        tmpl_gray = self._to_gray(tmpl_bgr)
        screen_gray = self._to_gray(screen_bgr)

        kp_tmpl, desc_tmpl = self._orb.detectAndCompute(tmpl_gray, None)
        kp_screen, desc_screen = self._orb.detectAndCompute(screen_gray, None)

        if desc_tmpl is None or desc_screen is None:
            return None
        if len(kp_tmpl) < 2 or len(kp_screen) < 2:
            return None

        # kNN matching with k=2 for ratio test
        raw_matches = self._bf.knnMatch(desc_tmpl, desc_screen, k=2)

        good_matches: list[cv2.DMatch] = []
        for pair in raw_matches:
            if len(pair) == 2:
                m, n = pair
                if m.distance < _RATIO_THRESHOLD * n.distance:
                    good_matches.append(m)

        if len(good_matches) < _MIN_GOOD_MATCHES:
            return None

        # Compute match confidence as ratio of good matches to template keypoints
        confidence = min(len(good_matches) / max(len(kp_tmpl), 1), 1.0)

        threshold = (
            target.confidence
            if target.confidence is not None
            else self._config.confidence_threshold
        )
        if confidence < threshold:
            return None

        # Estimate position: average of matched keypoints in the screenshot
        pts = np.array(
            [kp_screen[m.trainIdx].pt for m in good_matches],
            dtype=np.float32,
        )
        cx = int(np.mean(pts[:, 0]))
        cy = int(np.mean(pts[:, 1]))

        # Estimate bounding box from min/max of matched points
        x_min = int(np.min(pts[:, 0]))
        y_min = int(np.min(pts[:, 1]))
        x_max = int(np.max(pts[:, 0]))
        y_max = int(np.max(pts[:, 1]))
        w = max(x_max - x_min, 1)
        h = max(y_max - y_min, 1)

        elapsed = (time.perf_counter() - start) * 1000.0

        return MatchResult(
            found=True,
            x=cx,
            y=cy,
            width=w,
            height=h,
            confidence=confidence,
            method=MatchMethod.FEATURE,
            elapsed_ms=elapsed,
        )
