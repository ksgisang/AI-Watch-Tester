"""Tests for StepExecutor — individual test step runner.

Uses mock dependencies to test all ActionType dispatching.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from aat.core.exceptions import StepExecutionError
from aat.core.models import (
    ActionType,
    AssertType,
    ExpectedResult,
    MatchResult,
    StepConfig,
    StepStatus,
    TargetSpec,
)
from aat.engine.executor import _SYNONYMS, StepExecutor, _parse_coordinates, _parse_scroll_params

if TYPE_CHECKING:
    from pathlib import Path


# ─── Fixtures ────────────────────────────────────────────────


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
    engine.screenshot = AsyncMock(return_value=b"png_data")
    engine.save_screenshot = AsyncMock()
    engine.get_page_text = AsyncMock(return_value="Page text")
    engine.get_url = AsyncMock(return_value="https://example.com/page")
    engine.find_text_position = AsyncMock(return_value=None)
    # Explicitly remove attributes so hasattr() returns False
    # (MagicMock auto-creates any attribute, breaking the screen-coord code path)
    del engine.find_on_screen
    del engine.scroll_to_top
    del engine.force_click_by_text
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
        engine.screenshot = AsyncMock(return_value=b"png")
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
        engine.screenshot = AsyncMock(return_value=b"png")
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
        engine.screenshot = AsyncMock(return_value=b"png")
        engine.save_screenshot = AsyncMock()
        del engine.find_on_screen

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
        engine.screenshot = AsyncMock(return_value=b"png")
        engine.save_screenshot = AsyncMock()
        del engine.find_on_screen
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
        engine.screenshot = AsyncMock(return_value=b"png")
        engine.save_screenshot = AsyncMock()
        del engine.find_on_screen

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
        engine.screenshot = AsyncMock(return_value=b"png")
        engine.save_screenshot = AsyncMock()
        del engine.find_on_screen

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
        engine.screenshot = AsyncMock(return_value=b"png")
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
        engine.screenshot = AsyncMock(return_value=b"png")
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
        engine.screenshot = AsyncMock(return_value=b"png")
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
        engine.screenshot = AsyncMock(return_value=b"png")
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
        engine.screenshot = AsyncMock(return_value=b"png")
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
        engine.screenshot = AsyncMock(return_value=b"png")
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
