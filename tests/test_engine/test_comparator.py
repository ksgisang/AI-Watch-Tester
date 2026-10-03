"""Tests for Comparator — ExpectedResult evaluation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
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


class TestComparatorTextVisibleCaseInsensitive:
    @pytest.mark.asyncio
    async def test_text_visible_case_insensitive_pass(self) -> None:
        comparator = Comparator()
        engine = MockEngine(page_text="Welcome to the Dashboard")
        expected = ExpectedResult(
            type=AssertType.TEXT_VISIBLE,
            value="dashboard",
            case_insensitive=True,
        )
        await comparator.check(expected, engine)  # Should not raise

    @pytest.mark.asyncio
    async def test_text_visible_case_insensitive_fail(self) -> None:
        comparator = Comparator()
        engine = MockEngine(page_text="Welcome to the Dashboard")
        expected = ExpectedResult(
            type=AssertType.TEXT_VISIBLE,
            value="login",
            case_insensitive=True,
        )
        with pytest.raises(StepExecutionError, match="not visible on page"):
            await comparator.check(expected, engine)

    @pytest.mark.asyncio
    async def test_text_visible_case_sensitive_fails_on_case_mismatch(self) -> None:
        comparator = Comparator()
        engine = MockEngine(page_text="Welcome to the Dashboard")
        expected = ExpectedResult(
            type=AssertType.TEXT_VISIBLE,
            value="dashboard",
            case_insensitive=False,
        )
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
        """The message names what was compared and what was found.

        It used to say only "Text does not match 'Goodbye'", which reads as if
        the page lacked the text. With no selector the comparison is against
        the entire visible page, so the usual answer is that the page had the
        text plus everything else -- and the reader cannot tell those apart
        without seeing the actual value.
        """
        comparator = Comparator()
        engine = MockEngine(page_text="Hello World")
        expected = ExpectedResult(type=AssertType.TEXT_EQUALS, value="Goodbye")
        with pytest.raises(StepExecutionError) as exc:
            await comparator.check(expected, engine)
        message = str(exc.value)
        assert "the whole page" in message
        assert "Goodbye" in message
        assert "Hello World" in message


class TestComparatorTextEqualsCaseInsensitive:
    @pytest.mark.asyncio
    async def test_text_equals_case_insensitive_pass(self) -> None:
        comparator = Comparator()
        engine = MockEngine(page_text="  Hello World  ")
        expected = ExpectedResult(
            type=AssertType.TEXT_EQUALS,
            value="hello world",
            case_insensitive=True,
        )
        await comparator.check(expected, engine)

    @pytest.mark.asyncio
    async def test_text_equals_case_insensitive_fail(self) -> None:
        comparator = Comparator()
        engine = MockEngine(page_text="Hello World")
        expected = ExpectedResult(
            type=AssertType.TEXT_EQUALS,
            value="goodbye",
            case_insensitive=True,
        )
        with pytest.raises(StepExecutionError) as exc:
            await comparator.check(expected, engine)
        assert "goodbye" in str(exc.value)


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


class TestComparatorUrlContainsCaseInsensitive:
    @pytest.mark.asyncio
    async def test_url_contains_case_insensitive_pass(self) -> None:
        comparator = Comparator()
        engine = MockEngine(url="https://example.com/Dashboard")
        expected = ExpectedResult(
            type=AssertType.URL_CONTAINS,
            value="dashboard",
            case_insensitive=True,
        )
        await comparator.check(expected, engine)

    @pytest.mark.asyncio
    async def test_url_contains_case_insensitive_fail(self) -> None:
        comparator = Comparator()
        engine = MockEngine(url="https://example.com/login")
        expected = ExpectedResult(
            type=AssertType.URL_CONTAINS,
            value="dashboard",
            case_insensitive=True,
        )
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


# -- OCR fallback for canvas-rendered text (AAT-116) ------------------------

_KOREAN_CANVAS_PNG = (
    Path(__file__).resolve().parents[1] / "fixtures" / "images"
    / "flutter_canvaskit_korean.png"
)


class CanvasEngine(MockEngine):
    """Engine whose DOM is empty but whose screenshot carries the text.

    This is what a Flutter CanvasKit page actually looks like to AWT: the
    words are pixels in a ``<canvas>``, so ``get_page_text()`` returns nothing
    and only OCR can answer the question.
    """

    def __init__(self, page: object | None = None) -> None:
        super().__init__(page_text="", screenshot_data=_KOREAN_CANVAS_PNG.read_bytes())
        if page is not None:
            self.page = page


class TestOCRFallbackOnCanvasText:
    """The fixture is a crop of a real Flutter login screen (ClasRing).

    Read with AWT's pre-AAT-116 behaviour -- plain greyscale, no upscale, no
    ``lang``, Tesseract's default PSM -- it yields the empty string. Every
    assertion below would therefore have failed before the fix, which is the
    point: these are not tests of OCR, they are tests that the four faults
    stay fixed.
    """

    @pytest.mark.asyncio
    async def test_korean_canvas_text_is_found(self) -> None:
        comparator = Comparator(["eng", "kor"])
        expected = ExpectedResult(type=AssertType.TEXT_VISIBLE, value="학원 관리 시스템")
        await comparator.check(expected, CanvasEngine())  # must not raise

    @pytest.mark.asyncio
    async def test_absent_text_still_fails(self) -> None:
        """The fallback must not turn into a rubber stamp."""
        comparator = Comparator(["eng", "kor"])
        expected = ExpectedResult(type=AssertType.TEXT_VISIBLE, value="결제 완료")
        with pytest.raises(StepExecutionError, match="not visible on page"):
            await comparator.check(expected, CanvasEngine())

    @pytest.mark.asyncio
    async def test_english_only_cannot_read_korean(self) -> None:
        """Pins the first of the four faults.

        ``Comparator`` used to call Tesseract with no ``lang`` at all, i.e.
        English. If someone removes the language plumbing again, this test is
        the one that notices -- the others would still pass by luck on a
        Latin-script page.
        """
        comparator = Comparator(["eng"])
        expected = ExpectedResult(type=AssertType.TEXT_VISIBLE, value="학원 관리 시스템")
        with pytest.raises(StepExecutionError):
            await comparator.check(expected, CanvasEngine())

    @pytest.mark.asyncio
    async def test_whitespace_differences_do_not_matter(self) -> None:
        """Tesseract spaces CJK as it pleases: '계 정 이' for '계정이'.

        Expectations are written by humans, so the comparison collapses
        whitespace on both sides rather than asking authors to guess.
        """
        comparator = Comparator(["eng", "kor"])
        expected = ExpectedResult(type=AssertType.TEXT_VISIBLE, value="학원관리시스템")
        await comparator.check(expected, CanvasEngine())

    @pytest.mark.asyncio
    async def test_default_languages_include_korean(self) -> None:
        """A bare ``Comparator()`` must not silently run as English-only.

        Eight call sites construct one, and ``MatchingConfig`` already
        defaults to ``["eng", "kor"]``; the default here mirrors it so that
        forgetting to wire a ninth call site degrades to slow, not to blind.
        """
        comparator = Comparator()
        expected = ExpectedResult(type=AssertType.TEXT_VISIBLE, value="학원 관리 시스템")
        await comparator.check(expected, CanvasEngine())

    @pytest.mark.asyncio
    async def test_dom_hit_never_reaches_ocr(self) -> None:
        """OCR is a fallback, not a tax on every passing assertion."""
        comparator = Comparator(["eng", "kor"])
        engine = MockEngine(page_text="Welcome to the dashboard")
        engine.screenshot = AsyncMock(side_effect=AssertionError("OCR was called"))  # type: ignore[method-assign]
        expected = ExpectedResult(type=AssertType.TEXT_VISIBLE, value="dashboard")
        await comparator.check(expected, engine)


class TestOCRDoesNotReadAWTsOwnOverlay:
    """``aat run`` paints a ``#awt-overlay`` progress bar on the page.

    A failing ``text_visible`` repaints that bar with the message
    ``Text '<expected>' not visible on page`` -- which contains the expected
    text. OCR reading the bar would find it and report the assertion as
    passed: a false pass manufactured by the tool out of its own complaint.
    So the bar is hidden for the duration of the capture, and put back.
    """

    @pytest.mark.asyncio
    async def test_overlay_is_hidden_then_restored(self) -> None:
        page = MagicMock()
        page.evaluate = AsyncMock(return_value=True)
        engine = CanvasEngine(page=page)
        comparator = Comparator(["eng", "kor"])
        expected = ExpectedResult(type=AssertType.TEXT_VISIBLE, value="학원 관리 시스템")
        await comparator.check(expected, engine)

        scripts = [c.args[0] for c in page.evaluate.call_args_list]
        assert len(scripts) == 2, "expected one hide and one restore"
        assert "display = 'none'" in scripts[0]
        assert "awtPrevDisplay" in scripts[1]

    @pytest.mark.asyncio
    async def test_overlay_restored_even_when_text_absent(self) -> None:
        """The failure path is exactly where leaving it hidden would hurt:
        the user would get an evidence screenshot with no progress bar."""
        page = MagicMock()
        page.evaluate = AsyncMock(return_value=True)
        engine = CanvasEngine(page=page)
        comparator = Comparator(["eng", "kor"])
        expected = ExpectedResult(type=AssertType.TEXT_VISIBLE, value="결제 완료")
        with pytest.raises(StepExecutionError):
            await comparator.check(expected, engine)
        assert page.evaluate.call_count == 2

    @pytest.mark.asyncio
    async def test_page_without_overlay_support_still_works(self) -> None:
        """A DesktopEngine or a closed page must not break the fallback."""
        page = MagicMock()
        page.evaluate = AsyncMock(side_effect=RuntimeError("page closed"))
        engine = CanvasEngine(page=page)
        comparator = Comparator(["eng", "kor"])
        expected = ExpectedResult(type=AssertType.TEXT_VISIBLE, value="학원 관리 시스템")
        await comparator.check(expected, engine)


class TestOCRImageVariants:
    """Two images are tried, cheapest first.

    Measured on one real screenshot, preprocessing rescued one phrase and
    cost another, so neither variant can be dropped. The order is the part
    worth pinning: plain greyscale is a quarter of the pixels of the 2x
    upscale and took about half the OCR time, so a page that matches on the
    first one never pays for the second.
    """

    def test_plain_greyscale_comes_first(self) -> None:
        img = cv2.imread(str(_KOREAN_CANVAS_PNG))
        variants = list(Comparator._image_variants(img))
        assert len(variants) == 2
        assert variants[0].shape == img.shape[:2]
        assert variants[1].shape == (img.shape[0] * 2, img.shape[1] * 2)

    def test_second_variant_is_not_built_unless_needed(self) -> None:
        """The generator must stay lazy, or the saving is imaginary."""
        img = cv2.imread(str(_KOREAN_CANVAS_PNG))
        gen = Comparator._image_variants(img)
        with patch("aat.matchers.ocr.preprocess_for_ocr") as spy:
            next(gen)
            assert spy.call_count == 0
