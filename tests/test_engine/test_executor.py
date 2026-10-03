"""Tests for StepExecutor — individual test step runner.

Uses mock dependencies to test all ActionType dispatching.
"""

from __future__ import annotations

import itertools
import logging
import os
import time
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import cv2
import numpy as np
import pytest

from aat.core.exceptions import CriticalStepError, StepExecutionError
from aat.core.models import (
    ActionType,
    AssertType,
    ExpectedResult,
    MatchingConfig,
    MatchMethod,
    MatchResult,
    StepConfig,
    StepStatus,
    TargetSpec,
)
from aat.engine.executor import _SYNONYMS, StepExecutor, _parse_coordinates, _parse_scroll_params
from aat.matchers import template_store

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


# ─── Fixtures ────────────────────────────────────────────────


def _png(shade: int) -> bytes:
    """A real PNG the executor's change detection can decode."""
    return bytes(cv2.imencode(".png", np.full((40, 40), shade, dtype=np.uint8))[1])


def _screen_that_reacts() -> Callable[[], bytes]:
    """Screenshots that differ from one call to the next.

    The executor now judges a click by whether the screen moved, so a mock that
    returns one frozen image is claiming every click did nothing.
    """
    shades = itertools.cycle((0, 255))
    return lambda: _png(next(shades))


def _a_browser_that_moves(engine: MagicMock, start: str = "https://example.com/page") -> None:
    """Wire the mock's URL to follow its own ``navigate()`` calls.

    The executor now judges a navigation by where the browser landed, so a mock
    whose ``get_url`` is a constant is claiming every navigate went nowhere —
    the same trap ``_screen_that_reacts`` avoids for screenshots.
    """
    location = {"url": start}

    async def _navigate(url: str, *_args: object, **_kwargs: object) -> None:
        location["url"] = url

    async def _get_url() -> str:
        return location["url"]

    engine.navigate = AsyncMock(side_effect=_navigate)
    engine.get_url = AsyncMock(side_effect=_get_url)


@pytest.fixture
def mock_engine() -> MagicMock:
    engine = MagicMock()
    engine.navigate = AsyncMock()
    engine.click = AsyncMock()
    engine.double_click = AsyncMock()
    engine.right_click = AsyncMock()
    engine.type_text = AsyncMock()
    engine.press_key = AsyncMock()
    engine.key_combo = AsyncMock()
    engine.scroll = AsyncMock()
    engine.go_back = AsyncMock()
    engine.refresh = AsyncMock()
    engine.screenshot = AsyncMock(side_effect=_screen_that_reacts())
    engine.save_screenshot = AsyncMock()
    engine.get_page_text = AsyncMock(return_value="Page text")
    _a_browser_that_moves(engine)
    engine.find_text_position = AsyncMock(return_value=None)
    # Explicitly remove attributes so hasattr() returns False
    # (MagicMock auto-creates any attribute, breaking the screen-coord code path)
    del engine.find_on_screen
    del engine.scroll_to_top
    del engine.force_click_by_text
    # Same reason: an auto-created `find_text_box` is a MagicMock, and awaiting
    # one raises. Engines that can report a rectangle set it deliberately —
    # see TestVisualBaselineBanking.
    del engine.find_text_box
    # fast_mode must be False so executor doesn't short-circuit with MatchError
    engine._config = MagicMock(fast_mode=False)
    return engine


@pytest.fixture
def mock_matcher() -> MagicMock:
    matcher = MagicMock()
    matcher.find = AsyncMock(return_value=MatchResult(found=True, x=100, y=200, confidence=0.95))
    return matcher


@pytest.fixture
def mock_humanizer() -> MagicMock:
    humanizer = MagicMock()
    humanizer.move_to = AsyncMock()
    humanizer.type_text = AsyncMock()
    return humanizer


@pytest.fixture
def mock_waiter() -> MagicMock:
    waiter = MagicMock()
    waiter.wait_until_stable = AsyncMock(return_value=True)
    return waiter


@pytest.fixture
def mock_comparator() -> MagicMock:
    comparator = MagicMock()
    comparator.check = AsyncMock()
    comparator.check_assert = AsyncMock()
    return comparator


@pytest.fixture
def executor(
    mock_engine: MagicMock,
    mock_matcher: MagicMock,
    mock_humanizer: MagicMock,
    mock_waiter: MagicMock,
    mock_comparator: MagicMock,
    tmp_path: Path,
) -> StepExecutor:
    return StepExecutor(
        engine=mock_engine,
        matcher=mock_matcher,
        humanizer=mock_humanizer,
        waiter=mock_waiter,
        comparator=mock_comparator,
        screenshot_dir=tmp_path,
    )


# ─── Helper ──────────────────────────────────────────────────


def make_step(
    action: ActionType,
    value: str | None = None,
    target: TargetSpec | None = None,
    humanize: bool = False,
    optional: bool = False,
    assert_type: AssertType | None = None,
    screenshot_before: bool = False,
    screenshot_after: bool = False,
    expected: list[ExpectedResult] | None = None,
) -> StepConfig:
    kwargs: dict = {
        "step": 1,
        "action": action,
        "description": f"Test {action.value}",
        "humanize": humanize,
        "optional": optional,
        "screenshot_before": screenshot_before,
        "screenshot_after": screenshot_after,
    }
    if value is not None:
        kwargs["value"] = value
    if target is not None:
        kwargs["target"] = target
    if assert_type is not None:
        kwargs["assert_type"] = assert_type
    if expected is not None:
        kwargs["expected"] = expected
    return StepConfig(**kwargs)


# ─── Parse functions ─────────────────────────────────────────


class TestParseCoordinates:
    def test_valid(self) -> None:
        assert _parse_coordinates("100,200") == (100, 200)

    def test_with_spaces(self) -> None:
        assert _parse_coordinates(" 100 , 200 ") == (100, 200)

    def test_none_raises(self) -> None:
        with pytest.raises(StepExecutionError):
            _parse_coordinates(None)

    def test_invalid_format(self) -> None:
        with pytest.raises(StepExecutionError, match="Invalid coordinate format"):
            _parse_coordinates("100,200,300")

    def test_non_numeric(self) -> None:
        with pytest.raises(StepExecutionError, match="Invalid coordinate values"):
            _parse_coordinates("abc,def")


class TestParseScrollParams:
    def test_valid(self) -> None:
        assert _parse_scroll_params("100,200,300") == (100, 200, 300)

    def test_none_raises(self) -> None:
        with pytest.raises(StepExecutionError):
            _parse_scroll_params(None)

    def test_invalid_format(self) -> None:
        with pytest.raises(StepExecutionError, match="Invalid scroll format"):
            _parse_scroll_params("100,200")

    def test_non_numeric(self) -> None:
        with pytest.raises(StepExecutionError, match="Invalid scroll values"):
            _parse_scroll_params("a,b,c")


# ─── Navigation / Direct actions ─────────────────────────────


class TestNavigateAction:
    @pytest.mark.asyncio
    async def test_navigate(self, executor: StepExecutor, mock_engine: MagicMock) -> None:
        step = make_step(ActionType.NAVIGATE, value="https://test.com")
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_engine.navigate.assert_awaited_once_with("https://test.com")


class TestClickAtAction:
    @pytest.mark.asyncio
    async def test_click_at(self, executor: StepExecutor, mock_engine: MagicMock) -> None:
        step = make_step(ActionType.CLICK_AT, value="100,200")
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_engine.click.assert_awaited_once_with(100, 200)

    @pytest.mark.asyncio
    async def test_click_at_with_humanize(
        self, executor: StepExecutor, mock_humanizer: MagicMock, mock_engine: MagicMock
    ) -> None:
        step = make_step(ActionType.CLICK_AT, value="50,60", humanize=True)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_humanizer.move_to.assert_awaited_once()
        mock_engine.click.assert_awaited_once_with(50, 60)


class TestTypeTextAction:
    @pytest.mark.asyncio
    async def test_type_text(self, executor: StepExecutor, mock_engine: MagicMock) -> None:
        step = make_step(ActionType.TYPE_TEXT, value="hello")
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_engine.type_text.assert_awaited_once_with("hello")

    @pytest.mark.asyncio
    async def test_type_text_humanized(
        self, executor: StepExecutor, mock_humanizer: MagicMock
    ) -> None:
        step = make_step(ActionType.TYPE_TEXT, value="hello", humanize=True)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_humanizer.type_text.assert_awaited_once()


class TestPressKeyAction:
    @pytest.mark.asyncio
    async def test_press_key(self, executor: StepExecutor, mock_engine: MagicMock) -> None:
        step = make_step(ActionType.PRESS_KEY, value="Enter")
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_engine.press_key.assert_awaited_once_with("Enter")


class TestKeyComboAction:
    @pytest.mark.asyncio
    async def test_key_combo(self, executor: StepExecutor, mock_engine: MagicMock) -> None:
        step = make_step(ActionType.KEY_COMBO, value="Control+a")
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_engine.key_combo.assert_awaited_once_with("Control", "a")


class TestAssertAction:
    @pytest.mark.asyncio
    async def test_assert(self, executor: StepExecutor, mock_comparator: MagicMock) -> None:
        step = make_step(ActionType.ASSERT, value="dashboard", assert_type=AssertType.URL_CONTAINS)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_comparator.check_assert.assert_awaited_once()


class TestWaitAction:
    @pytest.mark.asyncio
    async def test_wait(self, executor: StepExecutor) -> None:
        step = make_step(ActionType.WAIT, value="10")  # 10ms
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED


