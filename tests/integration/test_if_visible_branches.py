"""``if_visible`` has two branches. This is the one place both are measured.

On 2026-03-24 ``if_visible`` was reported doing the opposite of what it says:
a help popup that was not open ran its dismiss block anyway, three times, and
then failed the step. ``0516fd9`` fixed the cause -- the visibility check took
any DOM node whose text matched and never asked whether that node was on
screen -- and shipped with no test. A fix with no reproduction is a claim, so
the report stayed open until this file.

What a branch test has to show is not that the code runs but that the two
branches *differ*, and only in the one thing they are supposed to differ in.
So every mode of the fixture serves the same witness button, outside the
popup, always pressable, and ``then`` does nothing but press it. The counter it
bumps is the answer: 1 means the branch ran, 0 means it did not. Without that,
"``then`` was skipped" and "``then`` ran and found nothing to do" are the same
observation.

Mocks are no use here. Whether Playwright reports a node inside a collapsed
menu as visible, and what ``bounding_box`` says about it, are facts about
Chromium -- and they are the whole question. Measured against this fixture:

    mode        count  is_visible  bounding_box
    modal       1      True        y = 160
    clean       0      --          --
    hidden      1      False       None          <- display: none
    collapsed   1      True        y = 194.5     <- height: 0; overflow: hidden

The third row is the 2026-03-24 report and the reason the fix works. The fourth
is a hole the fix did not close, found by writing this file: see
``TestAClippedAncestorIsStillHidden`` at the bottom, which is marked ``xfail``
rather than quietly deleted, because a comment does not run.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from aat.core.exceptions import StepExecutionError
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
from tests.fixtures.dismissible_popup_server import (
    POPUP_TEXT,
    TALLY_SELECTOR,
    WITNESS_SELECTOR,
    dismissible_popup_server,
)


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    with dismissible_popup_server() as url:
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
    """Executor with no learned store.

    A remembered position answers before the DOM on some paths, and this file
    is asking what the *visibility check* decides. Nothing may be able to
    answer on its behalf.
    """
    return StepExecutor(
        engine,
        HybridMatcher([TemplateMatcher(MatchingConfig())]),
        Humanizer(),
        Waiter(),
        Comparator(),
        tmp_path,
        learned_store=None,
    )


def _dismiss_step() -> StepConfig:
    """``if_visible`` in its block form: watch for the popup, press WITNESS."""
    return StepConfig(
        step=1,
        action=ActionType.IF_VISIBLE,
        target=TargetSpec(text=POPUP_TEXT),
        then=[
            {
                "action": "find_and_click",
                "target": {"selector": WITNESS_SELECTOR},
                "description": "press the witness",
            }
        ],
        description=f"dismiss '{POPUP_TEXT}' if it is up",
    )


def _gated_step() -> StepConfig:
    """``if_visible`` in its flag form: a normal step that only runs if present.

    The other half of the feature, and a different code path -- the flag is
    checked in ``execute_step`` before dispatch, while the block form goes
    through ``_handle_if_visible_block``. Both call the same predicate, so both
    inherited the same defect, and a test of one says nothing about the other.
    """
    return StepConfig(
        step=1,
        action=ActionType.FIND_AND_CLICK,
        target=TargetSpec(text=POPUP_TEXT),
        if_visible=True,
        description=f"click '{POPUP_TEXT}' only if it is up",
    )


async def _open(engine: WebEngine, base_url: str, mode: str) -> None:
    await engine.navigate(f"{base_url}/?mode={mode}")


async def _tally(engine: WebEngine) -> int:
    return int(await engine.page.locator(TALLY_SELECTOR).inner_text())


async def _matches_in_dom(engine: WebEngine) -> int:
    return int(await engine.page.get_by_text(POPUP_TEXT, exact=False).count())


class TestThePopupIsUp:
    """Branch one: the thing is on screen, so ``then`` runs."""

    @pytest.mark.asyncio
    async def test_then_runs_and_leaves_its_mark(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        await _open(engine, base_url, "modal")
        assert await _tally(engine) == 0

        result = await _executor(engine, tmp_path).execute_step(_dismiss_step())

        assert result.status == StepStatus.PASSED
        assert await _tally(engine) == 1, "then did not run while the popup was up"

    @pytest.mark.asyncio
    async def test_the_popup_is_gone_afterwards(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """Dismissal is the point, not a side effect.

        The block form re-checks after ``then`` and retries up to three times;
        a run that ended with the popup still up would have pressed the witness
        three times and then failed. One press is the whole contract.
        """
        await _open(engine, base_url, "modal")
        await _executor(engine, tmp_path).execute_step(_dismiss_step())

        assert await _matches_in_dom(engine) == 0
        assert await _tally(engine) == 1, "then ran more than once, so a retry fired"

    @pytest.mark.asyncio
    async def test_the_gated_step_runs(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        await _open(engine, base_url, "modal")
        result = await _executor(engine, tmp_path).execute_step(_gated_step())

        assert result.status == StepStatus.PASSED
        assert await _tally(engine) == 1, "the gated step was not actually dispatched"


class TestThePopupIsNotThere:
    """Branch two: nothing on screen, so the step is a no-op.

    Not just "it did not crash" -- skipping has to be observable, and it has to
    leave the page untouched. A dismiss block that runs against a page with no
    popup is how the 2026-03-24 report started.
    """

    @pytest.mark.asyncio
    async def test_then_does_not_run(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        await _open(engine, base_url, "clean")
        result = await _executor(engine, tmp_path).execute_step(_dismiss_step())

        assert result.status == StepStatus.PASSED
        assert await _tally(engine) == 0, "then ran with no popup on the page"

    @pytest.mark.asyncio
    async def test_the_gated_step_reports_skipped_not_passed(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """``SKIPPED``, and not ``PASSED``.

        The two are the same to an exit code and different to a reader: this
        repository's standing rule is that a step which did not happen must not
        be counted as one that did.
        """
        await _open(engine, base_url, "clean")
        result = await _executor(engine, tmp_path).execute_step(_gated_step())

        assert result.status == StepStatus.SKIPPED
        assert await _tally(engine) == 0


class TestTextInTheDomIsNotTextOnTheScreen:
    """The 2026-03-24 report, reduced to one page.

    A ``display: none`` nav link carrying the same words, and no popup. Before
    ``0516fd9`` a text search was the whole check, so this page ran the dismiss
    block, failed to dismiss anything, retried three times and failed the step
    -- which is what "the opposite of what it says" meant.
    """

    @pytest.mark.asyncio
    async def test_the_match_really_is_in_the_dom(self, engine: WebEngine, base_url: str) -> None:
        """First, that the fixture still poses the question.

        Playwright's text search returning hidden nodes is the premise of the
        whole defect. If a future version filtered them out, every test below
        would pass without exercising anything, so the premise is asserted
        rather than assumed.
        """
        await _open(engine, base_url, "hidden")
        assert await _matches_in_dom(engine) == 1
        assert await engine.page.get_by_text(POPUP_TEXT, exact=False).first.is_visible() is False

    @pytest.mark.asyncio
    async def test_then_does_not_run(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        await _open(engine, base_url, "hidden")
        result = await _executor(engine, tmp_path).execute_step(_dismiss_step())

        assert result.status == StepStatus.PASSED
        assert await _tally(engine) == 0, (
            "a hidden DOM node convinced if_visible the popup was up -- "
            "this is the 2026-03-24 regression"
        )

    @pytest.mark.asyncio
    async def test_the_step_does_not_fail_trying_to_dismiss_nothing(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """The reported symptom, named separately from its cause.

        What the user saw was not "the branch ran"; it was a red step on a page
        that was fine, because three dismiss attempts could not make a hidden
        nav link go away.
        """
        await _open(engine, base_url, "hidden")
        try:
            result = await _executor(engine, tmp_path).execute_step(_dismiss_step())
        except StepExecutionError as e:  # pragma: no cover — the regression
            pytest.fail(f"if_visible failed the step on a page with no popup: {e}")
        assert result.status != StepStatus.FAILED

    @pytest.mark.asyncio
    async def test_the_gated_step_is_skipped_too(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """Both forms, because both read the same predicate.

        The flag form has its own branch in ``execute_step`` and would have
        gone wrong in its own way: not three dismiss attempts but one click,
        aimed at a nav link nobody can see.
        """
        await _open(engine, base_url, "hidden")
        result = await _executor(engine, tmp_path).execute_step(_gated_step())

        assert result.status == StepStatus.SKIPPED
        assert await _tally(engine) == 0


class TestAClippedAncestorIsStillHidden:
    """A hole ``0516fd9`` did not close, found by writing the file above.

    ``display: none`` and ``height: 0; overflow: hidden`` both hide text, and
    Playwright tells them apart: the first leaves the child no box, so
    ``is_visible`` is False and the fix catches it; the second leaves the child
    its own box inside a clipped parent, so ``is_visible`` is **True** and a
    box comes back at y = 194.5 -- measured, not reasoned. The predicate
    therefore says the popup is up, ``then`` runs, nothing can be dismissed,
    and the step fails after three attempts. That is the 2026-03-24 report
    again, through a different stylesheet.

    It matters because ``height: 0`` is how an animated accordion or dropdown
    is normally built -- arguably more common than ``display: none``, since it
    is the one that can transition.

    Marked ``xfail(strict=True)`` and not fixed here on purpose. Closing it
    means changing what "visible" means for every ``if_visible`` step in every
    user's scenarios, and the candidate check (is the element actually painted
    at its own centre?) also rejects anything below the fold -- a change of
    behaviour that is not this work item's to make. Strict, so that whoever
    does make it is told by a red test rather than by reading this paragraph.
    """

    @pytest.mark.asyncio
    async def test_playwright_calls_the_clipped_node_visible(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """Not xfail: this one passes today and is the measurement itself.

        It pins the browser behaviour the hole rests on, so that if a future
        Chromium starts reporting clipped nodes as hidden, the xfail below
        turns green for a real reason and says so.
        """
        await _open(engine, base_url, "collapsed")
        locator = engine.page.get_by_text(POPUP_TEXT, exact=False).first
        assert await locator.is_visible() is True
        assert await locator.bounding_box() is not None

    @pytest.mark.xfail(
        strict=True,
        reason="height:0/overflow:hidden still reads as visible; see the class docstring",
    )
    @pytest.mark.asyncio
    async def test_then_does_not_run(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        await _open(engine, base_url, "collapsed")
        # The step failing is part of the defect, not a separate one: the
        # block runs against a popup that is not there, finds nothing to
        # press, and takes the step down with it.
        with contextlib.suppress(StepExecutionError):
            await _executor(engine, tmp_path).execute_step(_dismiss_step())
        assert await _tally(engine) == 0
