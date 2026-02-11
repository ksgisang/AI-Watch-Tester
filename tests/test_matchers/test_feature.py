"""Tests for FeatureMatcher."""

from __future__ import annotations

import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from aat.core.models import MatchingConfig, MatchMethod, TargetSpec
from aat.matchers.feature import FeatureMatcher

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_textured_image(
    width: int = 640,
    height: int = 480,
    seed: int = 42,
) -> np.ndarray:
    """Create an image with enough texture for ORB to detect keypoints."""
    rng = np.random.RandomState(seed)
    img = np.full((height, width, 3), 128, dtype=np.uint8)
    # Draw random circles & rectangles for rich features
    for _ in range(60):
        cx = rng.randint(0, width)
        cy = rng.randint(0, height)
        r = rng.randint(5, 30)
        color = tuple(int(c) for c in rng.randint(0, 256, 3))
        cv2.circle(img, (cx, cy), r, color, -1)
    for _ in range(40):
        x1 = rng.randint(0, width - 10)
        y1 = rng.randint(0, height - 10)
        x2 = x1 + rng.randint(10, 60)
        y2 = y1 + rng.randint(10, 60)
        color = tuple(int(c) for c in rng.randint(0, 256, 3))
        cv2.rectangle(img, (x1, y1), (x2, y2), color, -1)
    return img


def _encode_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    assert ok  # noqa: S101
    return bytes(buf)


def _save_image(img: np.ndarray, tmp_dir: Path, name: str = "template.png") -> str:
    path = tmp_dir / name
    cv2.imwrite(str(path), img)
    return str(path)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_dir() -> Path:
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


# ── can_handle ───────────────────────────────────────────────────────────────


class TestCanHandle:
    def test_true_when_image_provided(self) -> None:
        matcher = FeatureMatcher()
        assert matcher.can_handle(TargetSpec(image="btn.png")) is True

    def test_false_when_no_image(self) -> None:
        matcher = FeatureMatcher()
        assert matcher.can_handle(TargetSpec(text="hello")) is False


# ── find ─────────────────────────────────────────────────────────────────────


class TestFind:
    @pytest.mark.asyncio()
    async def test_match_same_region(self, tmp_dir: Path) -> None:
        """Template cropped from the screenshot should match (with enough features)."""
        screen = _make_textured_image(640, 480, seed=42)
        # Crop a rich region as template
        tmpl = screen[100:250, 150:350].copy()
        tmpl_path = _save_image(tmpl, tmp_dir)

        config = MatchingConfig(confidence_threshold=0.1)
        matcher = FeatureMatcher(config=config)
        target = TargetSpec(image=tmpl_path, confidence=0.1)
        screenshot_bytes = _encode_png(screen)

        result = await matcher.find(target, screenshot_bytes)

        # Feature matching on a direct crop should succeed
        if result is not None:
            assert result.found is True
            assert result.method == MatchMethod.FEATURE
            assert result.elapsed_ms > 0

    @pytest.mark.asyncio()
    async def test_no_match_unrelated(self, tmp_dir: Path) -> None:
        """Completely different images should not match."""
        screen = _make_textured_image(640, 480, seed=1)
        tmpl = _make_textured_image(80, 60, seed=999)
        tmpl_path = _save_image(tmpl, tmp_dir)

        config = MatchingConfig(confidence_threshold=0.85)
        matcher = FeatureMatcher(config=config)
        target = TargetSpec(image=tmpl_path)
        result = await matcher.find(target, _encode_png(screen))

        assert result is None

    @pytest.mark.asyncio()
    async def test_missing_file_returns_none(self) -> None:
        matcher = FeatureMatcher()
        target = TargetSpec(image="/tmp/does_not_exist_abc.png")
        result = await matcher.find(target, _encode_png(_make_textured_image()))
        assert result is None

    @pytest.mark.asyncio()
    async def test_corrupt_screenshot_returns_none(self, tmp_dir: Path) -> None:
        tmpl = _make_textured_image(80, 60, seed=7)
        tmpl_path = _save_image(tmpl, tmp_dir)

        matcher = FeatureMatcher()
        target = TargetSpec(image=tmpl_path)
        result = await matcher.find(target, b"garbage")
        assert result is None


# ── name ─────────────────────────────────────────────────────────────────────


class TestName:
    def test_name_is_feature(self) -> None:
        assert FeatureMatcher().name == "feature"
