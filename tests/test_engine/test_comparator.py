"""Tests for Comparator — ExpectedResult evaluation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aat.core.exceptions import StepExecutionError
from aat.core.models import AssertType, ExpectedResult
from aat.engine.comparator import Comparator


class MockEngine:
    """Mock engine for Comparator tests."""

    def __init__(
        self,
        page_text: str = "",
        url: str = "https://example.com",
        screenshot_data: bytes = b"png_data",
    ) -> None:
        self._page_text = page_text
        self._url = url
        self._screenshot_data = screenshot_data

    async def get_page_text(self) -> str:
        return self._page_text

    async def get_url(self) -> str:
        return self._url

    async def screenshot(self) -> bytes:
        return self._screenshot_data


class TestComparatorTextVisible:
    @pytest.mark.asyncio
    async def test_text_visible_pass(self) -> None:
        comparator = Comparator()
        engine = MockEngine(page_text="Welcome to the dashboard")
        expected = ExpectedResult(type=AssertType.TEXT_VISIBLE, value="dashboard")
        await comparator.check(expected, engine)  # Should not raise

    @pytest.mark.asyncio
    async def test_text_visible_fail(self) -> None:
        comparator = Comparator()
        engine = MockEngine(page_text="Welcome to the dashboard")
        expected = ExpectedResult(type=AssertType.TEXT_VISIBLE, value="login")
        with pytest.raises(StepExecutionError, match="not visible on page"):
            await comparator.check(expected, engine)


class TestComparatorTextEquals:
    @pytest.mark.asyncio
    async def test_text_equals_pass(self) -> None:
        comparator = Comparator()
        engine = MockEngine(page_text="  Hello World  ")
        expected = ExpectedResult(type=AssertType.TEXT_EQUALS, value="Hello World")
        await comparator.check(expected, engine)  # strip() then compare

    @pytest.mark.asyncio
    async def test_text_equals_fail(self) -> None:
        comparator = Comparator()
        engine = MockEngine(page_text="Hello World")
        expected = ExpectedResult(type=AssertType.TEXT_EQUALS, value="Goodbye")
        with pytest.raises(StepExecutionError, match="does not match"):
            await comparator.check(expected, engine)


class TestComparatorUrlContains:
    @pytest.mark.asyncio
    async def test_url_contains_pass(self) -> None:
        comparator = Comparator()
        engine = MockEngine(url="https://example.com/dashboard?tab=settings")
        expected = ExpectedResult(type=AssertType.URL_CONTAINS, value="dashboard")
        await comparator.check(expected, engine)

    @pytest.mark.asyncio
    async def test_url_contains_fail(self) -> None:
        comparator = Comparator()
        engine = MockEngine(url="https://example.com/login")
        expected = ExpectedResult(type=AssertType.URL_CONTAINS, value="dashboard")
        with pytest.raises(StepExecutionError, match="does not contain"):
            await comparator.check(expected, engine)


class TestComparatorImageVisible:
    @pytest.mark.asyncio
    async def test_image_visible_noop(self) -> None:
        """IMAGE_VISIBLE is a no-op in Comparator (handled by StepExecutor)."""
        comparator = Comparator()
        engine = MockEngine()
        expected = ExpectedResult(type=AssertType.IMAGE_VISIBLE, value="button.png")
        await comparator.check(expected, engine)  # Should not raise


class TestComparatorScreenshotMatch:
    @pytest.mark.asyncio
    async def test_screenshot_match_reference_not_found(self) -> None:
        comparator = Comparator()
        engine = MockEngine()
        expected = ExpectedResult(
            type=AssertType.SCREENSHOT_MATCH,
            value="/nonexistent/ref.png",
            tolerance=0.1,
        )
        with pytest.raises(StepExecutionError, match="not found"):
            await comparator.check(expected, engine)


class TestComparatorCheckAssert:
    @pytest.mark.asyncio
    async def test_check_assert_delegates_to_check(self) -> None:
        comparator = Comparator()
        engine = MockEngine(page_text="Hello World")
        step = MagicMock()
        step.expected = []  # no expected list — use inline assert_type
        step.assert_type = AssertType.TEXT_VISIBLE
        step.value = "Hello"
        await comparator.check_assert(step, engine)  # Should not raise

    @pytest.mark.asyncio
    async def test_check_assert_fail(self) -> None:
        comparator = Comparator()
        engine = MockEngine(url="https://example.com/login")
        step = MagicMock()
        step.expected = []  # no expected list — use inline assert_type
        step.assert_type = AssertType.URL_CONTAINS
        step.value = "dashboard"
        with pytest.raises(StepExecutionError):
            await comparator.check_assert(step, engine)


class TestCompareScreenshots:
    def test_compare_screenshots_missing_reference(self) -> None:
        with pytest.raises(StepExecutionError, match="not found"):
            Comparator._compare_screenshots(b"fake_png", "/nonexistent.png")
