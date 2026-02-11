"""Tests for LearnedMatcher."""

from __future__ import annotations

import hashlib
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from aat.core.models import LearnedElement, MatchMethod, TargetSpec
from aat.learning.matcher import LearnedMatcher


def _make_element(**overrides: object) -> LearnedElement:
    defaults: dict[str, object] = {
        "id": 1,
        "scenario_id": "SC-001",
        "step_number": 1,
        "target_name": "btn.png",
        "screenshot_hash": "somehash",
        "correct_x": 100,
        "correct_y": 200,
        "cropped_image_path": "/tmp/crop.png",
        "confidence": 0.95,
        "use_count": 0,
        "created_at": datetime(2025, 1, 1),
        "updated_at": datetime(2025, 1, 1),
    }
    defaults.update(overrides)
    return LearnedElement(**defaults)  # type: ignore[arg-type]


# ── can_handle ───────────────────────────────────────────────────────────────


class TestCanHandle:
    def test_always_true_for_image_target(self) -> None:
        store = MagicMock()
        matcher = LearnedMatcher(store=store)
        target = TargetSpec(image="btn.png")
        assert matcher.can_handle(target) is True

    def test_always_true_for_text_target(self) -> None:
        store = MagicMock()
        matcher = LearnedMatcher(store=store)
        target = TargetSpec(text="Login")
        assert matcher.can_handle(target) is True


# ── find ─────────────────────────────────────────────────────────────────────


class TestFind:
    @pytest.mark.asyncio()
    async def test_match_found(self) -> None:
        screenshot = b"fake-screenshot-bytes"
        expected_hash = hashlib.md5(screenshot).hexdigest()  # noqa: S324

        element = _make_element(
            screenshot_hash=expected_hash,
            target_name="btn.png",
        )

        store = MagicMock()
        store.find_by_hash.return_value = [element]
        store.increment_use_count.return_value = None

        matcher = LearnedMatcher(store=store)
        target = TargetSpec(image="btn.png")

        result = await matcher.find(target, screenshot)

        assert result is not None
        assert result.found is True
        assert result.x == 100
        assert result.y == 200
        assert result.confidence == 0.95
        assert result.method == MatchMethod.LEARNED
        store.increment_use_count.assert_called_once_with(1)

    @pytest.mark.asyncio()
    async def test_match_not_found(self) -> None:
        store = MagicMock()
        store.find_by_hash.return_value = []

        matcher = LearnedMatcher(store=store)
        target = TargetSpec(image="unknown.png")

        result = await matcher.find(target, b"some-screenshot")
        assert result is None

    @pytest.mark.asyncio()
    async def test_match_found_by_text(self) -> None:
        screenshot = b"test-bytes"
        expected_hash = hashlib.md5(screenshot).hexdigest()  # noqa: S324

        element = _make_element(
            screenshot_hash=expected_hash,
            target_name="Login",
        )

        store = MagicMock()
        store.find_by_hash.return_value = [element]

        matcher = LearnedMatcher(store=store)
        target = TargetSpec(text="Login")

        result = await matcher.find(target, screenshot)
        assert result is not None
        assert result.found is True


# ── name ─────────────────────────────────────────────────────────────────────


class TestName:
    def test_name_is_learned(self) -> None:
        store = MagicMock()
        assert LearnedMatcher(store=store).name == "learned"
