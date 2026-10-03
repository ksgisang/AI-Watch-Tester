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
  * `assert_text` no longer passes on text the DOM holds but `display: none`
    hides, on either path. That was the one fix in AAT-115 a green suite can
    feel: a scenario asserting on a notice the code has since hidden now goes
    red, because it had been reporting that users could see something they
    could not. The controls next to it pin the other direction -- visible text
    still passes, including a visible copy standing behind a hidden one.
  * a scenario's `expected_result` is evaluated, after the last step and before
    teardown. It had been loaded, validated and read by nobody, which is this
    file's theme in its purest form. An entry written as prose is reported as
    a warning rather than checked, because the loader reshapes a sentence into
    a `text_visible` against that sentence and checking it would fail the
    product for the author's wording.
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
    Scenario,
    StepConfig,
    StepStatus,
    TargetSpec,
)
from aat.engine.comparator import Comparator, evaluate_scenario_expectations
from aat.engine.executor import StepExecutor
from aat.engine.humanizer import Humanizer
from aat.engine.waiter import Waiter
from aat.engine.web import WebEngine
from aat.matchers.hybrid import HybridMatcher
from aat.matchers.template import TemplateMatcher
from tests.fixtures.rendered_text_server import LEAKED, NOTICE, WORD, rendered_text_server


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


