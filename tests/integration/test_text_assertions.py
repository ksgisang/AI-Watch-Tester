"""What AWT's text assertions can and cannot prove, against a real browser.

§9-2: a page rendered its LaTeX source instead of the formula, so where the
reader should have seen `질량` it said `\\(\\text{질량}\\)`. The suite stayed
green, and it stayed green *correctly* -- every text assertion AWT offered was
a substring match, and `질량` is a substring of the junk. Nothing was broken;
the available checks simply could not express the question.

That is the failure mode this file exists to hold still. "It passed" and "it was
checked" are different claims, and the only way to keep them apart is to write
down, executably, what each assertion is blind to. A mock page could not do it:
these are questions about what Chromium reports for real markup, and a mock
answers whatever the test asked it to.

Pinned here:
  * `assert_text` is a substring match on both of its paths (with a selector,
    and without), and is case-insensitive on both. So the leak passes.
  * `text_visible` is the same, which is what it is *for* -- "is this word
    anywhere on the page" is a legitimate question and narrowing it would turn
    passing scenarios red.
  * `text_equals` scoped to a selector is the check that catches the leak, and
    it is new: unscoped, it compares against `inner_text("body")`, so it demands
    the whole visible page equal the value and essentially never passes.
  * `assert_text` passes on text the DOM holds but `display: none` hides. That
    is a real defect and is left as a strict xfail, not a fix, because fixing
    it turns currently-passing scenarios red -- 대표님's call, not this file's.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from aat.core.models import (
    ActionType,
    AssertType,
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
from tests.fixtures.rendered_text_server import LEAKED, WORD, rendered_text_server


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    """Local page that renders `질량` cleanly, as LaTeX junk, or not at all."""
    with rendered_text_server() as url:
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
    )


def _assert_text(expected: str, *, selector: str | None = None) -> StepConfig:
    return StepConfig(
        step=1,
        action=ActionType.ASSERT_TEXT,
        description=f"check for {expected!r}",
        target=TargetSpec(text=expected, selector=selector),
    )


def _assert_type(kind: AssertType, expected: str, *, selector: str | None = None) -> StepConfig:
    return StepConfig(
        step=1,
        action=ActionType.ASSERT,
        description=f"{kind.value} {expected!r}",
        assert_type=kind,
        value=expected,
        target=TargetSpec(selector=selector) if selector else None,
    )


class TestAssertTextIsASubstringMatch:
    """Pinned as the limit it is, not asserted as desirable behaviour.

    Both branches of the `assert_text` handler are substring matches, and a
    reader of the scenario file has no way to tell: `질량` next to a page that
    says `\\(\\text{질량}\\)` looks like a check that holds.
    """

    @pytest.mark.asyncio
    async def test_the_latex_leak_passes_with_a_selector(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """§9-2 itself, reproduced in Chromium.

        This is the whole bug: the page is wrong, the assertion is pointed
        straight at the wrong element, and the step passes.
        """
        await engine.navigate(f"{base_url}/?render=latex")

        result = await _executor(engine, tmp_path).execute_step(
            _assert_text(WORD, selector="#question")
        )

        assert result.status == StepStatus.PASSED
        assert await engine.get_element_text("#question") == LEAKED

    @pytest.mark.asyncio
    async def test_the_latex_leak_passes_without_a_selector_too(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """The no-selector path goes through `get_by_text(exact=False)`.

        Worth a separate test because it is a different code path with the same
        blind spot, and it is the path a generated scenario usually takes.
        """
        await engine.navigate(f"{base_url}/?render=latex")

        result = await _executor(engine, tmp_path).execute_step(_assert_text(WORD))

        assert result.status == StepStatus.PASSED

    @pytest.mark.asyncio
    async def test_it_ignores_case(self, engine: WebEngine, base_url: str, tmp_path: Path) -> None:
        """Also undocumented in the scenario, and also sometimes wrong.

        A page that shows `CANCEL` satisfies a scenario asking for `Cancel`,
        which matters when the casing *is* the thing under review.
        """
        await engine.navigate(f"{base_url}/?render=clean")

        result = await _executor(engine, tmp_path).execute_step(_assert_text("문", selector="h1"))

        assert result.status == StepStatus.PASSED

    @pytest.mark.asyncio
    async def test_absent_text_still_fails(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """The true negative, without which none of the above means anything.

        A substring match that passes on everything would satisfy every test
        above while checking nothing.
        """
        await engine.navigate(f"{base_url}/?render=clean")

        result = await _executor(engine, tmp_path).execute_step(
            _assert_text("존재하지않는문구", selector="#question")
        )

        assert result.status == StepStatus.FAILED

    @pytest.mark.asyncio
    async def test_an_empty_element_fails(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """A page that rendered nothing must not read as a page that rendered.

        The sibling of the leak: the same template bug sometimes produces junk
        and sometimes produces nothing, and only one of those is caught by a
        substring match.
        """
        await engine.navigate(f"{base_url}/?render=empty")

        result = await _executor(engine, tmp_path).execute_step(
            _assert_text(WORD, selector="#question")
        )

        assert result.status == StepStatus.FAILED


class TestTextEqualsScopedToASelector:
    """The check that catches §9-2, and the reason it did not exist before.

    `text_equals` was always in the schema and three AI adapter prompts offer it
    as a valid assert type, so scenarios were generated with it. It compared the
    value against `get_page_text()`, which is `inner_text("body")` — the entire
    visible page. That can essentially never be equal to anything a person would
    write, so the type was advertised and unusable at the same time.

    Scoping it to `step.target.selector` is non-breaking precisely because of
    that: selector-plus-`text_equals` failed unconditionally before, so no
    passing scenario can change meaning.
    """

    @pytest.mark.asyncio
    async def test_it_catches_the_leak(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """The point of the whole exercise.

        Same page, same element, same expected word as the first test in this
        file — and this time the junk is caught.
        """
        await engine.navigate(f"{base_url}/?render=latex")

        result = await _executor(engine, tmp_path).execute_step(
            _assert_type(AssertType.TEXT_EQUALS, WORD, selector="#question")
        )

        assert result.status == StepStatus.FAILED
        # `repr` because the message quotes what it found, which is the only
        # way a reader of the report learns that the words were there and the
        # markup was there too. A bare "does not equal" would send them hunting.
        assert repr(LEAKED) in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_it_passes_on_the_clean_render(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """Otherwise it would be an assertion that fails on everything."""
        await engine.navigate(f"{base_url}/?render=clean")

        result = await _executor(engine, tmp_path).execute_step(
            _assert_type(AssertType.TEXT_EQUALS, WORD, selector="#question")
        )

        assert result.status == StepStatus.PASSED

    @pytest.mark.asyncio
    async def test_a_missing_element_says_so(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """A stale selector and wrong text are different diagnoses.

        Reporting "text does not equal" for an element that is not there sends
        the reader to look at the rendering when the scenario is what is out of
        date.
        """
        await engine.navigate(f"{base_url}/?render=clean")

        result = await _executor(engine, tmp_path).execute_step(
            _assert_type(AssertType.TEXT_EQUALS, WORD, selector="#no-such-thing")
        )

        assert result.status == StepStatus.FAILED
        assert "#no-such-thing" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_unscoped_it_still_compares_the_whole_page(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """Pinned so the compatibility claim above is a measurement.

        If this ever starts passing, the change was not non-breaking after all.
        """
        await engine.navigate(f"{base_url}/?render=clean")

        result = await _executor(engine, tmp_path).execute_step(
            _assert_type(AssertType.TEXT_EQUALS, WORD)
        )

        assert result.status == StepStatus.FAILED
        assert "whole page" in (result.error_message or ""), (
            "the message must admit what it compared"
        )

    @pytest.mark.asyncio
    async def test_unscoped_it_can_pass_when_the_page_is_only_that_text(
        self, engine: WebEngine, tmp_path: Path
    ) -> None:
        """Shown to be fair to the old behaviour: it was not dead, just useless.

        `about:blank` has no visible text, so an empty expectation matches. No
        real page is ever in this state, which is the point.
        """
        await engine.navigate("about:blank")

        result = await _executor(engine, tmp_path).execute_step(
            _assert_type(AssertType.TEXT_EQUALS, "")
        )

        assert result.status == StepStatus.PASSED


class TestTextVisibleStaysASubstringMatch:
    """Deliberately not narrowed, and worth saying why in a test.

    `text_visible` answers "is this word anywhere on the page", and scenarios
    rely on that. Pointing the selector at it would have been the obvious
    symmetric change and it would have turned passing scenarios red, so the
    selector goes to `text_equals` instead and this records the decision.
    """

    @pytest.mark.asyncio
    async def test_a_selector_does_not_narrow_it(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        await engine.navigate(f"{base_url}/?render=clean")

        result = await _executor(engine, tmp_path).execute_step(
            _assert_type(AssertType.TEXT_VISIBLE, WORD, selector="h1")
        )

        assert result.status == StepStatus.PASSED, "found elsewhere on the page, as intended"

    @pytest.mark.asyncio
    async def test_it_also_passes_on_the_leak(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """So `text_visible` is not the fix for §9-2 and must not be sold as one."""
        await engine.navigate(f"{base_url}/?render=latex")

        result = await _executor(engine, tmp_path).execute_step(
            _assert_type(AssertType.TEXT_VISIBLE, WORD)
        )

        assert result.status == StepStatus.PASSED


class TestHiddenText:
    """A strict xfail, following the host-scoping precedent.

    `assert_text` reads `inner_text`, and Playwright's `inner_text` does respect
    `display: none` — but the no-selector path uses `get_by_text`, which matches
    hidden nodes, and the OCR fallback is only reached when the DOM path finds
    nothing. So "the DOM contains it" can stand in for "a person can read it".

    Not fixed here: a scenario asserting on text that is present but hidden
    passes today, and making it fail turns currently-green suites red. That is
    a behaviour change and 대표님's decision. Marked `strict=True` so that
    whoever fixes it is told to come back and remove the marker — a comment
    would not have said anything at all.
    """

    @pytest.mark.xfail(
        strict=True,
        reason="assert_text passes on display:none text; fixing it is a behaviour change",
    )
    @pytest.mark.asyncio
    async def test_text_a_person_cannot_read_should_not_satisfy_an_assertion(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        await engine.navigate(f"{base_url}/?render=clean")

        result = await _executor(engine, tmp_path).execute_step(_assert_text("삭제된 안내문"))

        assert result.status == StepStatus.FAILED


class TestGetElementText:
    """The new engine capability, on its own.

    `None` for "no element" has to be distinguishable from `""` for "an element
    that rendered nothing", because the comparator turns them into different
    diagnoses and those are the two failures a template bug produces.
    """

    @pytest.mark.asyncio
    async def test_it_returns_the_elements_text(self, engine: WebEngine, base_url: str) -> None:
        await engine.navigate(f"{base_url}/?render=clean")

        assert await engine.get_element_text("#question") == WORD

    @pytest.mark.asyncio
    async def test_a_missing_element_is_none(self, engine: WebEngine, base_url: str) -> None:
        await engine.navigate(f"{base_url}/?render=clean")

        assert await engine.get_element_text("#no-such-thing") is None

    @pytest.mark.asyncio
    async def test_an_empty_element_is_not_none(self, engine: WebEngine, base_url: str) -> None:
        await engine.navigate(f"{base_url}/?render=empty")

        assert await engine.get_element_text("#question") == ""

    @pytest.mark.asyncio
    async def test_it_does_not_raise_on_an_invalid_selector(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """A malformed selector is a scenario mistake, and it must be reported.

        Playwright raises here rather than returning zero matches, so the
        comparator must let the error surface instead of turning it into a
        silent `None` that reads as "the element is gone".
        """
        await engine.navigate(f"{base_url}/?render=clean")

        with pytest.raises(Exception, match="(?i)selector"):
            await engine.get_element_text("#[[[broken")


class TestNoSelectorStillWorks:
    """Regression guard for the wiring, not for the comparison.

    `check_assert` now reads `step.target.selector`, and `target` is optional.
    A step with no target at all is the common shape for `assert_url`, so the
    attribute access has to tolerate it.
    """

    @pytest.mark.asyncio
    async def test_a_step_with_no_target_does_not_crash(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        await engine.navigate(f"{base_url}/?render=clean")

        result = await _executor(engine, tmp_path).execute_step(
            _assert_type(AssertType.TEXT_VISIBLE, WORD)
        )

        assert result.status == StepStatus.PASSED

    @pytest.mark.asyncio
    async def test_url_assertions_are_unaffected(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """The selector is passed to every branch, so check one that ignores it."""
        await engine.navigate(f"{base_url}/?render=clean")

        result = await _executor(engine, tmp_path).execute_step(
            _assert_type(AssertType.URL_CONTAINS, "render=clean", selector="#question")
        )

        assert result.status == StepStatus.PASSED


@pytest.mark.asyncio
async def test_the_leak_is_substring_identical(engine: WebEngine, base_url: str) -> None:
    """The premise of the fixture, measured rather than assumed.

    If the junk did not contain the word, every "this passes" test above would
    be passing for the wrong reason and the file would prove nothing.
    """
    await engine.navigate(f"{base_url}/?render=latex")

    rendered = await engine.get_element_text("#question")

    assert rendered is not None
    assert WORD in rendered
    assert rendered != WORD


class TestTheReportNamesTheRightStep:
    """A failure that cites step 0 sends the reader to a step that does not exist.

    `Comparator.check` raises with `step=0` at all eight of its raise sites,
    because it is handed an `ExpectedResult` and never told which step it came
    from. `StepExecutionError` builds its message from that number, so the
    console line, `last_run.json` and the PDF report all said `Step 0 (assert)`
    for an assertion on step 7. For a product whose stated job is leaving
    evidence behind, that is the wrong kind of evidence.
    """

    @pytest.mark.asyncio
    async def test_a_failed_assertion_cites_its_own_step_number(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        await engine.navigate(f"{base_url}/?render=latex")
        step = _assert_type(AssertType.TEXT_EQUALS, WORD, selector="#question")
        step = step.model_copy(update={"step": 7})

        result = await _executor(engine, tmp_path).execute_step(step)

        assert result.status == StepStatus.FAILED
        assert "Step 7" in (result.error_message or "")
        assert "Step 0" not in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_the_reason_survives_the_relabelling(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """Renumbering must not cost the diagnosis — §9-4's rule, applied here."""
        await engine.navigate(f"{base_url}/?render=latex")
        step = _assert_type(AssertType.TEXT_EQUALS, WORD, selector="#question")

        result = await _executor(engine, tmp_path).execute_step(
            step.model_copy(update={"step": 7})
        )

        assert repr(LEAKED) in (result.error_message or "")
        assert "#question" in (result.error_message or "")