class TestScrollAction:
    @pytest.mark.asyncio
    async def test_scroll(self, executor: StepExecutor, mock_engine: MagicMock) -> None:
        step = make_step(ActionType.SCROLL, value="100,200,300")
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_engine.scroll.assert_awaited_once_with(100, 200, 300)


class TestGoBackAction:
    @pytest.mark.asyncio
    async def test_go_back(self, executor: StepExecutor, mock_engine: MagicMock) -> None:
        step = make_step(ActionType.GO_BACK)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_engine.go_back.assert_awaited_once()


class TestRefreshAction:
    @pytest.mark.asyncio
    async def test_refresh(self, executor: StepExecutor, mock_engine: MagicMock) -> None:
        step = make_step(ActionType.REFRESH)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_engine.refresh.assert_awaited_once()


class TestScreenshotAction:
    @pytest.mark.asyncio
    async def test_screenshot(self, executor: StepExecutor, mock_engine: MagicMock) -> None:
        step = make_step(ActionType.SCREENSHOT)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_engine.save_screenshot.assert_awaited_once()


# ─── find_and_* actions ──────────────────────────────────────


class TestFindAndClickAction:
    @pytest.mark.asyncio
    async def test_find_and_click(
        self,
        executor: StepExecutor,
        mock_engine: MagicMock,
        mock_matcher: MagicMock,
        mock_waiter: MagicMock,
    ) -> None:
        target = TargetSpec(image="button.png")
        step = make_step(ActionType.FIND_AND_CLICK, target=target, humanize=False)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        assert result.match_result is not None
        assert result.match_result.found is True
        mock_engine.click.assert_awaited_once_with(100, 200)

    @pytest.mark.asyncio
    async def test_find_and_click_not_found(
        self, executor: StepExecutor, mock_matcher: MagicMock
    ) -> None:
        mock_matcher.find = AsyncMock(return_value=None)
        target = TargetSpec(image="missing.png")
        step = make_step(ActionType.FIND_AND_CLICK, target=target)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.FAILED
        assert "not found" in (result.error_message or "")


