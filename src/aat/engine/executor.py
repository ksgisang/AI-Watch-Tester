"""StepExecutor — individual test step runner.

Orchestrates: screenshot_before → wait → match → action → compare → screenshot_after
All dependencies are injected via constructor for testability.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

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


_SYNONYMS: dict[str, list[str]] = {
    "email": ["이메일", "e-mail", "이메일 주소"],
    "이메일": ["email", "e-mail"],
    "이메일 주소": ["email", "이메일"],
    "password": ["비밀번호", "패스워드"],
    "비밀번호": ["password", "패스워드"],
    "패스워드": ["password", "비밀번호"],
    "login": ["로그인", "sign in", "log in"],
    "로그인": ["login", "sign in", "log in"],
    "sign in": ["로그인", "login"],
    "register": ["회원가입", "sign up", "signup"],
    "회원가입": ["register", "sign up", "가입하기"],
    "search": ["검색", "찾기"],
    "검색": ["search"],
    "submit": ["제출", "확인", "전송"],
    "제출": ["submit", "확인"],
    "확인": ["submit", "제출", "ok", "confirm"],
}


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

            # 4. Check step-level expected results (skip for assert action,
            #    already handled in check_assert)
            if step.expected and step.action != ActionType.ASSERT:
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
        except Exception as e:  # noqa: BLE001
            elapsed = (time.monotonic() - start) * 1000
            error_msg = str(e) or f"{type(e).__name__}"
            return StepResult(
                step=step.step,
                action=step.action,
                status=StepStatus.FAILED,
                description=step.description,
                error_message=error_msg,
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

            # Post-click wait: detect navigation or modal animation
            if step.action in (
                ActionType.FIND_AND_CLICK,
                ActionType.FIND_AND_DOUBLE_CLICK,
                ActionType.FIND_AND_RIGHT_CLICK,
            ):
                await self._post_click_wait()

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

    async def _find_text_with_synonyms(self, text: str) -> tuple[int, int] | None:
        """Try find_text_position with synonym fallback."""
        pos = await self._engine.find_text_position(text)
        if pos is None:
            for syn in _SYNONYMS.get(text.lower(), []):
                pos = await self._engine.find_text_position(syn)
                if pos is not None:
                    break
        return pos

    async def _find_input_field(self, step: StepConfig) -> tuple[int, int] | None:
        """Enhanced input field finding for find_and_type.

        Fallback chain when CSS selector fails:
        1. placeholder text match (partial)
        2. get_by_label
        3. aria-label match
        4. Short text prefix match (e.g. "이메일" from "이메일을 입력하세요")
        5. input[type] match (email, password) inferred from selector/text

        Returns None if page is not a real Playwright page.
        """
        try:
            return await self._find_input_field_inner(step)
        except Exception:
            return None

    async def _find_input_field_inner(self, step: StepConfig) -> tuple[int, int] | None:
        """Inner implementation — may raise on non-Playwright pages."""
        page = self._engine.page  # type: ignore[attr-defined]
        target: TargetSpec = step.target  # type: ignore[assignment]
        text = target.text or ""
        selector = target.selector or ""

        locators: list[Any] = []

        # Build list of text variants: original + synonyms
        text_variants = [text] if text else []
        if text:
            for syn in _SYNONYMS.get(text.lower(), []):
                if syn.lower() != text.lower():
                    text_variants.append(syn)

        for variant in text_variants:
            # 1. placeholder partial match
            locators.append(page.locator(f'input[placeholder*="{variant}"]').first)
            locators.append(
                page.locator(f'textarea[placeholder*="{variant}"]').first,
            )
            # 2. label
            locators.append(page.get_by_label(variant, exact=False).first)
            # 3. aria-label
            locators.append(page.locator(f'[aria-label*="{variant}"]').first)
            # 4. Short prefix match (first meaningful segment)
            #    e.g. "이메일을 입력하세요" → try "이메일"
            for sep in ["을 ", "를 ", "을", "를", " "]:
                if sep in variant:
                    short = variant.split(sep)[0].strip()
                    if short and short != variant:
                        locators.append(
                            page.locator(f'input[placeholder*="{short}"]').first,
                        )
                        locators.append(
                            page.get_by_label(short, exact=False).first,
                        )
                    break

        # 5. Type-based inference from selector or text (includes synonyms)
        hint = (selector + " " + " ".join(text_variants)).lower()
        if any(k in hint for k in ("email", "mail", "이메일")):
            locators.append(page.locator('input[type="email"]').first)
        if any(k in hint for k in ("password", "비밀번호", "패스워드")):
            locators.append(page.locator('input[type="password"]').first)
        if any(k in hint for k in ("tel", "전화", "연락처", "핸드폰")):
            locators.append(page.locator('input[type="tel"]').first)
        if any(k in hint for k in ("search", "검색", "찾기")):
            locators.append(page.locator('input[type="search"]').first)

        for loc in locators:
            try:
                if await loc.count() > 0:
                    with contextlib.suppress(Exception):
                        await loc.scroll_into_view_if_needed(timeout=2000)
                    box = await loc.bounding_box()
                    if box:
                        return (
                            int(box["x"] + box["width"] / 2),
                            int(box["y"] + box["height"] / 2),
                        )
            except Exception:
                continue

        return None

    async def _act_at_pos(
        self, step: StepConfig, x: int, y: int, confidence: float = 1.0,
    ) -> MatchResult:
        """Execute find_and_* action at given position, return MatchResult."""
        from aat.core.models import MatchMethod, MatchResult

        result = MatchResult(
            found=True, x=x, y=y, confidence=confidence, method=MatchMethod.OCR,
        )
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

    async def _find_and_act(self, step: StepConfig) -> MatchResult:
        """Find target and perform action: wait → match → action.

        Fallback chain:
        0. CSS selector (highest priority — from crawl observation data)
        1. find_text_position (+ synonyms)
        2. scroll_to_top + retry find_text_position
        3. force_click_by_text (JS click, bypasses sticky headers)

        Args:
            step: Step with a find_and_* action and target.

        Returns:
            MatchResult from successful match.

        Raises:
            MatchError: If target not found.
        """
        target: TargetSpec = step.target  # type: ignore[assignment]

        # Priority 0: CSS selector (from observation data)
        # When both selector and text are provided, filter by text
        # to avoid clicking the wrong element (e.g., "로그인" instead of "가입"
        # when both share selector "button.MuiButtonBase-root")
        if target.selector and hasattr(self._engine, "page"):
            page = self._engine.page
            for attempt in range(3):
                try:
                    base_loc = page.locator(target.selector)
                    # Filter by text if available (critical for generic selectors)
                    if target.text:
                        loc = base_loc.filter(has_text=target.text).first
                        # Fallback to unfiltered if text filter matches nothing
                        if await loc.count() == 0:
                            loc = base_loc.first
                    else:
                        loc = base_loc.first
                    if await loc.count() > 0:
                        with contextlib.suppress(Exception):
                            await loc.scroll_into_view_if_needed(timeout=2000)
                        box = await loc.bounding_box()
                        if box:
                            x = int(box["x"] + box["width"] / 2)
                            y = int(box["y"] + box["height"] / 2)
                            return await self._act_at_pos(step, x, y, confidence=1.0)
                except Exception:
                    pass
                if attempt < 2:
                    await asyncio.sleep(0.5)

        # Priority 0.5: Enhanced input finding for find_and_type
        if step.action == ActionType.FIND_AND_TYPE and hasattr(self._engine, "page"):
            pos = await self._find_input_field(step)
            if pos is not None:
                return await self._act_at_pos(step, pos[0], pos[1], confidence=0.9)

        # Try Playwright native text search first (no screenshot needed)
        if target.text and hasattr(self._engine, "find_text_position"):
            pos = await self._find_text_with_synonyms(target.text)
            if pos is not None:
                return await self._act_at_pos(step, pos[0], pos[1])

            # Fallback 2: scroll to top + retry
            if hasattr(self._engine, "scroll_to_top"):
                await self._engine.scroll_to_top()
                pos = await self._find_text_with_synonyms(target.text)
                if pos is not None:
                    return await self._act_at_pos(step, pos[0], pos[1])

            # Fallback 3: JS force click via locator (bypasses sticky headers)
            if hasattr(self._engine, "force_click_by_text"):
                from aat.core.models import MatchMethod, MatchResult

                texts_to_try = [target.text] + _SYNONYMS.get(target.text.lower(), [])
                for t in texts_to_try:
                    if await self._engine.force_click_by_text(t):
                        result = MatchResult(
                            found=True, x=0, y=0, confidence=0.8,
                            method=MatchMethod.OCR,
                        )
                        if step.action == ActionType.FIND_AND_TYPE:
                            await self._do_type(step.value or "", step.humanize)
                        elif step.action == ActionType.FIND_AND_CLEAR:
                            await self._engine.key_combo("Control", "a")
                            await self._engine.press_key("Delete")
                        return result

        # Try PyAutoGUI screen search (DesktopEngine, image target)
        if target.image and hasattr(self._engine, "find_on_screen"):
            confidence = target.confidence or 0.8
            coords = await self._engine.find_on_screen(target.image, confidence)
            if coords is not None:
                from aat.core.models import MatchMethod, MatchResult

                sx, sy = coords
                result = MatchResult(
                    found=True,
                    x=sx,
                    y=sy,
                    confidence=confidence,
                    method=MatchMethod.TEMPLATE,
                )
                if step.action in (
                    ActionType.FIND_AND_CLICK,
                    ActionType.FIND_AND_DOUBLE_CLICK,
                    ActionType.FIND_AND_RIGHT_CLICK,
                ):
                    await self._do_click_screen(
                        sx,
                        sy,
                        step.humanize,
                        double=(step.action == ActionType.FIND_AND_DOUBLE_CLICK),
                        right=(step.action == ActionType.FIND_AND_RIGHT_CLICK),
                    )
                elif step.action == ActionType.FIND_AND_TYPE:
                    await self._do_click_screen(sx, sy, step.humanize)
                    await self._do_type(step.value or "", step.humanize)
                elif step.action == ActionType.FIND_AND_CLEAR:
                    await self._do_click_screen(sx, sy, step.humanize)
                    await self._engine.key_combo("Control", "a")
                    await self._engine.press_key("Delete")
                return result

        # Fallback: screenshot + matcher pipeline (OCR/template/feature)
        screenshot = await self._engine.screenshot()
        match_result = await self._matcher.find(target, screenshot)
        if match_result is None or not match_result.found:
            target_desc = target.image or target.text or "unknown"
            msg = f"Target '{target_desc}' not found"
            raise MatchError(msg)

        # Perform action at matched location
        return await self._act_at_pos(
            step, match_result.x, match_result.y, match_result.confidence,
        )

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

    async def _do_click_screen(
        self,
        x: int,
        y: int,
        humanize: bool,
        *,
        double: bool = False,
        right: bool = False,
    ) -> None:
        """Click using screen coordinates (for PyAutoGUI find_on_screen results).

        No viewport-to-screen conversion is applied.
        """
        if humanize:
            await self._humanizer.move_to_screen(self._engine, x, y)
        if double:
            await self._engine.double_click_on_screen(x, y)  # type: ignore[attr-defined]
        elif right:
            await self._engine.right_click_on_screen(x, y)  # type: ignore[attr-defined]
        else:
            await self._engine.click_on_screen(x, y)  # type: ignore[attr-defined]

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

    async def _post_click_wait(self) -> None:
        """Wait for potential navigation or modal animation after click.

        Lightweight: only waits if URL actually changes.
        - URL changed → wait_for_load_state("domcontentloaded") (fast, max 3s)
        - URL unchanged → minimal delay (300ms) for modal/animation start
        """
        if not hasattr(self._engine, "page"):
            return
        try:
            page = self._engine.page
            url_before = page.url

            # Minimal pause to let navigation start
            await asyncio.sleep(0.15)

            url_after = page.url
            if url_after != url_before:
                # Navigation detected — wait for DOM ready (fast, not networkidle)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=3000)
                except Exception:
                    pass
            else:
                # No navigation — brief delay for modal/animation
                await asyncio.sleep(0.3)
        except Exception:
            pass

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