class TestScenarioLevelExpectedResultIsDead:
    """`expected_result` is loaded, validated, and then read by nobody.

    The field is declared on :class:`~aat.core.models.Scenario`, has a
    validator that coerces free-text items into ``text_visible``, is shown in
    the shipped ``scenario-template.yaml``, and three AI adapter prompts
    instruct the model to fill it. No executor ever evaluates it, so every
    assertion written there is discarded and the scenario reports success
    without the check having run. That is the unit's theme in its purest form
    and worse than the substring problem: a substring match at least checks
    something.

    Not switched on here, because switching it on fails scenarios that pass
    today. The coercion turns an item like ``"User sees welcome message"`` into
    a ``text_visible`` assertion against that whole English sentence, and
    AI-generated scenarios are full of exactly that prose -- so the field would
    have to be cleaned out of existing files first. A behaviour change of that
    size is 대표님's call, so it is pinned the way the host-scoping gap is:
    `strict=True`, which tells whoever implements it to come back and delete
    the marker.

    Documented meanwhile on the two surfaces that promised otherwise:
    `references/scenario-schema.md` said "checked after the last step" and now
    says it is ignored, and the template now says not to use it.
    """

    @pytest.mark.xfail(
        strict=True,
        reason="Scenario.expected_result is never evaluated; wiring it up is a behaviour change",
    )
    def test_something_in_the_product_reads_the_field(self) -> None:
        """Asserted by searching the source, because the defect *is* the absence.

        There is no evaluator to call and no runner to drive -- `run_cmd` loops
        over steps inline -- so the only executable form of "nothing reads
        this" is that nothing mentions it. Declaration and generation sites are
        excluded: the model has to declare the field, and the adapters only
        ask an AI to produce it. What is missing is a consumer.
        """
        src = Path(__file__).resolve().parents[2] / "src" / "aat"
        writers = {src / "core" / "models.py"}
        writers |= set((src / "adapters").glob("*.py"))

        readers = [
            path.relative_to(src)
            for path in src.rglob("*.py")
            if path not in writers and "expected_result" in path.read_text(encoding="utf-8")
        ]

        assert readers, "no module outside models.py and adapters/ reads expected_result"
