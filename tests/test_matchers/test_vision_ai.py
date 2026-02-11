"""Tests for VisionAIMatcher stub."""

from __future__ import annotations

import pytest

from aat.core.models import TargetSpec
from aat.matchers.vision_ai import VisionAIMatcher


class TestVisionAIMatcher:
    def test_name(self) -> None:
        assert VisionAIMatcher().name == "vision_ai"

    def test_can_handle_returns_false(self) -> None:
        matcher = VisionAIMatcher()
        target = TargetSpec(image="test.png")
        assert matcher.can_handle(target) is False

    @pytest.mark.asyncio()
    async def test_find_returns_none(self) -> None:
        matcher = VisionAIMatcher()
        target = TargetSpec(image="test.png")
        result = await matcher.find(target, b"screenshot-data")
        assert result is None
