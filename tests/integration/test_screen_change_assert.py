"""``assert_screen_changed`` compares two frames. This file says which two.

Measured on 2026-10-15 against a live app: an ``assert_screen_changed`` step
placed after a click that had just expanded an FAQ accordion reported
``Screen change 0.0%``. The run's own ``step006_after.png`` shows the accordion
open. No threshold could have made that step pass, and none of the 1,474 tests
in the repository could have gone red, because the defect lives in the seam
*between* two steps and every existing test drove the assertion on its own.

The cause was a single shared slot. ``_last_screenshot`` is re-taken at the
start of every step, so by the time the assert step read it, it held a frame
taken moments earlier in that same step -- after the accordion was already
open. The assertion was comparing a step's own start against its own end, with
no action in between. 0.0% was the only answer it could give.

The blast radius is why this matters more than one scenario: ``aat devqa``
auto-injects one of these steps after *every* click when verbosity is
``detailed``, so every AI-generated detailed scenario carried an un-passable
step per click -- and with early abort on, the first one turned every step
after it into ``unverified``.

Both directions are mandatory here, and the second is not a formality. The
repair moves which frame the assertion reads; a version that reads "the frame
before anything happened, ever" would pass this file's first test and would
also pass on a click that missed its target entirely. That is the failure the
repository spent AAT-109, AAT-123 and AAT-124 removing, and it must not come
back through the assertion. So the fixture serves an inert button, and the
second test presses it.

Two consecutive assertions are covered too, because the smallest possible
repair (skip the re-take when the step is an assert) would have made the
second one compare against the first one's baseline and pass on no new change
at all. The rolling slot used instead gives the second assert the frame from
before the first assert -- which is post-click, so it correctly reads 0%.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from aat.core.models import (
    ActionType,
    EngineConfig,
    MatchingConfig,
    StepConfig,
    StepStatus,
    TargetSpec,
)
from aat.engine.comparator import Comparator
from aat.engine.executor import StepExecutor
from aat.engine.humanizer import Humanizer
from aat.engine.waiter import Waiter
from aat.engine.web import WebEngine
from aat.matchers.hybrid import HybridMatcher
from aat.matchers.template import TemplateMatcher
from tests.fixtures.screen_change_server import screen_change_server


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    with screen_change_server() as url:
        yield url


@pytest.fixture()
async def engine() -> AsyncIterator[WebEngine]:
    eng = WebEngine(EngineConfig(headless=True, speed="fast", screenshot_mode="off"))
    try:
        await eng.start()
    except Exception as e:  # noqa: BLE001 — environment without the browser binary
        pytest.skip(f"Chromium unavailable: {e}")
    try:
        yield eng
    finally:
        await eng.stop()


def _executor(engine: WebEngine, tmp_path: Path) -> StepExecutor:
    return StepExecutor(
        engine,
        HybridMatcher([TemplateMatcher(MatchingConfig())]),
        Humanizer(),
        Waiter(),
        Comparator(),
        tmp_path,
        learned_store=None,
    )


def _click(step: int, selector: str) -> StepConfig:
    return StepConfig(
        step=step,
        action=ActionType.FIND_AND_CLICK,
        target=TargetSpec(selector=selector),
        description=f"click {selector}",
    )


def _assert_changed(step: int, threshold: float = 0.05) -> StepConfig:
    return StepConfig(
        step=step,
        action=ActionType.ASSERT_SCREEN_CHANGED,
        threshold=threshold,
        description="the previous step should have changed the screen",
    )


class TestScreenChangeAfterARealChange:
    """The direction the live run proved broken: a change that must be seen."""

    async def test_assert_passes_after_a_click_that_expands_a_panel(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """The accordion case, reduced: click, then assert, in that order.

        This is the whole bug. Run the assert step on its own and it has
        always been 0.0%; run it one slot behind a step that did something and
        it has to see that something.
        """
        ex = _executor(engine, tmp_path)
        await engine.navigate(base_url)

        clicked = await ex.execute_step(_click(1, "#expand"))
        assert clicked.status == StepStatus.PASSED

        asserted = await ex.execute_step(_assert_changed(2))
        assert asserted.status == StepStatus.PASSED, asserted.error_message

    async def test_the_panel_really_did_open(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """Guard the fixture, not the product.

        If ``#expand`` ever stops expanding, the test above would start
        measuring nothing while still having something to fail on -- and the
        test below it would pass for the wrong reason. The live run had its
        own ``step006_after.png`` to settle this; here the DOM says it.
        """
        ex = _executor(engine, tmp_path)
        await engine.navigate(base_url)

        assert await engine.page.locator("#panel").is_visible() is False
        await ex.execute_step(_click(1, "#expand"))
        assert await engine.page.locator("#panel").is_visible() is True


class TestScreenChangeWhenNothingHappened:
    """The direction a careless repair breaks: no change must stay a failure."""

    async def test_assert_fails_after_a_click_that_moves_nothing(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """``#inert`` is wired to nothing, so the assertion has to say so.

        A repair that simply reached further back for its baseline -- to the
        first frame of the run, say -- would pass the test above and also pass
        here, and the whole point of the assertion is that it does not.
        """
        ex = _executor(engine, tmp_path)
        await engine.navigate(base_url)

        clicked = await ex.execute_step(_click(1, "#inert"))
        assert clicked.status in (StepStatus.PASSED, StepStatus.WARNING)

        asserted = await ex.execute_step(_assert_changed(2))
        assert asserted.status == StepStatus.FAILED
        assert "below threshold" in (asserted.error_message or "")

    async def test_second_consecutive_assert_fails_on_the_same_change(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """One change may satisfy one assertion, not two.

        This is the test that rules out the smaller repair. Skipping the
        baseline re-take on assert steps would leave both assertions reading
        the same pre-click frame, and the second would pass on a change it did
        not witness. Rolling the slot once per step gives assert #2 the frame
        from before assert #1 -- already post-click -- so it correctly reads
        no change.
        """
        ex = _executor(engine, tmp_path)
        await engine.navigate(base_url)

        await ex.execute_step(_click(1, "#expand"))
        first = await ex.execute_step(_assert_changed(2))
        assert first.status == StepStatus.PASSED

        second = await ex.execute_step(_assert_changed(3))
        assert second.status == StepStatus.FAILED
        assert "below threshold" in (second.error_message or "")


class TestScreenChangeBaselineSlot:
    """The slot itself: it must not be the one four other features read."""

    async def test_assert_baseline_is_not_the_pre_action_frame(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """``_last_screenshot`` keeps its meaning; the assertion gets its own.

        The no-effect check, the before/after screenshot mode and template
        cropping all read ``_last_screenshot`` and all want "the frame at the
        start of this step". Widening that slot to serve the assertion too
        would have moved the pixels those three compare against. They are
        separate fields precisely so that cannot happen, and this is the test
        that says so.
        """
        ex = _executor(engine, tmp_path)
        await engine.navigate(base_url)

        await ex.execute_step(_click(1, "#expand"))
        await ex.execute_step(_click(2, "#inert"))

        assert ex._last_screenshot is not None
        assert ex._assert_baseline is not None
        assert ex._assert_baseline != ex._last_screenshot

    async def test_first_step_has_no_baseline_and_does_not_crash(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """An assertion written as step 1 has nothing to compare against.

        It cannot be a failure -- the scenario author asked an unanswerable
        question, and failing it would blame the page. The pre-existing
        behaviour is to log and pass; the new slot must not turn that into an
        exception on the first step of every run.
        """
        ex = _executor(engine, tmp_path)
        await engine.navigate(base_url)

        result = await ex.execute_step(_assert_changed(1))
        assert result.status == StepStatus.PASSED

    def test_run_cmd_clears_both_slots_between_scenarios(self) -> None:
        """One executor runs every scenario in the file, one after another.

        ``_last_screenshot`` was already cleared between them. A new slot left
        uncleared would hand the next scenario's first assertion a frame from
        the previous scenario's last step -- a different page entirely, so it
        would pass on a change nothing in that scenario made. The end-to-end
        route cannot be driven from a test (it passes the approval gate, which
        reads ``/dev/tty``), so the wiring is what gets checked.
        """
        source = Path("src/aat/cli/commands/run_cmd.py").read_text(encoding="utf-8")

        assert "executor._assert_baseline = None" in source
