"""StepExecutor — individual test step runner.

Orchestrates: screenshot_before → wait → match → action → compare → screenshot_after
All dependencies are injected via constructor for testability.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from aat.core.exceptions import MatchError, StepExecutionError
from aat.core.models import (
    FIND_ACTIONS,
    ActionType,
    StepResult,
    StepStatus,
)

if TYPE_CHECKING:
    from aat.core.models import MatchResult, StepConfig, TargetSpec
    from aat.engine.base import BaseEngine
    from aat.engine.comparator import Comparator
    from aat.engine.humanizer import Humanizer
    from aat.engine.waiter import Waiter
    from aat.matchers.base import BaseMatcher


def _parse_coordinates(value: str | None) -> tuple[int, int]:
    """Parse 'x,y' coordinate string.

    Args:
        value: Coordinate string like '100,200'.

    Returns:
        Tuple of (x, y) integers.
    """
    if not value:
        msg = "click_at requires value in 'x,y' format"
        raise StepExecutionError(msg, step=0, action="click_at")
    parts = value.split(",")
    if len(parts) != 2:
        msg = f"Invalid coordinate format: '{value}'. Expected 'x,y'"
        raise StepExecutionError(msg, step=0, action="click_at")
    try:
        return int(parts[0].strip()), int(parts[1].strip())
    except ValueError as e:
        msg = f"Invalid coordinate values: '{value}'"
        raise StepExecutionError(msg, step=0, action="click_at") from e


def _parse_scroll_params(value: str | None) -> tuple[int, int, int]:
    """Parse 'x,y,delta' scroll parameter string.

    Args:
        value: Scroll params like '100,200,300'.

    Returns:
        Tuple of (x, y, delta) integers.
    """
    if not value:
        msg = "scroll requires value in 'x,y,delta' format"
        raise StepExecutionError(msg, step=0, action="scroll")
    parts = value.split(",")
    if len(parts) != 3:
        msg = f"Invalid scroll format: '{value}'. Expected 'x,y,delta'"
        raise StepExecutionError(msg, step=0, action="scroll")
    try:
        return int(parts[0].strip()), int(parts[1].strip()), int(parts[2].strip())
    except ValueError as e:
        msg = f"Invalid scroll values: '{value}'"
        raise StepExecutionError(msg, step=0, action="scroll") from e


class StepExecutor:
    """Execute individual test steps.

    All dependencies are injected via constructor for independent testing.
    """

    def __init__(
        self,
        engine: BaseEngine,
        matcher: BaseMatcher,
        humanizer: Humanizer,
        waiter: Waiter,
        comparator: Comparator,
        screenshot_dir: Path | None = None,
    ) -> None:
        self._engine = engine
        self._matcher = matcher
        self._humanizer = humanizer
        self._waiter = waiter
        self._comparator = comparator
        self._screenshot_dir = screenshot_dir or Path(".aat/screenshots")

    async def execute_step(self, step: StepConfig) -> StepResult:
        """Execute a single test step.

        Flow: screenshot_before → wait → match → action → compare → screenshot_after

        Args:
            step: Step configuration to execute.

        Returns:
            StepResult with pass/fail status.
        """
        start = time.monotonic()
        screenshots: dict[str, str | None] = {"before": None, "after": None}

        try:
            # 1. screenshot_before
            if step.screenshot_before:
                screenshots["before"] = await self._save_screenshot("before")

            # 2. Execute action
            match_result = await self._dispatch_action(step)

            # 3. screenshot_after
            if step.screenshot_after:
                screenshots["after"] = await self._save_screenshot("after")

            # 4. Check step-level expected results
            if step.expected:
                for exp in step.expected:
                    await self._comparator.check(exp, self._engine)

            elapsed = (time.monotonic() - start) * 1000
            return StepResult(
                step=step.step,
                action=step.action,
                status=StepStatus.PASSED,
                description=step.description,
                match_result=match_result,
                screenshot_before=screenshots["before"],
                screenshot_after=screenshots["after"],
                elapsed_ms=elapsed,
            )

        except (StepExecutionError, MatchError) as e:
            elapsed = (time.monotonic() - start) * 1000
            status = StepStatus.SKIPPED if step.optional else StepStatus.FAILED
            return StepResult(
                step=step.step,
                action=step.action,
                status=status,
                description=step.description,
                error_message=str(e),
                elapsed_ms=elapsed,
            )

    async def _dispatch_action(self, step: StepConfig) -> MatchResult | None:
        """Dispatch step action to the appropriate handler.

        Args:
            step: Step configuration.

        Returns:
            MatchResult if a find_and_* action was performed, else None.
        """
        match_result: MatchResult | None = None

        if step.action in FIND_ACTIONS:
            match_result = await self._find_and_act(step)

        elif step.action == ActionType.NAVIGATE:
            await self._engine.navigate(step.value or "")

        elif step.action == ActionType.CLICK_AT:
            x, y = _parse_coordinates(step.value)
            await self._do_click(x, y, step.humanize)

        elif step.action == ActionType.TYPE_TEXT:
            await self._do_type(step.value or "", step.humanize)

        elif step.action == ActionType.PRESS_KEY:
            await self._engine.press_key(step.value or "")

        elif step.action == ActionType.KEY_COMBO:
            keys = (step.value or "").split("+")
            await self._engine.key_combo(*keys)

        elif step.action == ActionType.ASSERT:
            await self._comparator.check_assert(step, self._engine)

        elif step.action == ActionType.WAIT:
            await asyncio.sleep(int(step.value or "1000") / 1000)

        elif step.action == ActionType.SCREENSHOT:
            await self._save_screenshot("manual")

        elif step.action == ActionType.SCROLL:
            x, y, delta = _parse_scroll_params(step.value)
            await self._engine.scroll(x, y, delta)

        elif step.action == ActionType.GO_BACK:
            await self._engine.go_back()

        elif step.action == ActionType.REFRESH:
            await self._engine.refresh()

        return match_result

    async def _find_and_act(self, step: StepConfig) -> MatchResult:
        """Find target and perform action: wait → match → action.

        Args:
            step: Step with a find_and_* action and target.

        Returns:
            MatchResult from successful match.

        Raises:
            MatchError: If target not found.
        """
        target: TargetSpec = step.target  # type: ignore[assignment]

        # Try Playwright native text search first (no screenshot needed)
        if target.text and hasattr(self._engine, "find_text_position"):
            pos = await self._engine.find_text_position(target.text)
            if pos is not None:
                from aat.core.models import MatchMethod, MatchResult as MR

                result = MR(
                    found=True, x=pos[0], y=pos[1],
                    confidence=1.0, method=MatchMethod.OCR,
                )
                x, y = result.x, result.y
                if step.action in (
                    ActionType.FIND_AND_CLICK,
                    ActionType.FIND_AND_DOUBLE_CLICK,
                    ActionType.FIND_AND_RIGHT_CLICK,
                ):
                    await self._do_click(
                        x, y, step.humanize,
                        double=(step.action == ActionType.FIND_AND_DOUBLE_CLICK),
                        right=(step.action == ActionType.FIND_AND_RIGHT_CLICK),
                    )
                elif step.action == ActionType.FIND_AND_TYPE:
                    await self._do_click(x, y, step.humanize)
                    await self._do_type(step.value or "", step.humanize)
                elif step.action == ActionType.FIND_AND_CLEAR:
                    await self._do_click(x, y, step.humanize)
                    await self._engine.key_combo("Control", "a")
                    await self._engine.press_key("Delete")
                return result

        # Fallback: screenshot + matcher pipeline (OCR/template/feature)
        screenshot = await self._engine.screenshot()
        result = await self._matcher.find(target, screenshot)
        if result is None or not result.found:
            target_desc = target.image or target.text or "unknown"
            msg = f"Target '{target_desc}' not found"
            raise MatchError(msg)

        # Perform action at matched location
        x, y = result.x, result.y
        if step.action in (
            ActionType.FIND_AND_CLICK,
            ActionType.FIND_AND_DOUBLE_CLICK,
            ActionType.FIND_AND_RIGHT_CLICK,
        ):
            await self._do_click(
                x,
                y,
                step.humanize,
                double=(step.action == ActionType.FIND_AND_DOUBLE_CLICK),
                right=(step.action == ActionType.FIND_AND_RIGHT_CLICK),
            )
        elif step.action == ActionType.FIND_AND_TYPE:
            await self._do_click(x, y, step.humanize)
            await self._do_type(step.value or "", step.humanize)
        elif step.action == ActionType.FIND_AND_CLEAR:
            await self._do_click(x, y, step.humanize)
            await self._engine.key_combo("Control", "a")
            await self._engine.press_key("Delete")

        return result

    async def _do_click(
        self,
        x: int,
        y: int,
        humanize: bool,
        *,
        double: bool = False,
        right: bool = False,
    ) -> None:
        """Click at coordinates with optional humanization.

        Args:
            x: Target x coordinate.
            y: Target y coordinate.
            humanize: Whether to use humanized mouse movement.
            double: Double-click if True.
            right: Right-click if True.
        """
        if humanize:
            await self._humanizer.move_to(self._engine, x, y)
        if double:
            await self._engine.double_click(x, y)
        elif right:
            await self._engine.right_click(x, y)
        else:
            await self._engine.click(x, y)

    async def _do_type(self, text: str, humanize: bool) -> None:
        """Type text with optional humanization.

        Args:
            text: Text to type.
            humanize: Whether to use humanized typing.
        """
        if humanize:
            await self._humanizer.type_text(self._engine, text)
        else:
            await self._engine.type_text(text)

    async def _save_screenshot(self, label: str) -> str:
        """Save screenshot and return file path.

        Args:
            label: Screenshot label (before, after, manual).

        Returns:
            Path string of saved screenshot.
        """
        filename = f"{label}_{uuid.uuid4().hex[:8]}.png"
        path = self._screenshot_dir / filename
        await self._engine.save_screenshot(path)
        return str(path)
