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

The third row is the 2026-03-24 report and the reason ``0516fd9`` works. The
fourth is a hole that fix did not close, found by writing this file: a child of
a collapsed container keeps a box of its own, so ``is_visible`` says yes and
the dismiss block runs against a popup nobody can see. It was pinned here as a
strict ``xfail`` for one working day and then closed by
:func:`aat.engine.dom_search.is_clipped_by_ancestor`.

Closing it meant teaching the check to *refuse* elements it used to accept,
which is the direction that fails silently -- a popup that really is up stops
being dismissed, and the scenario dies several steps later under another
name. So the last class here serves two pages where the popup is genuinely on
screen and shaped like a plausible implementation's blind spot: one below the
fold, one behind an inline ``overflow: hidden`` ancestor. Both must still run
``then``.

Four separate places decide this question, and a step reaches exactly one of
them depending on how it names its target -- selector, region, text, or text
with no box. Each has a class here, because a guard on a path no test walks
can be deleted without anything going red; two of them were added only after
a mutation sweep proved that. One class goes below the executor entirely and
calls the predicate directly, for the one choice the OCR fallback would
otherwise answer in its place.
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
    ScreenRegion,
    StepConfig,
    StepStatus,
    TargetSpec,
)
from aat.engine.comparator import Comparator
from aat.engine.dom_search import is_clipped_by_ancestor
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


def _dismiss_step_by_selector(selector: str) -> StepConfig:
    """The dismiss block, naming its target by selector instead of by text.

    A fourth place can answer "is it visible", and it is the first one tried:
    when the step carries a selector, the check resolves it and measures the
    box, never reaching the text search below. Every test above names its
    target by text, so this path was guarded and unexercised -- deletable
    without anything going red, which a mutation sweep duly demonstrated.
    """
    step = _dismiss_step()
    step.target = TargetSpec(selector=selector)
    return step