def _assert_text(expected: str, *, selector: str | None = None, step: int = 1) -> StepConfig:
    return StepConfig(
        step=step,
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
    """ "The DOM contains it" must not stand in for "a person can read it".

    Both paths through `assert_text` used to accept hidden text, for different
    reasons. The no-selector path counts `get_by_text` matches, and that
    locator matches hidden nodes. The selector path reads `inner_text`, which
    does respect `display: none` — on a *rendered* element; on a non-rendered
    one it falls back to `textContent` and hands back the hidden string.

    This is the one of AAT-115's three fixes that changes behaviour a green
    suite can feel: a scenario asserting on a notice the code has since hidden
    now goes red. That is the point — it was reporting that users could see
    something they could not.
    """

    @pytest.mark.asyncio
    async def test_text_a_person_cannot_read_should_not_satisfy_an_assertion(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        await engine.navigate(f"{base_url}/?render=clean")

        result = await _executor(engine, tmp_path).execute_step(_assert_text("삭제된 안내문"))

        assert result.status == StepStatus.FAILED

    @pytest.mark.asyncio
    async def test_the_selector_path_refuses_hidden_text_too(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """Naming the hidden element directly must not be a way around it."""
        await engine.navigate(f"{base_url}/?render=clean")

        result = await _executor(engine, tmp_path).execute_step(
            _assert_text("삭제된 안내문", selector="#hidden")
        )

        assert result.status == StepStatus.FAILED

    @pytest.mark.asyncio
    async def test_the_reason_given_is_hidden_not_missing(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """ "Not found on screen" would be true and useless.

        The reader has to be told the element exists, or they go looking for a
        rendering bug when the answer is a `display: none` they can grep for.
        """
        await engine.navigate(f"{base_url}/?render=clean")

        result = await _executor(engine, tmp_path).execute_step(
            _assert_text("삭제된 안내문", selector="#hidden")
        )

        assert "not visible" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_visible_text_still_passes_by_selector(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """The control. Without it the fix above could be "fail on everything"."""
        await engine.navigate(f"{base_url}/?render=clean")

        result = await _executor(engine, tmp_path).execute_step(
            _assert_text(WORD, selector="#question")
        )

        assert result.status == StepStatus.PASSED, result.error_message

    @pytest.mark.asyncio
    async def test_visible_text_still_passes_without_a_selector(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """The other control: narrowing `get_by_text` must not break the common case."""
        await engine.navigate(f"{base_url}/?render=clean")

        result = await _executor(engine, tmp_path).execute_step(_assert_text(WORD))

        assert result.status == StepStatus.PASSED, result.error_message

    @pytest.mark.asyncio
    async def test_a_visible_copy_behind_a_hidden_one_still_passes(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """The page is fine; only the first match in document order is hidden.

        A stale template that still holds last release's wording, plus the live
        view that holds this release's -- the same words, twice, unreadable copy
        first. Checking only the first `get_by_text` match would call this page
        broken, which is the opposite of the mistake the rest of this class
        guards against and just as wrong.
        """
        await engine.navigate(f"{base_url}/?render=clean")

        result = await _executor(engine, tmp_path).execute_step(_assert_text(NOTICE))

        assert result.status == StepStatus.PASSED, result.error_message

    @pytest.mark.asyncio
    async def test_a_failure_is_reported_against_the_step_that_failed(
        self, engine: WebEngine, base_url: str, tmp_path: Path
    ) -> None:
        """Derived repair: the OCR fallback raised with `step=0`.

        `StepExecutionError` builds its message from that number, so an
        assertion failing on step 7 announced itself as `Step 0 (assert_text)`
        — in the console, in `last_run.json` and in the PDF. The comparator's
        half of this was fixed in AAT-114; this is the engine's half.
        """
        await engine.navigate(f"{base_url}/?render=clean")

        result = await _executor(engine, tmp_path).execute_step(
            _assert_text("존재하지 않는 문구", step=7)
        )

        assert result.status == StepStatus.FAILED
        assert "Step 0" not in (result.error_message or "")


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


class TestScenarioLevelExpectedResult:
    """`expected_result` is checked now, and says so when it cannot be.

    The field was declared on :class:`~aat.core.models.Scenario`, coerced by a
    validator, shown in the shipped template and requested by three AI adapter
    prompts -- and read by no executor. Every assertion written there was
    discarded and the scenario reported success without the check having run:
    the unit's theme in its purest form, and worse than the substring problem,
    because a substring match at least checks something.

    The reason it stayed dead was the coercion: an entry like ``"User sees the
    welcome message"`` becomes a ``text_visible`` against that whole English
    sentence, so simply switching evaluation on would have failed every
    AI-generated scenario for its wording rather than for the product. The
    coercion now marks what it reshaped, and a reshaped entry is reported as a
    warning -- the check did not happen, which is the true answer. The third
    reading, passing it silently, is the defect this closes.
    """

    @staticmethod
    def _scenario(expected: list[object], *, steps: list[StepConfig] | None = None) -> Scenario:
        return Scenario(
            id="SC-001",
            name="scenario-level expectations",
            steps=steps
            or [
                StepConfig(
                    step=1,
                    action=ActionType.WAIT,
                    value="1",
                    description="stand still",
                )
            ],
            expected_result=expected,  # type: ignore[arg-type]
        )

    @pytest.mark.asyncio
    async def test_a_typed_expectation_is_checked_and_can_pass(
        self, engine: WebEngine, base_url: str
    ) -> None:
        await engine.navigate(f"{base_url}/?render=clean")
        scenario = self._scenario([{"type": "text_visible", "value": WORD}])

        results = await evaluate_scenario_expectations(scenario, engine)

        assert [r.status for r in results] == [StepStatus.PASSED]

    @pytest.mark.asyncio
    async def test_a_typed_expectation_that_is_wrong_fails(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """The whole point: a false claim in this field now turns the run red."""
        await engine.navigate(f"{base_url}/?render=clean")
        scenario = self._scenario([{"type": "text_visible", "value": "엉뚱한 글자"}])

        results = await evaluate_scenario_expectations(scenario, engine)

        assert results[0].status == StepStatus.FAILED
        assert "엉뚱한 글자" in (results[0].error_message or "")

    @pytest.mark.asyncio
    async def test_prose_is_warned_about_rather_than_checked(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """A sentence describes an outcome; it is not a value to look for.

        Failing it would fail the product for the author's wording, and
        passing it would be the original defect wearing a different hat.
        """
        await engine.navigate(f"{base_url}/?render=clean")
        scenario = self._scenario(["User sees the welcome message"])

        results = await evaluate_scenario_expectations(scenario, engine)

        assert results[0].status == StepStatus.WARNING
        assert "nothing was checked" in (results[0].error_message or "")

    @pytest.mark.asyncio
    async def test_a_scenario_that_stopped_early_skips_its_expectations(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """A critical failure leaves the browser somewhere nobody meant it to be.

        Judging an expectation against that page answers a question nobody
        asked, so it is reported as skipped -- the same answer the step loop
        gives the steps it never reached.
        """
        await engine.navigate(f"{base_url}/?render=clean")
        scenario = self._scenario([{"type": "text_visible", "value": WORD}])

        results = await evaluate_scenario_expectations(scenario, engine, skipped=True)

        assert results[0].status == StepStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_expectations_are_numbered_after_the_last_step(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """They share a report with the steps, so they must not restart at 1."""
        await engine.navigate(f"{base_url}/?render=clean")
        steps = [
            StepConfig(step=n, action=ActionType.WAIT, value="1", description=f"wait {n}")
            for n in (1, 2, 3)
        ]
        scenario = self._scenario(
            [{"type": "text_visible", "value": WORD}, {"type": "text_visible", "value": WORD}],
            steps=steps,
        )

        results = await evaluate_scenario_expectations(scenario, engine)

        assert [r.step for r in results] == [4, 5]
        assert all(r.action == ActionType.ASSERT for r in results)

    @pytest.mark.asyncio
    async def test_an_empty_field_produces_nothing(self, engine: WebEngine, base_url: str) -> None:
        """Most scenarios leave it empty; they must not gain a phantom step."""
        await engine.navigate(f"{base_url}/?render=clean")

        assert await evaluate_scenario_expectations(self._scenario([]), engine) == []

    def test_the_coercion_marks_what_it_reshaped(self) -> None:
        """Without this flag the evaluator cannot tell prose from an assertion.

        A string and ``{"type": "text_visible", "value": <same string>}`` arrive
        at the model as the same object otherwise, and the difference decides
        between warning and checking.
        """
        scenario = self._scenario(
            ["User sees the welcome message", {"type": "text_visible", "value": WORD}]
        )

        assert [e.from_prose for e in scenario.expected_result] == [True, False]

    def test_both_runners_call_the_evaluator(self) -> None:
        """The successor to the strict `xfail` that pinned "nothing reads this".

        Asserted by searching the source because the defect was an absence,
        and because the two call sites sit inside long async bodies that need
        a live browser and an approved run to reach -- the approval gate is
        not something a test may walk around. A grep cannot prove the call
        happens at the right moment, which the evaluator's own tests above
        cover; what it can prove is that neither runner quietly drops the
        field again, which is exactly how it died the first time.
        """
        src = Path(__file__).resolve().parents[2] / "src" / "aat"
        callers = {
            path.relative_to(src)
            for path in src.rglob("*.py")
            if "evaluate_scenario_expectations(" in path.read_text(encoding="utf-8")
        }

        assert Path("cli/commands/run_cmd.py") in callers, "aat run does not check expected_result"
        assert Path("core/loop.py") in callers, "aat loop does not check expected_result"
