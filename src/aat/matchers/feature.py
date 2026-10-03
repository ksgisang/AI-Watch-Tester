"""FeatureMatcher — ORB feature point matching.

ORB only. SIFT is not implemented; earlier docs said "ORB/SIFT", which promised
a rotation- and scale-robustness this matcher does not have.
"""

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

        threshold = (
            target.confidence
            if target.confidence is not None
            else self._config.confidence_threshold
        )

        # RANSAC 호모그래피로 정확한 위치 추정 (반복 패턴 오검출 방지)
        src_pts = np.array(
            [kp_tmpl[m.queryIdx].pt for m in good_matches], dtype=np.float32
        ).reshape(-1, 1, 2)
        dst_pts = np.array(
            [kp_screen[m.trainIdx].pt for m in good_matches], dtype=np.float32
        ).reshape(-1, 1, 2)

        h_matrix, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)

        homography_ok = False
        if h_matrix is not None:
            # 템플릿 코너를 스크린샷 공간으로 변환하여 바운딩 박스 계산
            h_tmpl, w_tmpl = tmpl_gray.shape[:2]
            corners = np.array(
                [[0, 0], [w_tmpl, 0], [w_tmpl, h_tmpl], [0, h_tmpl]], dtype=np.float32
            ).reshape(-1, 1, 2)
            transformed = cv2.perspectiveTransform(corners, h_matrix)
            pts = transformed.reshape(-1, 2)

            _min = pts.min(axis=0).astype(int)
            _max = pts.max(axis=0).astype(int)
            x_min, y_min = int(_min[0]), int(_min[1])
            x_max, y_max = int(_max[0]), int(_max[1])
            w = x_max - x_min
            h = y_max - y_min

            # 변환 결과가 퇴화(degenerate)하면 폴백
            if w > 0 and h > 0:
                cx = (x_min + x_max) // 2
                cy = (y_min + y_max) // 2
                inlier_ratio = float(mask.sum()) / len(mask) if mask is not None else 0.0
                confidence = min(1.0, inlier_ratio * (len(good_matches) / _MIN_GOOD_MATCHES))
                homography_ok = True

        if not homography_ok:
            # 폴백: 매칭 키포인트 평균으로 위치 추정
            fallback_pts = np.array(
                [kp_screen[m.trainIdx].pt for m in good_matches],
                dtype=np.float32,
            )
            cx = int(np.mean(fallback_pts[:, 0]))
            cy = int(np.mean(fallback_pts[:, 1]))
            x_min = int(np.min(fallback_pts[:, 0]))
            y_min = int(np.min(fallback_pts[:, 1]))
            x_max = int(np.max(fallback_pts[:, 0]))
            y_max = int(np.max(fallback_pts[:, 1]))
            w = max(x_max - x_min, 1)
            h = max(y_max - y_min, 1)
            confidence = min(len(good_matches) / max(len(kp_tmpl), 1), 1.0)

        if confidence < threshold:
            return None

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