def _dismiss_step_in_region(region: ScreenRegion) -> StepConfig:
    """The dismiss block, scoped to part of the screen.

    A third place can answer "is it visible", reached only when the step names
    a region: instead of asking `is_visible`, it takes the bounding box and
    checks the centre point falls inside the region. It was written for the
    same reason the others were and inherited the same hole, so it needs its
    own pages -- a region step has never appeared in this file before, and a
    check that is never exercised is a check that can be deleted without
    anything going red.
    """
    step = _dismiss_step()
    step.region = region
    return step


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
    """The second route into the 2026-03-24 report, found by writing the file
    above and closed by :func:`aat.engine.dom_search.is_clipped_by_ancestor`.

    ``display: none`` and ``height: 0; overflow: hidden`` both hide text, and
    Playwright tells them apart: the first leaves the child no box, so
    ``is_visible`` is False and ``0516fd9`` caught it; the second leaves the
    child its own box inside a clipped parent, so ``is_visible`` is **True**
    and a box comes back at y = 194.5 -- measured, not reasoned. So the
    predicate used to say the popup was up, ``then`` ran, nothing could be
    dismissed, and the step failed after three attempts: the same report
    through a different stylesheet.

    It matters because ``height: 0`` is how an animated accordion or dropdown
    is normally built -- arguably more common than ``display: none``, since it
    is the one that can transition.

    The check asks whether an ancestor has collapsed, not whether a click at
    the element's centre would land on it. The second question is the obvious
    one and is wrong here: ``document.elementFromPoint`` only sees the
    viewport, so it would also reject everything below the fold and undo
    AAT-121. ``TestAVisibleElementIsStillVisible`` holds that line.
    """

    @pytest.mark.asyncio
    async def test_playwright_calls_the_clipped_node_visible(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """The measurement the repair rests on, kept as a test.

        It pins the browser behaviour that makes the extra check necessary. If
        a future Chromium starts reporting clipped nodes as hidden, this turns
        red and whoever sees it learns that the check below has become
        redundant -- rather than carrying it forever because a comment said so.
        """
        await _open(engine, base_url, "collapsed")
        locator = engine.page.get_by_text(POPUP_TEXT, exact=False).first
        assert await locator.is_visible() is True
        assert await locator.bounding_box() is not None

    @pytest.mark.asyncio
    async def test_then_does_not_run(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        await _open(engine, base_url, "collapsed")
        # The step failing was part of the defect, not a separate one: the
        # block ran against a popup that was not there, found nothing to
        # press, and took the step down with it. Suppressed rather than
        # asserted against, because the tally is the claim being made.
        with contextlib.suppress(StepExecutionError):
            await _executor(engine, tmp_path).execute_step(_dismiss_step())
        assert await _tally(engine) == 0, (
            "a node inside a zero-height clipped parent convinced if_visible "
            "the popup was up -- the 2026-03-24 report by its second route"
        )

    @pytest.mark.asyncio
    async def test_the_step_does_not_fail_trying_to_dismiss_nothing(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """The symptom, named separately from its cause -- as for ``hidden``.

        What a user saw was not "the branch ran"; it was a red step on a page
        that was fine.
        """
        await _open(engine, base_url, "collapsed")
        try:
            result = await _executor(engine, tmp_path).execute_step(_dismiss_step())
        except StepExecutionError as e:  # pragma: no cover — the regression
            pytest.fail(f"if_visible failed the step on a page with no popup: {e}")
        assert result.status != StepStatus.FAILED

    @pytest.mark.asyncio
    async def test_the_gated_step_is_skipped_too(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        await _open(engine, base_url, "collapsed")
        result = await _executor(engine, tmp_path).execute_step(_gated_step())

        assert result.status == StepStatus.SKIPPED
        assert await _tally(engine) == 0


class TestTheRegionPathAnswersTheSameWay:
    """Both branches again, through the third visibility check.

    A step that names a region never reaches `is_visible` at all: it measures
    the bounding box and asks whether the centre lands inside the region. Same
    question, separate code, and it was wrong in the same way. Both modes sit
    in the top half of a 720px viewport -- the popup at y = 160, the clipped
    nav at y = 194.5 -- so the region itself is not what separates them.
    """

    @pytest.mark.asyncio
    async def test_a_real_popup_in_the_region_still_runs_then(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        await _open(engine, base_url, "modal")
        result = await _executor(engine, tmp_path).execute_step(
            _dismiss_step_in_region(ScreenRegion.TOP)
        )

        assert result.status == StepStatus.PASSED
        assert await _tally(engine) == 1, "the region path stopped seeing a real popup"

    @pytest.mark.asyncio
    async def test_a_clipped_node_in_the_region_does_not(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        await _open(engine, base_url, "collapsed")
        with contextlib.suppress(StepExecutionError):
            await _executor(engine, tmp_path).execute_step(
                _dismiss_step_in_region(ScreenRegion.TOP)
            )

        assert await _tally(engine) == 0, (
            "the region path accepted a clipped node -- the box is inside the "
            "region, but nobody can see what is in it"
        )


class TestTheSelectorPathAnswersTheSameWay:
    """Both branches again, through the check that runs *first*.

    A step that names a selector is resolved and measured before the text
    search is ever reached, so none of the tests above touch this path. The
    selector here points straight at the clipped link -- the author has said
    exactly which node they mean, and the answer still has to be no, because
    naming an element is not the same as being able to see it.
    """

    @pytest.mark.asyncio
    async def test_a_real_popup_named_by_selector_still_runs_then(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        await _open(engine, base_url, "modal")
        result = await _executor(engine, tmp_path).execute_step(
            _dismiss_step_by_selector("#popup")
        )

        assert result.status == StepStatus.PASSED
        assert await _tally(engine) == 1, "the selector path stopped seeing a real popup"

    @pytest.mark.asyncio
    async def test_a_clipped_node_named_by_selector_does_not(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        await _open(engine, base_url, "collapsed")
        with contextlib.suppress(StepExecutionError):
            await _executor(engine, tmp_path).execute_step(
                _dismiss_step_by_selector("nav.clipped a")
            )

        assert await _tally(engine) == 0, (
            "the selector path accepted a clipped node -- it has a box and a "
            "width, and nobody can see it"
        )


class TestThePredicateByItself:
    """The one choice inside the predicate that the executor cannot pin.

    ``test_an_inline_clipping_ancestor_is_not_a_clipped_one`` below is the
    scenario-level claim, and it is not enough on its own: if the DOM path
    wrongly calls the inline text clipped, the OCR fallback at the end of
    ``_check_target_visible`` reads the same words off the screenshot -- they
    really are painted, at 26px -- and the step passes anyway. Measured: with
    the border box swapped for ``clientHeight``, the predicate answers
    ``True`` on the inline page and the executor still answers ``True``.

    So the border-box choice is pinned here, where it is made, with nothing
    downstream able to answer in its place.
    """

    @pytest.mark.asyncio
    async def test_a_collapsed_ancestor_is_clipped(self, engine: WebEngine, base_url: str) -> None:
        await _open(engine, base_url, "collapsed")
        locator = engine.page.get_by_text(POPUP_TEXT, exact=False).first
        assert await is_clipped_by_ancestor(locator) is True

    @pytest.mark.asyncio
    async def test_an_inline_clipping_ancestor_is_not(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """The border box, not ``clientHeight``.

        The two properties disagree on exactly this page -- 0 against 18px --
        and ``clientHeight`` is 0 for every non-replaced inline element, so an
        implementation reading it hides ordinary text inside any ``<span>``
        carrying ``overflow: hidden``.
        """
        await _open(engine, base_url, "inline")
        locator = engine.page.get_by_text(POPUP_TEXT, exact=False).first
        assert await is_clipped_by_ancestor(locator) is False

    @pytest.mark.asyncio
    async def test_an_ordinary_popup_is_not(self, engine: WebEngine, base_url: str) -> None:
        await _open(engine, base_url, "modal")
        locator = engine.page.get_by_text(POPUP_TEXT, exact=False).first
        assert await is_clipped_by_ancestor(locator) is False

    @pytest.mark.asyncio
    async def test_below_the_fold_is_not(self, engine: WebEngine, base_url: str) -> None:
        """Scroll position is not part of the question.

        The predicate asks whether an ancestor has collapsed, which is true or
        false regardless of where the page happens to be scrolled to.
        """
        await _open(engine, base_url, "belowfold")
        locator = engine.page.get_by_text(POPUP_TEXT, exact=False).first
        assert await is_clipped_by_ancestor(locator) is False


class TestAVisibleElementIsStillVisible:
    """The other direction, and the reason the check has the shape it does.

    A visibility check can fail in two ways, and only one of them announces
    itself. Accepting something hidden produces the noisy failure above, three
    dismiss attempts and a red step. Rejecting something visible produces
    silence: ``if_visible`` skips a popup that really is up, the scenario
    carries on into a page covered by a modal, and the failure surfaces several
    steps later wearing somebody else's name. So both pages here hold a popup
    that is genuinely on screen, each shaped like a plausible implementation's
    blind spot.
    """

    @pytest.mark.asyncio
    async def test_below_the_fold_still_counts(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """2,000px down and unscrolled. AAT-121's line, held.

        ``document.elementFromPoint`` at the element's centre is the direct way
        to ask "would a click land here", and it answers no for every element
        outside the viewport. An implementation built on it closes the clipped
        case and quietly reintroduces the defect AAT-121 spent a work item
        removing.
        """
        await _open(engine, base_url, "belowfold")
        assert await _tally(engine) == 0

        result = await _executor(engine, tmp_path).execute_step(_dismiss_step())

        assert result.status == StepStatus.PASSED
        assert await _tally(engine) == 1, (
            "a popup below the fold was treated as not on screen -- this is AAT-121 undone"
        )

    @pytest.mark.asyncio
    async def test_an_inline_clipping_ancestor_is_not_a_clipped_one(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """``clientHeight`` is 0 for every non-replaced inline element.

        Measured on this page: the clipping ``<span>`` reports ``clientHeight``
        0 and a border box 18px tall. The cheaper property would therefore
        hide ordinary text inside any inline element that happens to carry
        ``overflow: hidden``, which is a far larger blast radius than the
        defect being fixed.

        This is the scenario-level claim and not the thing that pins the
        choice: the step passes here even with the wrong property, because the
        OCR fallback reads the words off the screenshot. See
        ``TestThePredicateByItself``.
        """
        await _open(engine, base_url, "inline")
        result = await _executor(engine, tmp_path).execute_step(_dismiss_step())

        assert result.status == StepStatus.PASSED
        assert await _tally(engine) == 1, (
            "readable text inside an inline overflow:hidden ancestor was "
            "treated as clipped -- the clientHeight trap"
        )

    @pytest.mark.asyncio
    async def test_the_inline_ancestor_really_poses_the_question(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """The premise, asserted rather than assumed.

        Playwright's text engine matches the smallest element containing the
        text. Put the text directly inside the clipping span and the span
        *is* the match, so the ancestor walk starts above it and the page
        proves nothing -- which is exactly how the first version of this
        fixture passed under both candidate implementations. This pins the
        nesting that makes the question real.

        The width is asserted for the same reason and against a second way of
        losing it: the ``<b>`` shares ``#popup`` with every other mode, and
        that rule's ``position: fixed`` empties the span horizontally, turning
        this page into another ``collapsed``. Which is to say the span has to
        have *both* dimensions, or the only thing being measured is the hole
        again.
        """
        await _open(engine, base_url, "inline")
        locator = engine.page.get_by_text(POPUP_TEXT, exact=False).first
        shape = await locator.evaluate(
            "(el) => {"
            "  const p = el.parentElement;"
            "  const r = p.getBoundingClientRect();"
            "  return {tag: el.tagName, cls: p.className,"
            "          clientH: p.clientHeight,"
            "          rectH: r.height, rectW: r.width};"
            "}"
        )
        assert shape["tag"] == "B", "the match must be *inside* the clipping span"
        assert shape["cls"] == "inline-clip"
        assert shape["clientH"] == 0, "no clientHeight trap left to fall into"
        assert shape["rectH"] > 0, "the span must really be on screen"
        assert shape["rectW"] > 0, "the span is 0 wide -- this is `collapsed`, not `inline`"
