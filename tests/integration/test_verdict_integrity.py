"""A verdict has to come from the page, against a real browser.

SC-901 reported "22 of 24 steps passed" for a run in which the account was
never created. Three separate mechanisms produced that line, and all three are
exercised here because all three are invisible to a mock:

1. **AWT read its own progress bar back as page content.** The bar is painted on
   the page under test and carries the step description -- and, when an
   assertion fails, the expected words verbatim (``Text '승인 대기' not visible on
   page``). ``Comparator.check`` reads ``inner_text("body")``, so an assertion
   could be satisfied by text AWT had just written itself. Which also explains
   why the *same* assertion passed at step 21 and failed at step 24: the verdict
   depended on what the bar happened to be showing, not on the page.

2. **The pixels carried it too.** A shadow root stops the DOM routes; it does
   nothing for ``engine.screenshot()``, which feeds evidence images, the PDF,
   visual-regression baselines, the matcher chain and the OCR fallback.

3. **A typing failure scored as a pass.** ``find_and_type`` against a
   ``<select>`` clicked the element, opened the dropdown, typed into nothing,
   and reported PASSED because an element had been found.

The fixture server serves the two pages that make these answerable: a signup
form holding every shape a type target can be, and a plain page that does
**not** contain the phrase the scenario asserts -- so the assertion has exactly
one honest answer, and any pass is proof AWT answered from its own output.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from aat.cli.commands.run_cmd import _overlay_init, _overlay_update
from aat.core.exceptions import CriticalStepError, StepExecutionError
from aat.core.models import (
    ActionType,
    AssertType,
    EngineConfig,
    ExpectedResult,
    MatchMethod,
    MatchResult,
    StepConfig,
    StepStatus,
    TargetSpec,
)
from aat.engine.comparator import Comparator
from aat.engine.executor import StepExecutor
from aat.engine.humanizer import Humanizer
from aat.engine.waiter import Waiter
from aat.engine.web import WebEngine
from tests.fixtures.signup_form_server import (
    APPROVAL_NOTICE,
    SCHOOL_PLACEHOLDER,
    signup_form_server,
)


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    with signup_form_server() as url:
        yield url


@pytest.fixture()
async def engine() -> AsyncIterator[WebEngine]:
    """Real headless Chromium. Skips the test if the browser is not installed."""
    eng = WebEngine(EngineConfig(headless=True, speed="fast", screenshot_mode="off"))
    try:
        await eng.start()
    except Exception as e:  # noqa: BLE001 — environment without the browser binary
        pytest.skip(f"Chromium unavailable: {e}")
    try:
        yield eng
    finally:
        await eng.stop()


@pytest.fixture()
def executor(engine: WebEngine, tmp_path: Path) -> StepExecutor:
    # The matcher is stubbed to find nothing so every test here is answered by
    # the DOM route the defect lived on. A matcher that could succeed would let
    # a step pass for a reason this file is not measuring.
    matcher = AsyncMock()
    matcher.find = AsyncMock(
        return_value=MatchResult(
            found=False, x=0, y=0, confidence=0.0, method=MatchMethod.TEMPLATE
        )
    )
    return StepExecutor(engine, matcher, Humanizer(), Waiter(), Comparator(), tmp_path)


def _type_into(selector: str, text: str, *, critical: bool = False) -> StepConfig:
    return StepConfig(
        step=6,
        action=ActionType.FIND_AND_TYPE,
        target=TargetSpec(selector=selector),
        value=text,
        description=f"Fill {selector}",
        critical=critical,
        humanize=False,
    )


class TestTypingThatDidNotLand:
    """Defect 3: the action failed and the step said PASSED."""

    async def test_select_is_a_warning_not_a_pass(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """The reported defect, reproduced on the element that caused it."""
        await engine.navigate(f"{base_url}/signup")
        result = await executor.execute_step(_type_into("#school", "가락고등학교"))

        assert result.status == StepStatus.WARNING, result.error_message
        assert result.error_message is not None
        # The warning has to say what to do instead. "Something went wrong" on a
        # step that looks like it worked sends the reader back to the scenario.
        assert "<select>" in result.error_message
        assert "select_option" in result.error_message
        # And it quotes the value the field is actually showing, so the reader
        # can see for themselves that the text did not go in.
        assert SCHOOL_PLACEHOLDER in result.error_message

    async def test_an_ordinary_input_still_passes(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """The case that must not become yellow. Without this the rule is
        indistinguishable from warning on everything."""
        await engine.navigate(f"{base_url}/signup")
        result = await executor.execute_step(_type_into("#email", "user@test.com"))

        assert result.status == StepStatus.PASSED, result.error_message
        assert await engine.page.input_value("#email") == "user@test.com"

    async def test_readonly_is_a_warning(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        await engine.navigate(f"{base_url}/signup")
        result = await executor.execute_step(_type_into("#code", "ABC123"))

        assert result.status == StepStatus.WARNING, result.error_message
        assert result.error_message is not None
        assert "readonly" in result.error_message

    async def test_disabled_is_a_warning(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """Needs the selector fallback to be answerable at all.

        A disabled element cannot be focused, so ``document.activeElement`` is
        the ``<body>`` and the probe's primary question returns "nothing to
        measure". Only re-asking about the element the step named gets an
        answer.
        """
        await engine.navigate(f"{base_url}/signup")
        result = await executor.execute_step(_type_into("#referrer", "김대리"))

        assert result.status == StepStatus.WARNING, result.error_message
        assert result.error_message is not None
        assert "disabled" in result.error_message

    async def test_critical_typing_failure_stops_the_step(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """A step the author marked critical does not get to be a warning."""
        await engine.navigate(f"{base_url}/signup")
        with pytest.raises(CriticalStepError):
            await executor.execute_step(_type_into("#school", "가락고등학교", critical=True))


class TestOverlayIsNotPageContent:
    """Defects 1 and 2: the verdict came from AWT's own progress bar."""

    @staticmethod
    async def _bar_showing(engine: WebEngine, text: str) -> None:
        await _overlay_init(engine.page)
        await _overlay_update(engine.page, text)

    async def test_the_bar_is_painted_but_not_in_the_page_text(
        self, engine: WebEngine, base_url: str
    ) -> None:
        await engine.navigate(f"{base_url}/plain")
        await self._bar_showing(engine, f"Step 21: {APPROVAL_NOTICE} 확인")

        # It exists as an element -- otherwise this test would pass on a run
        # where the overlay simply failed to inject, which proves nothing.
        assert await engine.page.locator("#awt-overlay").count() == 1
        assert APPROVAL_NOTICE not in await engine.get_page_text()

    async def test_playwright_text_search_does_not_pierce_it(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """A closed root, not merely a root.

        Playwright's text engine pierces *open* shadow roots, so the find and
        assert routes that use ``get_by_text`` would still have reached the bar.
        """
        await engine.navigate(f"{base_url}/plain")
        await self._bar_showing(engine, f"Step 21: {APPROVAL_NOTICE} 확인")

        assert await engine.page.get_by_text(APPROVAL_NOTICE).count() == 0

    async def test_the_assertion_fails_as_it_should(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """The page does not say it, so the only honest verdict is a failure."""
        await engine.navigate(f"{base_url}/plain")
        await self._bar_showing(engine, f"Text '{APPROVAL_NOTICE}' not visible on page")

        with pytest.raises(StepExecutionError):
            await Comparator().check(
                ExpectedResult(type=AssertType.TEXT_VISIBLE, value=APPROVAL_NOTICE),
                engine,
            )

    async def test_the_verdict_does_not_depend_on_which_step_is_running(
        self, engine: WebEngine, base_url: str
    ) -> None:
        """Defect 1, stated directly.

        Step 21 and step 24 asserted the same phrase on the same page and got
        opposite verdicts. The only thing that differed between them was the
        text in the bar, so the test varies exactly that and nothing else.
        """
        expected = ExpectedResult(type=AssertType.TEXT_VISIBLE, value=APPROVAL_NOTICE)
        verdicts = []
        for label in (
            f"Step 21: {APPROVAL_NOTICE} 확인",
            f"Step 24: Text '{APPROVAL_NOTICE}' not visible on page",
        ):
            await engine.navigate(f"{base_url}/plain")
            await self._bar_showing(engine, label)
            try:
                await Comparator().check(expected, engine)
                verdicts.append("passed")
            except StepExecutionError:
                verdicts.append("failed")

        assert verdicts == ["failed", "failed"], verdicts

    async def test_captures_do_not_carry_the_bar(self, engine: WebEngine, base_url: str) -> None:
        """Pixels have no shadow boundary.

        Byte-identical to a capture taken before the bar existed is a stronger
        claim than "the bar is not in the DOM text": it is the one the OCR
        fallback, the matcher chain, the PDF and the visual baselines all
        depend on.
        """
        await engine.navigate(f"{base_url}/plain")
        clean = await engine.screenshot()

        await self._bar_showing(engine, f"Text '{APPROVAL_NOTICE}' not visible on page")
        assert await engine.screenshot() == clean

        # And the bar comes back afterwards -- a hide that never restores makes
        # the headful progress display useless from the first capture on.
        assert (
            await engine.page.evaluate(
                "() => getComputedStyle(document.getElementById('awt-overlay')).display"
            )
            != "none"
        )
