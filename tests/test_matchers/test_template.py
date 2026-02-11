"""Tests for TemplateMatcher."""

from __future__ import annotations

import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

from aat.core.models import MatchingConfig, MatchMethod, TargetSpec
from aat.matchers.template import TemplateMatcher

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_screenshot(width: int = 640, height: int = 480) -> np.ndarray:
    """Create a dark-gray screenshot with a distinctive multi-color pattern."""
    img = np.full((height, width, 3), 40, dtype=np.uint8)
    # Draw a distinctive non-uniform pattern at a known position
    # so that TM_CCOEFF_NORMED can differentiate it
    cv2.rectangle(img, (200, 150), (280, 210), (255, 255, 255), -1)
    cv2.circle(img, (240, 180), 15, (0, 0, 200), -1)
    cv2.line(img, (210, 155), (270, 205), (0, 200, 0), 2)
    return img


def _encode_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    assert ok  # noqa: S101
    return bytes(buf)


def _save_template(img: np.ndarray, tmp_dir: Path) -> str:
    """Save *img* as a PNG file and return the path string."""
    path = tmp_dir / "template.png"
    cv2.imwrite(str(path), img)
    return str(path)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def screenshot_bytes() -> bytes:
    return _encode_png(_make_screenshot())


@pytest.fixture()
def tmp_dir() -> Path:
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


# ── can_handle ───────────────────────────────────────────────────────────────


class TestCanHandle:
    def test_true_when_image_provided(self) -> None:
        matcher = TemplateMatcher()
        target = TargetSpec(image="some_image.png")
        assert matcher.can_handle(target) is True

    def test_false_when_no_image(self) -> None:
        matcher = TemplateMatcher()
        target = TargetSpec(text="hello")
        assert matcher.can_handle(target) is False


# ── find ─────────────────────────────────────────────────────────────────────


class TestFind:
    @pytest.mark.asyncio()
    async def test_exact_match(
        self,
        screenshot_bytes: bytes,
        tmp_dir: Path,
    ) -> None:
        """Template that exactly matches a region should be found."""
        # Extract the white rectangle region as template
        screen = _make_screenshot()
        tmpl = screen[150:210, 200:280]
        tmpl_path = _save_template(tmpl, tmp_dir)

        config = MatchingConfig(multi_scale=False, confidence_threshold=0.8)
        matcher = TemplateMatcher(config=config)
        target = TargetSpec(image=tmpl_path)
        result = await matcher.find(target, screenshot_bytes)

        assert result is not None
        assert result.found is True
        assert result.method == MatchMethod.TEMPLATE
        assert result.confidence >= 0.8
        # Center should be near (240, 180)
        assert abs(result.x - 240) <= 5
        assert abs(result.y - 180) <= 5
        assert result.elapsed_ms > 0

    @pytest.mark.asyncio()
    async def test_multi_scale_match(
        self,
        screenshot_bytes: bytes,
        tmp_dir: Path,
    ) -> None:
        """Multi-scale matching should find a slightly scaled template."""
        screen = _make_screenshot()
        tmpl = screen[150:210, 200:280]
        tmpl_path = _save_template(tmpl, tmp_dir)

        config = MatchingConfig(
            multi_scale=True,
            scale_range_min=0.8,
            scale_range_max=1.2,
            confidence_threshold=0.7,
        )
        matcher = TemplateMatcher(config=config)
        target = TargetSpec(image=tmpl_path)
        result = await matcher.find(target, screenshot_bytes)

        assert result is not None
        assert result.found is True

    @pytest.mark.asyncio()
    async def test_no_match_low_confidence(
        self,
        screenshot_bytes: bytes,
        tmp_dir: Path,
    ) -> None:
        """A random noise template should not match."""
        rng = np.random.RandomState(42)
        noise = rng.randint(0, 256, (60, 80, 3), dtype=np.uint8)
        tmpl_path = _save_template(noise, tmp_dir)

        config = MatchingConfig(multi_scale=False, confidence_threshold=0.99)
        matcher = TemplateMatcher(config=config)
        target = TargetSpec(image=tmpl_path)
        result = await matcher.find(target, screenshot_bytes)

        assert result is None

    @pytest.mark.asyncio()
    async def test_missing_template_file(self) -> None:
        """Non-existent image path should return None, not crash."""
        matcher = TemplateMatcher()
        target = TargetSpec(image="/tmp/nonexistent_image_abc123.png")
        result = await matcher.find(target, _encode_png(_make_screenshot()))
        assert result is None

    @pytest.mark.asyncio()
    async def test_corrupt_screenshot_returns_none(
        self,
        tmp_dir: Path,
    ) -> None:
        """Corrupt screenshot bytes should return None."""
        screen = _make_screenshot()
        tmpl = screen[150:210, 200:280]
        tmpl_path = _save_template(tmpl, tmp_dir)

        matcher = TemplateMatcher()
        target = TargetSpec(image=tmpl_path)
        result = await matcher.find(target, b"not-a-png")
        assert result is None


# ── name ─────────────────────────────────────────────────────────────────────


class TestName:
    def test_name_is_template(self) -> None:
        assert TemplateMatcher().name == "template"