class TestFindAndClickScreenCoords:
    """Test find_and_click using PyAutoGUI screen-coordinate path."""

    @pytest.mark.asyncio
    async def test_find_and_click_via_screen(
        self,
        mock_matcher: MagicMock,
        mock_humanizer: MagicMock,
        mock_waiter: MagicMock,
        mock_comparator: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When engine has find_on_screen and image target, use screen coords."""
        engine = MagicMock()
        engine.find_on_screen = AsyncMock(return_value=(500, 300))
        engine.click_on_screen = AsyncMock()
        engine.screenshot = AsyncMock(side_effect=_screen_that_reacts())
        engine.save_screenshot = AsyncMock()
        engine.find_text_position = AsyncMock(return_value=None)
        executor = StepExecutor(
            engine=engine,
            matcher=mock_matcher,
            humanizer=mock_humanizer,
            waiter=mock_waiter,
            comparator=mock_comparator,
            screenshot_dir=tmp_path,
        )
        target = TargetSpec(image="button.png")
        step = make_step(ActionType.FIND_AND_CLICK, target=target, humanize=False)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        assert result.match_result is not None
        assert result.match_result.x == 500
        assert result.match_result.y == 300
        engine.find_on_screen.assert_awaited_once()
        engine.click_on_screen.assert_awaited_once_with(500, 300)
        # Regular matcher should NOT be called
        mock_matcher.find.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_find_on_screen_miss_falls_through(
        self,
        mock_matcher: MagicMock,
        mock_humanizer: MagicMock,
        mock_waiter: MagicMock,
        mock_comparator: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When find_on_screen returns None, fall through to matcher."""
        engine = MagicMock()
        engine.find_on_screen = AsyncMock(return_value=None)
        engine.click = AsyncMock()
        engine.screenshot = AsyncMock(side_effect=_screen_that_reacts())
        engine.save_screenshot = AsyncMock()
        engine.find_text_position = AsyncMock(return_value=None)
        engine._config = MagicMock(fast_mode=False)
        executor = StepExecutor(
            engine=engine,
            matcher=mock_matcher,
            humanizer=mock_humanizer,
            waiter=mock_waiter,
            comparator=mock_comparator,
            screenshot_dir=tmp_path,
        )
        target = TargetSpec(image="button.png")
        step = make_step(ActionType.FIND_AND_CLICK, target=target, humanize=False)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        # Fell through to screenshot+matcher
        mock_matcher.find.assert_awaited_once()
        engine.click.assert_awaited_once_with(100, 200)


class TestFindAndDoubleClickAction:
    @pytest.mark.asyncio
    async def test_find_and_double_click(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        target = TargetSpec(image="icon.png")
        step = make_step(ActionType.FIND_AND_DOUBLE_CLICK, target=target, humanize=False)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_engine.double_click.assert_awaited_once_with(100, 200)


class TestFindAndRightClickAction:
    @pytest.mark.asyncio
    async def test_find_and_right_click(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        target = TargetSpec(image="menu.png")
        step = make_step(ActionType.FIND_AND_RIGHT_CLICK, target=target, humanize=False)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_engine.right_click.assert_awaited_once_with(100, 200)


class TestFindAndTypeAction:
    @pytest.mark.asyncio
    async def test_find_and_type(self, executor: StepExecutor, mock_engine: MagicMock) -> None:
        target = TargetSpec(text="Username")
        step = make_step(ActionType.FIND_AND_TYPE, target=target, value="admin", humanize=False)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_engine.click.assert_awaited_once_with(100, 200)
        mock_engine.type_text.assert_awaited_once_with("admin")


class TestFindAndClearAction:
    @pytest.mark.asyncio
    async def test_find_and_clear(self, executor: StepExecutor, mock_engine: MagicMock) -> None:
        target = TargetSpec(text="Field")
        step = make_step(ActionType.FIND_AND_CLEAR, target=target, humanize=False)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_engine.click.assert_awaited_once_with(100, 200)
        mock_engine.key_combo.assert_awaited_once_with("Control", "a")
        mock_engine.press_key.assert_awaited_once_with("Delete")


# ─── assert_text ─────────────────────────────────────────────


def _page_with_text(*, count: int, inner: str = "", found_by_text: bool = False) -> MagicMock:
    """Build a Playwright-like page for the DOM side of assert_text."""
    locator = MagicMock()
    locator.count = AsyncMock(return_value=count)
    locator.inner_text = AsyncMock(return_value=inner)
    by_text = MagicMock()
    by_text.count = AsyncMock(return_value=1 if found_by_text else 0)
    page = MagicMock()
    page.locator = MagicMock(return_value=MagicMock(first=locator))
    page.get_by_text = MagicMock(return_value=MagicMock(first=by_text))
    return page


class TestAssertTextAction:
    @pytest.mark.asyncio
    async def test_selector_match_skips_ocr(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        mock_engine.page = _page_with_text(count=1, inner="Saved successfully")
        ocr = AsyncMock()
        executor._verify_text_on_screen = ocr  # type: ignore[method-assign]
        step = make_step(ActionType.ASSERT_TEXT, target=TargetSpec(selector="#msg", text="saved"))
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        ocr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_selector_holds_other_text_fails(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        mock_engine.page = _page_with_text(count=1, inner="Something went wrong")
        executor._verify_text_on_screen = AsyncMock()  # type: ignore[method-assign]
        step = make_step(ActionType.ASSERT_TEXT, target=TargetSpec(selector="#msg", text="Saved"))
        result = await executor.execute_step(step)
        assert result.status == StepStatus.FAILED
        assert "Something went wrong" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_author_message_keeps_the_actual_cause(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        mock_engine.page = _page_with_text(count=1, inner="Something went wrong")
        executor._verify_text_on_screen = AsyncMock()  # type: ignore[method-assign]
        step = StepConfig(
            step=7,
            action=ActionType.ASSERT_TEXT,
            description="Success banner is shown",
            target=TargetSpec(selector="#msg", text="Saved"),
            message="Save succeeded",
        )
        result = await executor.execute_step(step)
        assert result.status == StepStatus.FAILED
        error = result.error_message or ""
        assert "Save succeeded" in error
        assert "actual cause:" in error
        assert "Something went wrong" in error

    @pytest.mark.asyncio
    async def test_missing_selector_falls_back_to_ocr(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        mock_engine.page = _page_with_text(count=0)
        ocr = AsyncMock()
        executor._verify_text_on_screen = ocr  # type: ignore[method-assign]
        step = make_step(ActionType.ASSERT_TEXT, target=TargetSpec(selector="#msg", text="Saved"))
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        ocr.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_without_selector_page_text_skips_ocr(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        mock_engine.page = _page_with_text(count=0, found_by_text=True)
        ocr = AsyncMock()
        executor._verify_text_on_screen = ocr  # type: ignore[method-assign]
        step = make_step(ActionType.ASSERT_TEXT, target=TargetSpec(text="Saved"))
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        ocr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_without_selector_falls_back_to_ocr(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        mock_engine.page = _page_with_text(count=0, found_by_text=False)
        ocr = AsyncMock()
        executor._verify_text_on_screen = ocr  # type: ignore[method-assign]
        step = make_step(ActionType.ASSERT_TEXT, target=TargetSpec(text="Saved"))
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        ocr.assert_awaited_once()


# ─── select_option ───────────────────────────────────────────


def _page_with_select(accepts: str) -> tuple[MagicMock, MagicMock]:
    """Build a Playwright-like page whose <select> answers to one kwarg only.

    `accepts` is `label`, `value`, `index`, or `none` for an element that
    refuses every form, which is what a wrong option name looks like.
    """
    locator = MagicMock()
    locator.wait_for = AsyncMock()
    locator.scroll_into_view_if_needed = AsyncMock()

    async def select_option(**kwargs: object) -> None:
        for key in ("label", "value", "index"):
            if key in kwargs:
                if key != accepts:
                    msg = f"no option matching {key}"
                    raise RuntimeError(msg)
                return
        msg = "nothing to select"
        raise RuntimeError(msg)

    locator.select_option = AsyncMock(side_effect=select_option)
    page = MagicMock()
    page.locator = MagicMock(return_value=MagicMock(first=locator))
    return page, locator


class TestSelectOptionAction:
    @pytest.mark.asyncio
    async def test_select_by_label(self, executor: StepExecutor, mock_engine: MagicMock) -> None:
        page, locator = _page_with_select("label")
        mock_engine.page = page
        step = make_step(
            ActionType.SELECT_OPTION, value="Grade 3", target=TargetSpec(selector="#grade")
        )
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        page.locator.assert_called_once_with("#grade")
        locator.select_option.assert_awaited_once()
        assert locator.select_option.await_args.kwargs["label"] == "Grade 3"

    @pytest.mark.asyncio
    async def test_falls_back_to_value(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        page, locator = _page_with_select("value")
        mock_engine.page = page
        step = make_step(
            ActionType.SELECT_OPTION, value="g3", target=TargetSpec(selector="#grade")
        )
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        assert locator.select_option.await_count == 2
        assert locator.select_option.await_args.kwargs["value"] == "g3"

    @pytest.mark.asyncio
    async def test_falls_back_to_index_when_numeric(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        page, locator = _page_with_select("index")
        mock_engine.page = page
        step = make_step(ActionType.SELECT_OPTION, value="2", target=TargetSpec(selector="#grade"))
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        assert locator.select_option.await_count == 3
        assert locator.select_option.await_args.kwargs["index"] == 2

    @pytest.mark.asyncio
    async def test_fails_when_no_form_matches(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        page, _ = _page_with_select("none")
        mock_engine.page = page
        step = make_step(
            ActionType.SELECT_OPTION, value="Grade 9", target=TargetSpec(selector="#grade")
        )
        result = await executor.execute_step(step)
        assert result.status == StepStatus.FAILED
        assert "select_option failed" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_fails_without_a_playwright_page(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        del mock_engine.page
        step = make_step(
            ActionType.SELECT_OPTION, value="Grade 3", target=TargetSpec(selector="#grade")
        )
        result = await executor.execute_step(step)
        assert result.status == StepStatus.FAILED
        assert "Playwright page" in (result.error_message or "")


# ─── Screenshots & Expected ─────────────────────────────────


class TestScreenshotBeforeAfter:
    @pytest.mark.asyncio
    async def test_screenshot_before(self, executor: StepExecutor, mock_engine: MagicMock) -> None:
        step = make_step(ActionType.GO_BACK, screenshot_before=True)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        assert result.screenshot_before is not None
        assert "before_" in result.screenshot_before

    @pytest.mark.asyncio
    async def test_screenshot_after(self, executor: StepExecutor, mock_engine: MagicMock) -> None:
        step = make_step(ActionType.GO_BACK, screenshot_after=True)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        assert result.screenshot_after is not None
        assert "after_" in result.screenshot_after


class TestExpectedResults:
    @pytest.mark.asyncio
    async def test_expected_checked_on_success(
        self, executor: StepExecutor, mock_comparator: MagicMock
    ) -> None:
        expected = [ExpectedResult(type=AssertType.TEXT_VISIBLE, value="Welcome")]
        step = make_step(ActionType.GO_BACK, expected=expected)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_comparator.check.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_expected_failure_marks_failed(
        self, executor: StepExecutor, mock_comparator: MagicMock
    ) -> None:
        mock_comparator.check = AsyncMock(
            side_effect=StepExecutionError("fail", step=1, action="assert")
        )
        expected = [ExpectedResult(type=AssertType.TEXT_VISIBLE, value="Missing")]
        step = make_step(ActionType.GO_BACK, expected=expected)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.FAILED


# ─── Error handling ──────────────────────────────────────────


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_optional_step_skipped_on_error(
        self, executor: StepExecutor, mock_matcher: MagicMock
    ) -> None:
        mock_matcher.find = AsyncMock(return_value=None)
        target = TargetSpec(image="optional.png")
        step = make_step(ActionType.FIND_AND_CLICK, target=target, optional=True)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_elapsed_time_recorded(self, executor: StepExecutor) -> None:
        step = make_step(ActionType.GO_BACK)
        result = await executor.execute_step(step)
        assert result.elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_click_at_invalid_value_fails(self, executor: StepExecutor) -> None:
        step = make_step(ActionType.CLICK_AT, value="invalid")
        result = await executor.execute_step(step)
        assert result.status == StepStatus.FAILED


# ─── Synonym fallback ────────────────────────────────────────


class TestSynonymMapping:
    def test_email_has_korean_synonyms(self) -> None:
        syns = _SYNONYMS.get("email", [])
        assert "이메일" in syns

    def test_password_has_korean_synonyms(self) -> None:
        syns = _SYNONYMS.get("password", [])
        assert "비밀번호" in syns

    def test_korean_maps_back_to_english(self) -> None:
        assert "email" in _SYNONYMS.get("이메일", [])
        assert "password" in _SYNONYMS.get("비밀번호", [])

    def test_login_synonyms(self) -> None:
        syns = _SYNONYMS.get("login", [])
        assert "로그인" in syns
        assert "sign in" in syns


class TestSynonymFallback:
    @pytest.mark.asyncio
    async def test_synonym_fallback_finds_korean_text(
        self,
        mock_matcher: MagicMock,
        mock_humanizer: MagicMock,
        mock_waiter: MagicMock,
        mock_comparator: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When 'Email' is not found, synonym '이메일' should be tried."""
        engine = MagicMock()
        # First call (original "Email") returns None, second call ("이메일") returns coords
        engine.find_text_position = AsyncMock(side_effect=[None, (150, 250)])
        engine.click = AsyncMock()
        engine.type_text = AsyncMock()
        engine.screenshot = AsyncMock(side_effect=_screen_that_reacts())
        engine.save_screenshot = AsyncMock()
        del engine.find_on_screen
        del engine.find_text_box  # awaiting an auto-created MagicMock raises

        executor = StepExecutor(
            engine=engine,
            matcher=mock_matcher,
            humanizer=mock_humanizer,
            waiter=mock_waiter,
            comparator=mock_comparator,
            screenshot_dir=tmp_path,
        )

        target = TargetSpec(text="Email")
        step = make_step(ActionType.FIND_AND_TYPE, target=target, value="test@test.com")
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        assert result.match_result is not None
        assert result.match_result.x == 150
        assert result.match_result.y == 250
        # Should have called find_text_position twice (original + synonym)
        assert engine.find_text_position.await_count == 2

    @pytest.mark.asyncio
    async def test_no_synonym_if_original_found(
        self,
        executor: StepExecutor,
        mock_engine: MagicMock,
    ) -> None:
        """When original text is found, no synonym lookup should happen."""
        mock_engine.find_text_position = AsyncMock(return_value=(100, 200))

        target = TargetSpec(text="Email")
        step = make_step(ActionType.FIND_AND_CLICK, target=target)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        # Only called once — no synonym needed
        mock_engine.find_text_position.assert_awaited_once_with("Email")


# ─── Scroll-to-top + force click fallback ────────────────────


class TestScrollToTopFallback:
    @pytest.mark.asyncio
    async def test_scroll_to_top_retry_succeeds(
        self,
        mock_matcher: MagicMock,
        mock_humanizer: MagicMock,
        mock_waiter: MagicMock,
        mock_comparator: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When text not found, scroll to top + retry should succeed."""
        engine = MagicMock()
        # "login" has 3 synonyms: 로그인, sign in, log in
        # First 4 calls (original + 3 synonyms) all return None → scroll_to_top,
        # then 5th call (after scroll, original text) returns coords
        engine.find_text_position = AsyncMock(side_effect=[None, None, None, None, (200, 300)])
        engine.scroll_to_top = AsyncMock()
        engine.click = AsyncMock()
        engine.screenshot = AsyncMock(side_effect=_screen_that_reacts())
        engine.save_screenshot = AsyncMock()
        del engine.find_on_screen
        del engine.find_text_box  # awaiting an auto-created MagicMock raises
        del engine.force_click_by_text

        executor = StepExecutor(
            engine=engine,
            matcher=mock_matcher,
            humanizer=mock_humanizer,
            waiter=mock_waiter,
            comparator=mock_comparator,
            screenshot_dir=tmp_path,
        )

        target = TargetSpec(text="Login")
        step = make_step(ActionType.FIND_AND_CLICK, target=target)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        engine.scroll_to_top.assert_awaited_once()


class TestForceClickFallback:
    @pytest.mark.asyncio
    async def test_force_click_succeeds_after_all_else_fails(
        self,
        mock_matcher: MagicMock,
        mock_humanizer: MagicMock,
        mock_waiter: MagicMock,
        mock_comparator: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When all find_text_position attempts fail, force_click_by_text is tried."""
        engine = MagicMock()
        # All find_text_position calls return None
        engine.find_text_position = AsyncMock(return_value=None)
        engine.scroll_to_top = AsyncMock()
        engine.force_click_by_text = AsyncMock(return_value=True)
        engine.type_text = AsyncMock()
        engine.screenshot = AsyncMock(side_effect=_screen_that_reacts())
        engine.save_screenshot = AsyncMock()
        del engine.find_on_screen
        del engine.find_text_box  # awaiting an auto-created MagicMock raises

        executor = StepExecutor(
            engine=engine,
            matcher=mock_matcher,
            humanizer=mock_humanizer,
            waiter=mock_waiter,
            comparator=mock_comparator,
            screenshot_dir=tmp_path,
        )

        target = TargetSpec(text="Submit")
        step = make_step(ActionType.FIND_AND_CLICK, target=target)
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        assert result.match_result is not None
        assert result.match_result.confidence == 0.8
        engine.force_click_by_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_force_click_type_action(
        self,
        mock_matcher: MagicMock,
        mock_humanizer: MagicMock,
        mock_waiter: MagicMock,
        mock_comparator: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Force click for find_and_type should click then type."""
        engine = MagicMock()
        engine.find_text_position = AsyncMock(return_value=None)
        engine.scroll_to_top = AsyncMock()
        engine.force_click_by_text = AsyncMock(return_value=True)
        engine.type_text = AsyncMock()
        engine.screenshot = AsyncMock(side_effect=_screen_that_reacts())
        engine.save_screenshot = AsyncMock()
        del engine.find_on_screen
        del engine.find_text_box  # awaiting an auto-created MagicMock raises

        executor = StepExecutor(
            engine=engine,
            matcher=mock_matcher,
            humanizer=mock_humanizer,
            waiter=mock_waiter,
            comparator=mock_comparator,
            screenshot_dir=tmp_path,
        )

        target = TargetSpec(text="Password")
        step = make_step(ActionType.FIND_AND_TYPE, target=target, value="secret123")
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        engine.force_click_by_text.assert_awaited()
        engine.type_text.assert_awaited_once_with("secret123")


# ─── wait_for load state ──────────────────────────────────────


class TestWaitForLoadState:
    """Test wait_for field: explicit Playwright load state wait after action."""

    @pytest.mark.asyncio
    async def test_wait_for_networkidle_called(
        self,
        mock_matcher: MagicMock,
        mock_humanizer: MagicMock,
        mock_waiter: MagicMock,
        mock_comparator: MagicMock,
        tmp_path: Path,
    ) -> None:
        """wait_for='networkidle' calls page.wait_for_load_state('networkidle')."""
        page = MagicMock()
        page.url = "https://example.com"
        page.wait_for_load_state = AsyncMock()

        engine = MagicMock()
        engine.navigate = AsyncMock()
        engine.screenshot = AsyncMock(side_effect=_screen_that_reacts())
        engine.save_screenshot = AsyncMock()
        engine.page = page

        executor = StepExecutor(
            engine=engine,
            matcher=mock_matcher,
            humanizer=mock_humanizer,
            waiter=mock_waiter,
            comparator=mock_comparator,
            screenshot_dir=tmp_path,
        )

        step = StepConfig(
            step=1,
            action=ActionType.NAVIGATE,
            value="https://example.com",
            description="Navigate",
            wait_for="networkidle",
        )
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        page.wait_for_load_state.assert_awaited_once_with("networkidle", timeout=30000)

    @pytest.mark.asyncio
    async def test_wait_for_domcontentloaded(
        self,
        mock_matcher: MagicMock,
        mock_humanizer: MagicMock,
        mock_waiter: MagicMock,
        mock_comparator: MagicMock,
        tmp_path: Path,
    ) -> None:
        """wait_for='domcontentloaded' uses 10s timeout."""
        page = MagicMock()
        page.url = "https://example.com"
        page.wait_for_load_state = AsyncMock()

        engine = MagicMock()
        engine.navigate = AsyncMock()
        engine.screenshot = AsyncMock(side_effect=_screen_that_reacts())
        engine.save_screenshot = AsyncMock()
        engine.page = page

        executor = StepExecutor(
            engine=engine,
            matcher=mock_matcher,
            humanizer=mock_humanizer,
            waiter=mock_waiter,
            comparator=mock_comparator,
            screenshot_dir=tmp_path,
        )

        step = StepConfig(
            step=1,
            action=ActionType.NAVIGATE,
            value="https://example.com",
            description="Navigate",
            wait_for="domcontentloaded",
        )
        await executor.execute_step(step)
        page.wait_for_load_state.assert_awaited_once_with("domcontentloaded", timeout=10000)

    @pytest.mark.asyncio
    async def test_wait_for_none_skips(
        self,
        mock_matcher: MagicMock,
        mock_humanizer: MagicMock,
        mock_waiter: MagicMock,
        mock_comparator: MagicMock,
        tmp_path: Path,
    ) -> None:
        """wait_for=None (default) does NOT call wait_for_load_state."""
        page = MagicMock()
        page.url = "https://example.com"
        page.wait_for_load_state = AsyncMock()

        engine = MagicMock()
        engine.navigate = AsyncMock()
        engine.screenshot = AsyncMock(side_effect=_screen_that_reacts())
        engine.save_screenshot = AsyncMock()
        engine.page = page

        executor = StepExecutor(
            engine=engine,
            matcher=mock_matcher,
            humanizer=mock_humanizer,
            waiter=mock_waiter,
            comparator=mock_comparator,
            screenshot_dir=tmp_path,
        )

        step = StepConfig(
            step=1,
            action=ActionType.NAVIGATE,
            value="https://example.com",
            description="Navigate",
        )
        await executor.execute_step(step)
        page.wait_for_load_state.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wait_for_invalid_state_skips(
        self,
        mock_matcher: MagicMock,
        mock_humanizer: MagicMock,
        mock_waiter: MagicMock,
        mock_comparator: MagicMock,
        tmp_path: Path,
    ) -> None:
        """wait_for with unknown state logs warning and does not raise."""
        page = MagicMock()
        page.url = "https://example.com"
        page.wait_for_load_state = AsyncMock()

        engine = MagicMock()
        engine.navigate = AsyncMock()
        engine.screenshot = AsyncMock(side_effect=_screen_that_reacts())
        engine.save_screenshot = AsyncMock()
        engine.page = page

        executor = StepExecutor(
            engine=engine,
            matcher=mock_matcher,
            humanizer=mock_humanizer,
            waiter=mock_waiter,
            comparator=mock_comparator,
            screenshot_dir=tmp_path,
        )

        step = StepConfig(
            step=1,
            action=ActionType.NAVIGATE,
            value="https://example.com",
            description="Navigate",
            wait_for="invalid_state",
        )
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        page.wait_for_load_state.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wait_for_timeout_does_not_fail_step(
        self,
        mock_matcher: MagicMock,
        mock_humanizer: MagicMock,
        mock_waiter: MagicMock,
        mock_comparator: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Timeout in wait_for_load_state does not cause step failure."""
        from playwright.async_api import TimeoutError as PlaywrightTimeout

        page = MagicMock()
        page.url = "https://example.com"
        page.wait_for_load_state = AsyncMock(side_effect=PlaywrightTimeout("timeout"))

        engine = MagicMock()
        engine.navigate = AsyncMock()
        engine.screenshot = AsyncMock(side_effect=_screen_that_reacts())
        engine.save_screenshot = AsyncMock()
        engine.page = page

        executor = StepExecutor(
            engine=engine,
            matcher=mock_matcher,
            humanizer=mock_humanizer,
            waiter=mock_waiter,
            comparator=mock_comparator,
            screenshot_dir=tmp_path,
        )

        step = StepConfig(
            step=1,
            action=ActionType.NAVIGATE,
            value="https://example.com",
            description="Navigate",
            wait_for="networkidle",
        )
        result = await executor.execute_step(step)
        # Timeout is swallowed — step still passes
        assert result.status == StepStatus.PASSED


# ─── Login redirect detection ────────────────────────────────


class TestIsLoginUrl:
    """One pattern list behind every hard stop — see _is_login_url."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://app.test/login",
            "https://app.test/login?next=%2Fexam",
            "https://app.test/signin",
            "https://nid.naver.com/nidlogin.login",
            "https://app.test/account/login",
            "https://app.test/accounts/login",
            "https://APP.TEST/LOGIN",
        ],
    )
    def test_login_urls(self, executor: StepExecutor, url: str) -> None:
        assert executor._is_login_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://app.test/",
            "https://app.test/exam",
            "https://app.test/api/auth/logout",  # the opposite of a login redirect
            "https://app.test/authors/42",
            "https://app.test/oauth/authorize",
            "",
        ],
    )
    def test_non_login_urls(self, executor: StepExecutor, url: str) -> None:
        assert executor._is_login_url(url) is False


class TestLoginRedirectExpected:
    """The only way past a login-redirect hard stop."""

    def test_closed_by_default(self, executor: StepExecutor) -> None:
        step = make_step(ActionType.NAVIGATE, value="https://app.test/")
        assert step.expect_login_redirect is None
        assert executor._login_redirect_expected(step) is False

    def test_open_for_marked_step(self, executor: StepExecutor) -> None:
        step = make_step(ActionType.NAVIGATE, value="https://app.test/")
        step.expect_login_redirect = True
        assert executor._login_redirect_expected(step) is True

    def test_explicit_false_does_not_open_it(self, executor: StepExecutor) -> None:
        step = make_step(ActionType.NAVIGATE, value="https://app.test/")
        step.expect_login_redirect = False
        assert executor._login_redirect_expected(step) is False

    def test_open_after_deliberate_navigation_to_login(self, executor: StepExecutor) -> None:
        executor._intentional_login_page = True
        step = make_step(ActionType.ASSERT_URL, value="/login")
        assert executor._login_redirect_expected(step) is True


class TestPostNavigateRedirect:
    """navigate hard stop (site 1 of 3)."""

    @staticmethod
    def _engine_on(url: str) -> MagicMock:
        engine = MagicMock()
        engine.navigate = AsyncMock()
        engine.screenshot = AsyncMock(side_effect=_screen_that_reacts())
        engine.save_screenshot = AsyncMock()
        page = MagicMock()
        page.url = url
        page.title = AsyncMock(return_value="Sign in")
        engine.page = page
        engine._config = MagicMock(fast_mode=False, speed="fast")
        return engine

    def _executor(self, engine: MagicMock, tmp_path: Path) -> StepExecutor:
        return StepExecutor(
            engine=engine,
            matcher=MagicMock(find=AsyncMock(return_value=MatchResult(found=True, x=1, y=1))),
            humanizer=MagicMock(move_to=AsyncMock(), type_text=AsyncMock()),
            waiter=MagicMock(wait_until_stable=AsyncMock(return_value=True)),
            comparator=MagicMock(check=AsyncMock(), check_assert=AsyncMock()),
            screenshot_dir=tmp_path,
        )

    async def test_unexpected_redirect_raises(self, tmp_path: Path) -> None:
        ex = self._executor(self._engine_on("https://app.test/login?next=%2F"), tmp_path)
        step = make_step(ActionType.NAVIGATE, value="https://app.test/")

        with pytest.raises(StepExecutionError, match="Unexpected redirect to login page"):
            await ex._check_post_navigate_redirect(step)

    async def test_expected_redirect_passes(self, tmp_path: Path) -> None:
        ex = self._executor(self._engine_on("https://app.test/login?next=%2F"), tmp_path)
        step = make_step(ActionType.NAVIGATE, value="https://app.test/")
        step.expect_login_redirect = True

        await ex._check_post_navigate_redirect(step)  # must not raise

    async def test_logout_url_is_not_a_login_redirect(self, tmp_path: Path) -> None:
        """Bare '/auth' used to make /api/auth/logout look like a session expiry."""
        ex = self._executor(self._engine_on("https://app.test/api/auth/logout"), tmp_path)
        step = make_step(ActionType.NAVIGATE, value="https://app.test/")

        await ex._check_post_navigate_redirect(step)  # must not raise


class TestLoadSessionAge:
    """load_session: how old the reused session is, and when that is too old.

    A saved session that the server has already ended looks exactly like a
    wrong password from the outside, which is why the age has to be said out
    loud and why a step can put a ceiling on it.
    """

    def _executor(self, engine: MagicMock, tmp_path: Path) -> StepExecutor:
        return StepExecutor(
            engine=engine,
            matcher=MagicMock(find=AsyncMock(return_value=MatchResult(found=True, x=1, y=1))),
            humanizer=MagicMock(move_to=AsyncMock(), type_text=AsyncMock()),
            waiter=MagicMock(wait_until_stable=AsyncMock(return_value=True)),
            comparator=MagicMock(check=AsyncMock(), check_assert=AsyncMock()),
            screenshot_dir=tmp_path / "screenshots",
        )

    def _session_file(self, tmp_path: Path, *, age_min: float) -> Path:
        path = tmp_path / "sessions" / "haneul.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"cookies": []}')
        stamp = time.time() - age_min * 60
        os.utime(path, (stamp, stamp))
        return path

    def _step(self, max_age_min: int | None = None) -> StepConfig:
        return StepConfig(
            step=1,
            action=ActionType.LOAD_SESSION,
            name="haneul",
            description="Reuse the signed-in session",
            max_age_min=max_age_min,
        )

    @pytest.mark.asyncio
    async def test_age_is_reported_when_the_session_loads(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._session_file(tmp_path, age_min=21)
        engine = MagicMock(load_session=AsyncMock())
        executor = self._executor(engine, tmp_path)

        with caplog.at_level(logging.INFO, logger="aat.engine.executor"):
            await executor._handle_load_session(self._step())

        engine.load_session.assert_awaited_once()
        assert "21 minutes ago" in caplog.text

    @pytest.mark.asyncio
    async def test_session_past_the_cap_fails_at_that_step(self, tmp_path: Path) -> None:
        session = self._session_file(tmp_path, age_min=40)
        engine = MagicMock(load_session=AsyncMock())
        executor = self._executor(engine, tmp_path)

        with pytest.raises(StepExecutionError) as exc:
            await executor._handle_load_session(self._step(max_age_min=15))

        message = str(exc.value)
        assert "too old" in message
        assert "40 minutes ago" in message
        assert str(session) in message  # says which file to stop reusing
        engine.load_session.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_session_within_the_cap_still_loads(self, tmp_path: Path) -> None:
        self._session_file(tmp_path, age_min=5)
        engine = MagicMock(load_session=AsyncMock())
        executor = self._executor(engine, tmp_path)

        await executor._handle_load_session(self._step(max_age_min=15))

        engine.load_session.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_cap_leaves_an_old_session_alone(self, tmp_path: Path) -> None:
        """Without max_age_min the old 24h rule is all that applies."""
        self._session_file(tmp_path, age_min=200)
        engine = MagicMock(load_session=AsyncMock())
        executor = self._executor(engine, tmp_path)

        await executor._handle_load_session(self._step())

        engine.load_session.assert_awaited_once()

    def test_the_failure_does_not_point_at_the_credentials(self, tmp_path: Path) -> None:
        """The message has to route to the session, not to the password."""
        from aat.core.diagnosis import classify_failure

        session = self._session_file(tmp_path, age_min=40)
        message = (
            f"saved session 'haneul' is too old: saved 40 minutes ago, max_age_min=15. "
            f"The service has probably ended it — log in again instead of reusing {session}."
        )

        assert classify_failure(message) == "session_expired"


# ─── Navigation is judged by the URL, not by pixels ──────────


class TestNavigationEffect:
    """`critical: true` on a navigate step used to fail every time.

    NAVIGATE sat in `_CRITICAL_CHANGE_ACTIONS` with a 50% pixel threshold, so
    the simplest scenario a new user can write died on step 1 against a plain
    page — example.com repaints 9.1% — while the URL and title printed on the
    next log lines proved the navigation had worked. The diagnosis then aimed
    FIX_TARGET at the healthy scenario.
    """

    @staticmethod
    def _frozen_screen() -> bytes:
        """One image, returned every time: zero measured pixel change.

        This is the sparse page that broke the old threshold.
        """
        return _png(200)

    @staticmethod
    def _executor(engine: MagicMock, tmp_path: Path) -> StepExecutor:
        return StepExecutor(
            engine=engine,
            matcher=MagicMock(find=AsyncMock(return_value=MatchResult(found=True, x=1, y=1))),
            humanizer=MagicMock(move_to=AsyncMock(), type_text=AsyncMock()),
            waiter=MagicMock(wait_until_stable=AsyncMock(return_value=True)),
            comparator=MagicMock(check=AsyncMock(), check_assert=AsyncMock()),
            screenshot_dir=tmp_path,
        )

    @classmethod
    def _engine(cls, urls: list[str]) -> MagicMock:
        """An engine whose screen never moves and whose URL follows `urls`."""
        engine = MagicMock()
        engine.navigate = AsyncMock()
        engine.screenshot = AsyncMock(return_value=cls._frozen_screen())
        engine.save_screenshot = AsyncMock()
        engine.get_page_text = AsyncMock(return_value="Example Domain")
        engine.get_url = AsyncMock(side_effect=itertools.cycle(urls))
        engine.find_text_position = AsyncMock(return_value=None)
        del engine.find_on_screen
        del engine.find_text_box  # awaiting an auto-created MagicMock raises
        del engine.scroll_to_top
        del engine.force_click_by_text
        del engine.page  # skip the URL/title blocker probe
        engine._config = MagicMock(fast_mode=False)
        return engine

    @pytest.mark.asyncio
    async def test_critical_navigate_passes_on_a_page_that_barely_repaints(
        self, tmp_path: Path
    ) -> None:
        """The regression. A frozen screen must not fail a navigate that worked.

        Mutation check: putting NAVIGATE back in `_CRITICAL_THRESHOLDS` and
        routing it to `_verify_click_effect` makes this raise CriticalStepError.
        """
        engine = self._engine(["about:blank", "https://example.com/"])
        executor = self._executor(engine, tmp_path)
        step = StepConfig(
            step=1,
            action=ActionType.NAVIGATE,
            description="Open the target site",
            value="https://example.com",
            critical=True,
        )

        result = await executor.execute_step(step)

        assert result.status == StepStatus.PASSED

    @pytest.mark.asyncio
    async def test_critical_navigate_fails_when_the_browser_never_left(
        self, tmp_path: Path
    ) -> None:
        """Dropping the pixel check must not drop the check altogether."""
        engine = self._engine(["https://old.example/stuck"])
        executor = self._executor(engine, tmp_path)
        step = StepConfig(
            step=1,
            action=ActionType.NAVIGATE,
            description="Open the target site",
            value="https://example.com/target",
            critical=True,
        )

        with pytest.raises(CriticalStepError) as exc:
            await executor.execute_step(step)

        assert "old.example/stuck" in str(exc.value)

    @pytest.mark.asyncio
    async def test_a_navigate_that_never_left_is_a_warning_not_a_pass(
        self, tmp_path: Path
    ) -> None:
        """Non-critical, but still not PASSED — AAT-109's rule, one step up."""
        engine = self._engine(["https://old.example/stuck"])
        executor = self._executor(engine, tmp_path)
        step = StepConfig(
            step=1,
            action=ActionType.NAVIGATE,
            description="Open the target site",
            value="https://example.com/target",
        )

        result = await executor.execute_step(step)

        assert result.status == StepStatus.WARNING

    @pytest.mark.asyncio
    async def test_a_redirect_passes_and_the_destination_is_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Following a redirect is the server's decision, not a test failure.

        It still has to show up in the log: the scenario asked for one place
        and ended up in another, and the reader needs to see which.
        """
        engine = self._engine(["https://example.com/old", "https://example.com/new-home"])
        executor = self._executor(engine, tmp_path)
        step = StepConfig(
            step=1,
            action=ActionType.NAVIGATE,
            description="Open the target site",
            value="https://example.com/old-home",
            critical=True,
        )

        with caplog.at_level(logging.INFO):
            result = await executor.execute_step(step)

        assert result.status == StepStatus.PASSED
        assert "new-home" in caplog.text

    @pytest.mark.asyncio
    async def test_an_unreadable_url_is_not_counted_as_a_failure(self, tmp_path: Path) -> None:
        """No URL means no verdict. Guessing either way would be worse."""
        engine = self._engine(["about:blank"])
        engine.get_url = AsyncMock(side_effect=RuntimeError("engine detached"))
        executor = self._executor(engine, tmp_path)
        step = StepConfig(
            step=1,
            action=ActionType.NAVIGATE,
            description="Open the target site",
            value="https://example.com",
            critical=True,
        )

        result = await executor.execute_step(step)

        assert result.status == StepStatus.PASSED

    def test_navigate_is_no_longer_scored_in_pixels(self) -> None:
        """Guards the fix itself, so a future edit cannot quietly undo it."""
        assert ActionType.NAVIGATE not in StepExecutor._CRITICAL_CHANGE_ACTIONS
        assert ActionType.NAVIGATE not in StepExecutor._CRITICAL_THRESHOLDS

    @pytest.mark.parametrize(
        ("requested", "landed"),
        [
            ("https://example.com", "https://example.com/"),
            ("https://example.com", "http://www.example.com"),
            ("https://example.com/app", "https://example.com/app?ref=1"),
            ("https://example.com/app", "https://example.com/app#top"),
            ("example.com/app", "https://EXAMPLE.com/app/"),
        ],
    )
    def test_url_key_reads_these_as_the_same_destination(
        self, requested: str, landed: str
    ) -> None:
        assert StepExecutor._url_key(requested) in StepExecutor._url_key(landed)

    @pytest.mark.parametrize(
        ("requested", "landed"),
        [
            ("https://example.com/dashboard", "https://example.com/login"),
            ("https://example.com", "https://example.org"),
        ],
    )
    def test_url_key_keeps_different_destinations_apart(self, requested: str, landed: str) -> None:
        assert StepExecutor._url_key(requested) not in StepExecutor._url_key(landed)


# ─── Match provenance labels ─────────────────────────────────


def _page_with_one_element(
    box: dict[str, float] | None = None,
) -> MagicMock:
    """A page whose locator resolves to exactly one element with a box."""
    loc = MagicMock()
    loc.count = AsyncMock(return_value=1)
    loc.scroll_into_view_if_needed = AsyncMock()
    loc.bounding_box = AsyncMock(
        return_value=box or {"x": 100.0, "y": 200.0, "width": 80.0, "height": 40.0}
    )
    loc.click = AsyncMock()
    base = MagicMock(first=loc)
    base.filter = MagicMock(return_value=MagicMock(first=loc))
    page = MagicMock()
    page.locator = MagicMock(return_value=base)
    return page


class TestMatchProvenanceLabel:
    """Every way of finding a target must report *which* way it was.

    ``_act_at_pos`` used to stamp ``MatchMethod.OCR`` on its result no matter
    who called it. A CSS selector hit, a learned coordinate and the matcher
    chain's own verdict were all recorded as ``ocr`` in ``match_history`` —
    which is how 237 rows came to name a matcher that never ran, and why
    "visual matching saved this run" was not a measurable claim. These tests
    pin each caller to its own label, because a number nobody can trust is
    worse than no number.
    """

    @pytest.mark.asyncio
    async def test_css_selector_hit_is_labelled_playwright(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        mock_engine.page = _page_with_one_element()
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(selector="#submit"))

        result = await executor.execute_step(step)

        assert result.status == StepStatus.PASSED
        assert result.match_result is not None
        assert result.match_result.method == MatchMethod.PLAYWRIGHT

    @pytest.mark.asyncio
    async def test_text_search_hit_is_labelled_playwright(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        del mock_engine.page  # skip the selector and semantics paths
        mock_engine.find_text_position = AsyncMock(return_value=(150, 250))
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(text="Submit"))

        result = await executor.execute_step(step)

        assert result.match_result is not None
        assert result.match_result.method == MatchMethod.PLAYWRIGHT

    @pytest.mark.asyncio
    async def test_force_click_fallback_is_labelled_playwright(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        """A JS click through a locator is still DOM work, not OCR."""
        del mock_engine.page
        mock_engine.find_text_position = AsyncMock(return_value=None)
        mock_engine.force_click_by_text = AsyncMock(return_value=True)
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(text="Submit"))

        result = await executor.execute_step(step)

        assert result.match_result is not None
        assert result.match_result.method == MatchMethod.PLAYWRIGHT

    @pytest.mark.asyncio
    async def test_flutter_semantics_hit_is_labelled_semantics(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        """SEMANTICS names no matcher, but it names a real strategy.

        Labelling it ``ocr`` hid the one lookup that makes CanvasKit apps
        testable at all.
        """
        mock_engine.page = MagicMock()
        executor._find_by_flutter_semantics = AsyncMock(return_value=(10, 20))  # type: ignore[method-assign]
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(text="Submit"))

        result = await executor.execute_step(step)

        assert result.match_result is not None
        assert result.match_result.method == MatchMethod.SEMANTICS

    @pytest.mark.asyncio
    async def test_learned_coordinates_are_labelled_learned(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        """Learned coordinates are a guess from an earlier run, not a match.

        Reading them as ``ocr`` made AAT-109's whole failure mode — a stale
        coordinate clicking nothing — invisible in the history.
        """
        del mock_engine.page
        store = MagicMock()
        store.find_state_coords = MagicMock(return_value=(300, 400, 0.9))
        store.get_strategies = MagicMock(return_value=[])
        store.get_target_failure_count = MagicMock(return_value=0)
        executor._learned_store = store

        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(text="Submit"))
        result = await executor.execute_step(step)

        assert result.match_result is not None
        assert result.match_result.method == MatchMethod.LEARNED

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method",
        [
            MatchMethod.TEMPLATE,
            MatchMethod.OCR,
            MatchMethod.FEATURE,
            MatchMethod.VISION_AI,
        ],
    )
    async def test_the_chain_verdict_survives_the_action(
        self,
        executor: StepExecutor,
        mock_engine: MagicMock,
        mock_matcher: MagicMock,
        method: MatchMethod,
    ) -> None:
        """The defect that made the visual stack unmeasurable.

        ``_act_at_pos`` overwrote the chain's verdict, so a template or vision
        hit was indistinguishable from a selector hit. Parametrised over every
        chain method because the bug was in the handoff, not in any one matcher.
        """
        del mock_engine.page
        mock_matcher.find = AsyncMock(
            return_value=MatchResult(found=True, x=50, y=60, confidence=0.9, method=method)
        )
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(image="button.png"))

        result = await executor.execute_step(step)

        assert result.status == StepStatus.PASSED
        assert result.match_result is not None
        assert result.match_result.method == method

    @pytest.mark.asyncio
    async def test_the_label_reaches_match_history(
        self, executor: StepExecutor, mock_engine: MagicMock, mock_matcher: MagicMock
    ) -> None:
        """The label is only worth fixing if it lands in the store.

        ``match_history`` is the only evidence of which strategy carries the
        suite, so this asserts the end of the wire, not the middle.
        """
        del mock_engine.page
        store = MagicMock()
        store.find_state_coords = MagicMock(return_value=None)
        store.find_by_name = MagicMock(return_value=None)
        store.get_strategies = MagicMock(return_value=[])
        store.get_target_failure_count = MagicMock(return_value=0)
        executor._learned_store = store
        mock_matcher.find = AsyncMock(
            return_value=MatchResult(
                found=True, x=50, y=60, confidence=0.9, method=MatchMethod.VISION_AI
            )
        )
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(image="button.png"))

        await executor.execute_step(step)

        assert store.record_match.call_args.kwargs["method"] == "vision_ai"

    @pytest.mark.asyncio
    async def test_targetless_step_records_playwright(
        self, executor: StepExecutor, mock_engine: MagicMock
    ) -> None:
        """navigate/wait/assert carry no match result; the engine acted.

        Taken from the enum rather than a bare literal so this default and
        ``MatchMethod`` cannot drift apart — ``_classify_strategy`` reads the
        same string to decide what advice to give.
        """
        store = MagicMock()
        executor._learned_store = store
        step = make_step(ActionType.NAVIGATE, value="https://example.com/next")

        await executor.execute_step(step)

        assert store.record_match.call_args.kwargs["method"] == MatchMethod.PLAYWRIGHT.value


# ─── Visual baseline banking ─────────────────────────────────


def _png_sized(width: int, height: int, shade: int) -> bytes:
    """A PNG of a given size, so a 320x240 element box lands inside it."""
    return bytes(cv2.imencode(".png", np.full((height, width), shade, dtype=np.uint8))[1])


def _screen_that_reacts_sized(width: int, height: int) -> Callable[[], bytes]:
    shades = itertools.cycle((0, 255))
    return lambda: _png_sized(width, height, next(shades))


def _png_with_patch(width: int, height: int, box: dict[str, float]) -> bytes:
    """A dark frame with a red rectangle where the element is."""
    img = np.full((height, width, 3), 30, dtype=np.uint8)
    x, y = int(box["x"]), int(box["y"])
    img[y : y + int(box["height"]), x : x + int(box["width"])] = (0, 0, 255)
    return bytes(cv2.imencode(".png", img)[1])


class TestVisualBaselineBanking:
    """A DOM hit has to leave behind a picture, or self-healing has nothing to heal from.

    The feature was advertised and shipped, and it fired zero times in real
    use. One reason was that the only code that ever banked a template lived
    inside ``HybridMatcher`` — which the executor reaches *only after* a DOM
    lookup has already failed. So every element AWT successfully found was
    never photographed, and when the selector later broke there was nothing on
    disk to fall back to.

    Banking costs no extra screenshot: the frame captured for
    ``assert_screen_changed`` is the one cropped. And it is provisional, for
    the AAT-109 reason — a selector can resolve to the wrong element, and a
    picture of the wrong element is worse than none, because healing from it
    reproduces the wrong click and reports a pass.
    """

    BOX = {"x": 40.0, "y": 50.0, "width": 80.0, "height": 30.0}

    @staticmethod
    def _executor(engine: MagicMock, tmp_path: Path, *, learn: bool = True) -> StepExecutor:
        return StepExecutor(
            engine=engine,
            matcher=MagicMock(find=AsyncMock(return_value=MatchResult(found=False, x=0, y=0))),
            humanizer=MagicMock(move_to=AsyncMock(), type_text=AsyncMock()),
            waiter=MagicMock(wait_until_stable=AsyncMock(return_value=True)),
            comparator=MagicMock(check=AsyncMock(), check_assert=AsyncMock()),
            screenshot_dir=tmp_path,
            learn_coords=learn,
        )

    @pytest.fixture
    def engine(self, mock_engine: MagicMock) -> MagicMock:
        """A page with one findable element, screenshotted at viewport size."""
        mock_engine.screenshot = AsyncMock(side_effect=_screen_that_reacts_sized(320, 240))
        mock_engine._config = MagicMock(fast_mode=False, viewport_width=320, viewport_height=240)
        mock_engine.page = _page_with_one_element(dict(self.BOX))
        return mock_engine

    @pytest.mark.asyncio
    async def test_a_selector_hit_banks_a_picture_of_the_element(
        self, engine: MagicMock, tmp_path: Path
    ) -> None:
        """The regression: a DOM hit used to leave the store empty."""
        executor = self._executor(engine, tmp_path)
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(selector="#submit"))

        result = await executor.execute_step(step)

        assert result.status == StepStatus.PASSED
        (entry,) = template_store.inventory()
        assert entry.target == "#submit"
        assert entry.width == 80 + 2 * template_store.PAD
        assert entry.height == 30 + 2 * template_store.PAD
        assert entry.method == MatchMethod.PLAYWRIGHT.value

    @pytest.mark.asyncio
    async def test_the_scope_follows_the_page_the_step_ran_against(
        self, engine: MagicMock, tmp_path: Path
    ) -> None:
        """Pictures belong to a host, so one app's "확인" cannot answer another's."""
        engine.get_url = AsyncMock(return_value="https://shop.example.net/cart")
        executor = self._executor(engine, tmp_path)
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(selector="#buy"))

        await executor.execute_step(step)

        (entry,) = template_store.inventory()
        assert entry.scope == "shop.example.net"
        assert template_store.lookup("shop.example.net", "#buy") is not None

    @pytest.mark.asyncio
    async def test_the_picture_comes_from_before_the_action(
        self, engine: MagicMock, tmp_path: Path
    ) -> None:
        """After a click the element may be gone; the crop must predate it.

        The first frame has a red rectangle where the element is and every
        later frame does not, so a red crop proves the banked picture came
        from the frame taken before the action — not from the post-step frame,
        which is the one most of the verification code works with.
        """
        engine.screenshot = AsyncMock(
            side_effect=itertools.chain(
                [_png_with_patch(320, 240, self.BOX)],
                (_png_sized(320, 240, s) for s in itertools.cycle((0, 200))),
            )
        )
        executor = self._executor(engine, tmp_path)
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(selector="#submit"))

        await executor.execute_step(step)

        (entry,) = template_store.inventory()
        img = cv2.imread(str(entry.path))
        centre = img[img.shape[0] // 2, img.shape[1] // 2]
        assert tuple(int(c) for c in centre) == (0, 0, 255)

    @pytest.mark.asyncio
    async def test_a_click_that_moved_nothing_banks_nothing(
        self, engine: MagicMock, tmp_path: Path
    ) -> None:
        """AAT-109's rule, applied to pictures as well as coordinates.

        A selector that resolves to the wrong element still "succeeds". The
        only evidence that it found the right one is that clicking it did
        something, so banking waits for that evidence.
        """
        engine.screenshot = AsyncMock(return_value=_png_sized(320, 240, 128))
        executor = self._executor(engine, tmp_path)
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(selector="#submit"))

        result = await executor.execute_step(step)

        assert result.status == StepStatus.WARNING
        assert template_store.inventory() == []

    @pytest.mark.asyncio
    async def test_no_learn_turns_banking_off(self, engine: MagicMock, tmp_path: Path) -> None:
        """`aat run --no-learn` means remember nothing, pictures included."""
        executor = self._executor(engine, tmp_path, learn=False)
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(selector="#submit"))

        result = await executor.execute_step(step)

        assert result.status == StepStatus.PASSED
        assert template_store.inventory() == []

    @pytest.mark.asyncio
    async def test_a_step_marked_learn_false_banks_nothing(
        self, engine: MagicMock, tmp_path: Path
    ) -> None:
        """`learn: false` marks targets whose position follows the content."""
        executor = self._executor(engine, tmp_path)
        step = make_step(
            ActionType.FIND_AND_CLICK, target=TargetSpec(selector="#submit")
        ).model_copy(update={"learn": False})

        await executor.execute_step(step)

        assert template_store.inventory() == []

    @pytest.mark.asyncio
    async def test_a_text_search_hit_banks_the_box_the_engine_reported(
        self, mock_engine: MagicMock, tmp_path: Path
    ) -> None:
        """Most scenarios name a button by its label, not by a selector."""
        del mock_engine.page  # skip the selector and semantics paths
        mock_engine.screenshot = AsyncMock(side_effect=_screen_that_reacts_sized(320, 240))
        mock_engine._config = MagicMock(fast_mode=False, viewport_width=320, viewport_height=240)
        mock_engine.find_text_box = AsyncMock(return_value=dict(self.BOX))
        executor = self._executor(mock_engine, tmp_path)
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(text="Submit"))

        result = await executor.execute_step(step)

        assert result.status == StepStatus.PASSED
        (entry,) = template_store.inventory()
        assert entry.target == "Submit"

    @pytest.mark.asyncio
    async def test_an_engine_without_boxes_still_passes(
        self, mock_engine: MagicMock, tmp_path: Path
    ) -> None:
        """DesktopEngine reports a centre point and no rectangle.

        Nothing to photograph is not an error — the step must still run.
        """
        del mock_engine.page
        mock_engine.screenshot = AsyncMock(side_effect=_screen_that_reacts_sized(320, 240))
        mock_engine._config = MagicMock(fast_mode=False, viewport_width=320, viewport_height=240)
        mock_engine.find_text_position = AsyncMock(return_value=(80, 65))
        executor = self._executor(mock_engine, tmp_path)
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(text="Submit"))

        result = await executor.execute_step(step)

        assert result.status == StepStatus.PASSED
        assert template_store.inventory() == []

    @pytest.mark.asyncio
    async def test_coordinate_clicks_bank_nothing(self, engine: MagicMock, tmp_path: Path) -> None:
        """`click_at: "100,50"` names no element, so there is nothing to recognise."""
        executor = self._executor(engine, tmp_path)
        step = make_step(ActionType.CLICK_AT, value="100,50")

        await executor.execute_step(step)

        assert template_store.inventory() == []

    @pytest.mark.asyncio
    async def test_a_store_failure_does_not_fail_the_step(
        self, engine: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A step that found its element must not fail on the bookkeeping after."""

        def _explode(*_args: object, **_kwargs: object) -> None:
            msg = "disk full"
            raise OSError(msg)

        monkeypatch.setattr(template_store, "save", _explode)
        executor = self._executor(engine, tmp_path)
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(selector="#submit"))

        result = await executor.execute_step(step)

        assert result.status == StepStatus.PASSED


# ─── Self-healing from a banked picture ──────────────────────


def _page_with_no_element() -> MagicMock:
    """A page whose locators resolve to nothing — the selector has gone stale."""
    loc = MagicMock()
    loc.count = AsyncMock(return_value=0)
    base = MagicMock(first=loc)
    base.filter = MagicMock(return_value=MagicMock(first=loc))
    page = MagicMock()
    page.locator = MagicMock(return_value=base)
    page.get_by_role = MagicMock(return_value=base)
    page.get_by_text = MagicMock(return_value=base)
    return page


class TestSelfHealingFromBank:
    """When the selector breaks, the banked picture has to actually find the element.

    This is the differentiator, and it was wired shut in two places. The chain
    that knows how to match a banked crop runs only after a DOM lookup fails —
    correct — but ``--fast`` raised ``MatchError`` *before* the chain, and
    ``--fast`` is the mode the docs, the skill and the MCP server all
    recommend. So the one command users were told to run was the one command
    that could never heal.

    The matcher here is real, not a stub: the point of these tests is that a
    crop taken from one screen locates the element on the next one.
    """

    BOX = {"x": 40.0, "y": 50.0, "width": 80.0, "height": 30.0}
    URL = "https://example.com/page"

    @classmethod
    def _screen(cls) -> bytes:
        """The page as it looks while the element is on it."""
        return _png_with_patch(320, 240, cls.BOX)

    @classmethod
    def _screens_that_react(cls, engine: MagicMock) -> None:
        """Show the element until something is clicked, then show a changed page.

        A heal that clicked the right pixels still has to prove it did
        something, or AAT-109 downgrades it to a warning — so the mock has to
        react to the click the way a real page would.
        """
        acted = {"yes": False}

        async def _click(*_args: object, **_kwargs: object) -> None:
            acted["yes"] = True

        async def _screenshot(*_args: object, **_kwargs: object) -> bytes:
            return _png_sized(320, 240, 255) if acted["yes"] else cls._screen()

        engine.click = AsyncMock(side_effect=_click)
        engine.screenshot = AsyncMock(side_effect=_screenshot)

    @classmethod
    def _bank(cls, name: str, *, host: str = "example.com") -> None:
        saved = template_store.save(
            template_store.scope_for_host(host),
            name,
            cls._screen(),
            left=cls.BOX["x"],
            top=cls.BOX["y"],
            width=cls.BOX["width"],
            height=cls.BOX["height"],
            method=MatchMethod.PLAYWRIGHT.value,
            confidence=0.95,
        )
        assert saved is not None, "the fixture itself must bank something"

    @staticmethod
    def _executor(engine: MagicMock, tmp_path: Path) -> StepExecutor:
        from aat.matchers.hybrid import HybridMatcher
        from aat.matchers.template import TemplateMatcher

        return StepExecutor(
            engine=engine,
            matcher=HybridMatcher([TemplateMatcher(MatchingConfig())]),
            humanizer=MagicMock(move_to=AsyncMock(), type_text=AsyncMock()),
            waiter=MagicMock(wait_until_stable=AsyncMock(return_value=True)),
            comparator=MagicMock(check=AsyncMock(), check_assert=AsyncMock()),
            screenshot_dir=tmp_path,
        )

    @pytest.fixture
    def engine(self, mock_engine: MagicMock) -> MagicMock:
        """A page that no longer answers the selector, still showing the element."""
        mock_engine.page = _page_with_no_element()
        self._screens_that_react(mock_engine)
        mock_engine.get_url = AsyncMock(return_value=self.URL)
        mock_engine._config = MagicMock(fast_mode=False, viewport_width=320, viewport_height=240)
        return mock_engine

    @pytest.mark.asyncio
    async def test_a_broken_selector_is_healed_by_the_banked_picture(
        self, engine: MagicMock, tmp_path: Path
    ) -> None:
        self._bank("#submit")
        executor = self._executor(engine, tmp_path)
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(selector="#submit"))

        result = await executor.execute_step(step)

        assert result.status == StepStatus.PASSED
        assert result.match_result is not None
        assert result.match_result.method == MatchMethod.SAVED_TEMPLATE
        clicked_x, clicked_y = engine.click.call_args[0]
        assert abs(clicked_x - 80) <= 2  # 40 + 80/2
        assert abs(clicked_y - 65) <= 2  # 50 + 30/2

    @pytest.mark.asyncio
    async def test_fast_mode_heals_instead_of_giving_up(
        self, engine: MagicMock, tmp_path: Path
    ) -> None:
        """`aat run --skill-mode --fast` is the recommended command. It must heal.

        One deterministic attempt only: a banked crop matched against the
        current screen. No OCR and no paid vision call, so the mode still means
        what it says.
        """
        engine._config = MagicMock(fast_mode=True, viewport_width=320, viewport_height=240)
        self._bank("#submit")
        executor = self._executor(engine, tmp_path)
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(selector="#submit"))

        result = await executor.execute_step(step)

        assert result.status == StepStatus.PASSED
        assert result.match_result is not None
        assert result.match_result.method == MatchMethod.SAVED_TEMPLATE

    @pytest.mark.asyncio
    async def test_fast_mode_with_nothing_banked_still_fails_fast(
        self, engine: MagicMock, tmp_path: Path
    ) -> None:
        """Healing must not become a tax on every failing step.

        The store is checked for a file before any matching work, so a run that
        has banked nothing pays a stat() call and nothing else — which is why
        the matcher must not be reached here at all.
        """
        engine._config = MagicMock(fast_mode=True, viewport_width=320, viewport_height=240)
        executor = self._executor(engine, tmp_path)
        matching = AsyncMock(return_value=None)
        executor._matcher.find_saved_template = matching  # type: ignore[union-attr]
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(selector="#submit"))

        result = await executor.execute_step(step)

        assert result.status == StepStatus.FAILED
        assert "Fast Mode" in (result.error_message or "")
        assert matching.await_count == 0

    @pytest.mark.asyncio
    async def test_a_picture_banked_for_another_host_does_not_heal(
        self, engine: MagicMock, tmp_path: Path
    ) -> None:
        """A false pass is worse than a lost heal, so the host has to match."""
        self._bank("#submit", host="other.example.org")
        executor = self._executor(engine, tmp_path)
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(selector="#submit"))

        result = await executor.execute_step(step)

        assert result.status == StepStatus.FAILED

    @pytest.mark.asyncio
    async def test_a_picture_of_something_else_does_not_heal(
        self, engine: MagicMock, tmp_path: Path
    ) -> None:
        """The crop has to be found on screen; being on disk is not enough."""
        template_store.save(
            template_store.scope_for_host("example.com"),
            "#submit",
            _png_with_patch(320, 240, {"x": 200.0, "y": 150.0, "width": 60.0, "height": 40.0}),
            left=200,
            top=150,
            width=60,
            height=40,
            method=MatchMethod.PLAYWRIGHT.value,
            confidence=0.95,
        )
        engine.screenshot = AsyncMock(return_value=_png_sized(320, 240, 255))
        executor = self._executor(engine, tmp_path)
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(selector="#submit"))

        result = await executor.execute_step(step)

        assert result.status == StepStatus.FAILED

    @pytest.mark.asyncio
    async def test_a_run_banks_a_picture_the_next_run_can_find(
        self, mock_engine: MagicMock, tmp_path: Path
    ) -> None:
        """The round trip, which is the only thing that proves the two halves agree.

        They did not. The executor banked under ``text or selector`` while the
        chain looked up ``text or image``, so a step named only by a selector —
        the step healing exists for, since a renamed selector is the failure
        being healed — banked a picture nothing could ever find. Both sides now
        call ``template_store.name_for``.
        """
        mock_engine.get_url = AsyncMock(return_value=self.URL)
        mock_engine._config = MagicMock(fast_mode=False, viewport_width=320, viewport_height=240)
        mock_engine.page = _page_with_one_element(dict(self.BOX))
        mock_engine.screenshot = AsyncMock(
            side_effect=itertools.chain(
                [self._screen()],
                (_png_sized(320, 240, s) for s in itertools.cycle((0, 200))),
            )
        )
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(selector="#submit"))

        banked = await self._executor(mock_engine, tmp_path).execute_step(step)

        assert banked.status == StepStatus.PASSED
        assert banked.match_result is not None
        assert banked.match_result.method == MatchMethod.PLAYWRIGHT

        # Next run: the selector names nothing, the element is still on screen.
        mock_engine.page = _page_with_no_element()
        self._screens_that_react(mock_engine)

        healed = await self._executor(mock_engine, tmp_path).execute_step(step)

        assert healed.status == StepStatus.PASSED
        assert healed.match_result is not None
        assert healed.match_result.method == MatchMethod.SAVED_TEMPLATE

    @pytest.mark.asyncio
    async def test_a_heal_is_recorded_as_its_own_strategy(
        self, engine: MagicMock, tmp_path: Path
    ) -> None:
        """"A banked picture carried this step" is advice about the scenario.

        Filed under ``use_template`` it would read as "image matching works
        here", when what happened is that the step's own selector is stale.
        """
        self._bank("#submit")
        executor = self._executor(engine, tmp_path)
        store = MagicMock()
        store.find_state_coords = MagicMock(return_value=None)
        store.find_by_name = MagicMock(return_value=None)
        store.get_strategies = MagicMock(return_value=[])
        store.get_target_failure_count = MagicMock(return_value=0)
        executor._learned_store = store
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(selector="#submit"))

        await executor.execute_step(step)

        assert store.record_match.call_args.kwargs["method"] == MatchMethod.SAVED_TEMPLATE.value
        assert store.learn_strategy.call_args[0][1] == "healed_from_bank"

    @pytest.mark.asyncio
    async def test_a_heal_does_not_rebank_from_where_it_matched(
        self, engine: MagicMock, tmp_path: Path
    ) -> None:
        """Otherwise each heal re-centres on the last heal's error and the crop walks."""
        self._bank("#submit")
        path = template_store.path_for(template_store.scope_for_host("example.com"), "#submit")
        before = path.read_bytes()
        executor = self._executor(engine, tmp_path)
        step = make_step(ActionType.FIND_AND_CLICK, target=TargetSpec(selector="#submit"))

        result = await executor.execute_step(step)

        assert result.status == StepStatus.PASSED
        assert path.read_bytes() == before
