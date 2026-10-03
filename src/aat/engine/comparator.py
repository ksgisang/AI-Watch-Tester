"""Comparator — ExpectedResult evaluation against engine state.

Checks assertions like text_visible, url_contains, screenshot_match
against the current state of the test engine.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import cv2
import numpy as np

from aat.core.exceptions import StepExecutionError
from aat.core.models import ActionType, AssertType, ExpectedResult, StepResult, StepStatus

if TYPE_CHECKING:
    from aat.core.models import Scenario, StepConfig
    from aat.engine.base import BaseEngine


class Comparator:
    """Compare expected results against actual engine state."""

    async def check(
        self,
        expected: ExpectedResult,
        engine: BaseEngine,
        selector: str | None = None,
    ) -> None:
        """Verify an expected result. Raises StepExecutionError on failure.

        Args:
            expected: Expected result assertion.
            engine: BaseEngine instance for querying current state.
            selector: CSS selector to scope the assertion to, when the step
                named one. Only ``text_equals`` reads it -- see that branch for
                why, and why ``text_visible`` deliberately ignores it.
        """
        if expected.type == AssertType.TEXT_VISIBLE:
            # 1. Try DOM text first
            page_text = await engine.get_page_text()
            if expected.case_insensitive:
                found = expected.value.lower() in page_text.lower()
            else:
                found = expected.value in page_text

            # 2. Fallback: OCR on screenshot (Canvas/Flutter/WebGL)
            if not found and hasattr(engine, "screenshot"):
                found = await self._ocr_text_check(
                    engine, expected.value, expected.case_insensitive
                )

            if not found:
                raise StepExecutionError(
                    f"Text '{expected.value}' not visible on page",
                    step=0,
                    action="assert",
                )

        elif expected.type == AssertType.TEXT_EQUALS:
            # Scoped to the step's selector when it has one, and the whole page
            # otherwise. The unscoped form is kept for compatibility but it is
            # very nearly unusable: `get_page_text` returns `inner_text("body")`,
            # so it demands that the entire visible page equal the value. Three
            # AI adapter prompts offer `text_equals` as a valid assert type, so
            # scenarios do get generated with it -- and with no selector they
            # fail no matter what the page says.
            #
            # Scoping it is what makes the type do the job only it can do.
            # `assert_text` and `text_visible` are both substring matches, so
            # neither can catch "the expected text is present, surrounded by
            # junk" -- a template leaking its own markup around the right words
            # passes every one of them. An exact match against one element is
            # the check that fails there, which is why the selector lands here
            # and not on `text_visible`: substring-matching the whole page is
            # what `text_visible` is *for*, and narrowing it would turn passing
            # scenarios red.
            actual: str | None
            if selector is not None and hasattr(engine, "get_element_text"):
                actual = await engine.get_element_text(selector)  # type: ignore[attr-defined]
                if actual is None:
                    raise StepExecutionError(
                        f"No element matched selector {selector!r}",
                        step=0,
                        action="assert",
                    )
                where = f"selector {selector!r}"
            else:
                actual = await engine.get_page_text()
                where = "the whole page"

            stripped = actual.strip()
            if expected.case_insensitive:
                matched = expected.value.lower() == stripped.lower()
            else:
                matched = expected.value == stripped
            if not matched:
                # Naming what was compared against matters more here than
                # anywhere else: the old message was "Text does not match 'X'",
                # which reads as if the page lacked the text when the real
                # answer was usually that it had the text plus everything else.
                raise StepExecutionError(
                    f"Text in {where} does not equal {expected.value!r}: got {stripped[:200]!r}",
                    step=0,
                    action="assert",
                )

        elif expected.type == AssertType.URL_CONTAINS:
            # Retry with short polling to handle post-navigation race condition
            current_url = await self._wait_for_url(
                engine,
                expected.value,
                contains=True,
                case_insensitive=expected.case_insensitive,
            )
            check_val = expected.value.lower() if expected.case_insensitive else expected.value
            check_url = current_url.lower() if expected.case_insensitive else current_url
            if check_val not in check_url:
                raise StepExecutionError(
                    f"URL does not contain '{expected.value}'. Current: {current_url}",
                    step=0,
                    action="assert",
                )

        elif expected.type == AssertType.URL_NOT_CONTAINS:
            # Retry with short polling to handle post-navigation race condition
            current_url = await self._wait_for_url(
                engine,
                expected.value,
                contains=False,
                case_insensitive=expected.case_insensitive,
            )
            check_val = expected.value.lower() if expected.case_insensitive else expected.value
            check_url = current_url.lower() if expected.case_insensitive else current_url
            if check_val in check_url:
                raise StepExecutionError(
                    f"URL should not contain '{expected.value}'. Current: {current_url}",
                    step=0,
                    action="assert",
                )

        elif expected.type == AssertType.IMAGE_VISIBLE:
            # IMAGE_VISIBLE is handled at StepExecutor level via assert step.
            # Comparator passes through (no-op for now).
            pass

        elif expected.type == AssertType.SCREENSHOT_MATCH:
            screenshot = await engine.screenshot()
            similarity = self._compare_screenshots(screenshot, expected.value)
            threshold = 1.0 - expected.tolerance
            if similarity < threshold:
                raise StepExecutionError(
                    f"Screenshot similarity {similarity:.2%} below threshold {threshold:.2%}",
                    step=0,
                    action="assert",
                )

    async def _check_as_step(
        self,
        expected: ExpectedResult,
        engine: BaseEngine,
        selector: str | None,
        step_number: int,
    ) -> None:
        """Run :meth:`check` and label any failure with the real step number.

        Every ``raise`` in :meth:`check` passes ``step=0``, because ``check``
        takes an :class:`ExpectedResult` and has never been told which step it
        belongs to. ``StepExecutionError`` builds its message from that, so a
        failed assertion on step 7 reported itself as ``Step 0 (assert): ...``
        -- in the console, in ``last_run.json`` and in the PDF report. For a
        product whose stated job is leaving evidence behind, pointing the reader
        at a step that does not exist is the wrong kind of evidence.

        Re-raising here rather than threading a step number through all eight
        raise sites: ``raw_message`` exists for exactly this, and the assertion
        logic stays a function of the expectation and the page.
        """
        try:
            await self.check(expected, engine, selector)
        except StepExecutionError as e:
            raise StepExecutionError(e.raw_message, step=step_number, action=e.action) from e

    async def check_assert(self, step: StepConfig, engine: BaseEngine) -> None:
        """Assert action handler.

        Priority: step.assert_type (explicit) > expected[].type (implicit).
        When assert_type is set, it overrides the type in expected list items
        so that ``assert_type: url_contains`` is not silently ignored when
        expected[0].type defaults to text_visible.

        ``step.target.selector`` is passed through to :meth:`check`, which uses
        it to scope ``text_equals`` to one element.

        Args:
            step: StepConfig with assert info.
            engine: BaseEngine instance.
        """
        selector = step.target.selector if step.target else None

        # Format 1 (inline): assert_type + value — highest priority
        if step.assert_type is not None and step.value is not None:
            expected = ExpectedResult(type=step.assert_type, value=step.value)
            await self._check_as_step(expected, engine, selector, step.step)
            return

        # Format 2: expected list (override type if assert_type is set)
        if step.expected:
            for exp in step.expected:
                if step.assert_type is not None and exp.type != step.assert_type:
                    exp = ExpectedResult(
                        type=step.assert_type,
                        value=exp.value,
                        tolerance=exp.tolerance,
                        case_insensitive=exp.case_insensitive,
                    )
                await self._check_as_step(exp, engine, selector, step.step)
            return

        raise StepExecutionError(
            "Assert step requires 'expected' list or 'assert_type' + 'value'",
            step=step.step,
            action="assert",
        )

    @staticmethod
    async def _ocr_text_check(
        engine: BaseEngine,
        text: str,
        case_insensitive: bool = False,
    ) -> bool:
        """Fallback: check text via OCR on screenshot (for Canvas/Flutter)."""
        try:
            import pytesseract  # type: ignore[import-untyped]

            screenshot = await engine.screenshot()
            img_arr = np.frombuffer(screenshot, dtype=np.uint8)
            img = cv2.imdecode(img_arr, cv2.IMREAD_GRAYSCALE)
            if img is None:
                return False
            ocr_text: str = pytesseract.image_to_string(img)
            if case_insensitive:
                return text.lower() in ocr_text.lower()
            return text in ocr_text
        except Exception:
            return False

    @staticmethod
    async def _wait_for_url(
        engine: BaseEngine,
        value: str,
        *,
        contains: bool,
        case_insensitive: bool = False,
        timeout: float = 5.0,
        interval: float = 0.3,
    ) -> str:
        """Poll URL up to *timeout* seconds waiting for the condition to be met.

        This handles the race condition where a form submit triggers navigation
        but the URL hasn't changed yet when the assert step runs.

        Returns the last observed URL.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        last_url = ""
        while True:
            last_url = await engine.get_url()
            check_val = value.lower() if case_insensitive else value
            check_url = last_url.lower() if case_insensitive else last_url
            if contains and check_val in check_url:
                return last_url
            if not contains and check_val not in check_url:
                return last_url
            if asyncio.get_event_loop().time() >= deadline:
                return last_url
            await asyncio.sleep(interval)

    @staticmethod
    def _compare_screenshots(current: bytes, reference_path: str) -> float:
        """Compare current screenshot with reference using normalized correlation.

        Args:
            current: Current screenshot as PNG bytes.
            reference_path: Path to reference screenshot image.

        Returns:
            Similarity score between 0.0 and 1.0.
        """
        img1 = cv2.imdecode(
            np.frombuffer(current, np.uint8),
            cv2.IMREAD_GRAYSCALE,
        )
        img2 = cv2.imread(reference_path, cv2.IMREAD_GRAYSCALE)
        if img2 is None:
            raise StepExecutionError(
                f"Reference screenshot '{reference_path}' not found",
                step=0,
                action="assert",
            )
        if img1 is None:
            raise StepExecutionError(
                "Failed to decode current screenshot",
                step=0,
                action="assert",
            )
        # Resize reference to match current
        img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))
        result = cv2.matchTemplate(img1, img2, cv2.TM_CCORR_NORMED)
        return float(result[0][0])


# ─── Scenario-level expected_result ──────────────────────────


PROSE_WARNING = (
    "written as a sentence, not an assertion, so nothing was checked — "
    "give it a `type:` and a `value:`, or move it into an `assert` step"
)

_SKIPPED_REASON = "the scenario stopped early, so the expectations were never reached"


async def evaluate_scenario_expectations(
    scenario: Scenario,
    engine: BaseEngine,
    *,
    skipped: bool = False,
    comparator: Comparator | None = None,
) -> list[StepResult]:
    """Check a scenario's ``expected_result`` entries and report each one.

    The field is declared on the model, offered by the shipped template and
    requested by three AI adapter prompts, and until now no executor read it:
    every assertion written there was discarded and the scenario reported
    success without the check having run. This is the consumer.

    Each entry comes back as a :class:`StepResult` so it reaches the console,
    ``last_run.json`` and the report by the same road as a step -- an
    expectation that failed is evidence, and evidence that only exists in one
    of the three places is the kind of gap this field was.

    Numbered after the last real step rather than from 1, because the two
    share a report and a reader counting down the steps should not meet a
    "step 1" at the bottom.

    *skipped* is for a scenario that stopped early: a critical failure leaves
    the browser somewhere the author never meant it to be, and an expectation
    judged against that page answers a question nobody asked. The step loop
    already skips the rest of the steps in that case; this follows it.

    An entry whose ``from_prose`` flag is set is reported as a **warning**
    rather than checked. Passing it would be the original defect wearing a
    different hat -- a check that did not happen, reported green -- and
    failing it would fail the product for the author's wording.
    """
    if not scenario.expected_result:
        return []

    checker = comparator or Comparator()
    first_number = max((s.step for s in scenario.steps), default=0) + 1
    results: list[StepResult] = []

    for offset, expected in enumerate(scenario.expected_result):
        description = f"expected_result[{offset}]: {expected.type.value} {expected.value!r}"
        number = first_number + offset

        if skipped:
            results.append(
                StepResult(
                    step=number,
                    action=ActionType.ASSERT,
                    status=StepStatus.SKIPPED,
                    description=description,
                    error_message=_SKIPPED_REASON,
                )
            )
            continue

        if expected.from_prose:
            results.append(
                StepResult(
                    step=number,
                    action=ActionType.ASSERT,
                    status=StepStatus.WARNING,
                    description=description,
                    error_message=PROSE_WARNING,
                )
            )
            continue

        started = time.monotonic()
        status = StepStatus.PASSED
        error: str | None = None
        try:
            # No selector: a scenario-level expectation has no target to scope
            # to, so `text_equals` here compares the whole page. That is the
            # documented behaviour of the unscoped form, not an oversight.
            await checker.check(expected, engine)
        except StepExecutionError as e:
            status, error = StepStatus.FAILED, e.raw_message
        except Exception as e:  # noqa: BLE001 — an expectation must not kill the run
            status, error = StepStatus.ERROR, f"{type(e).__name__}: {e}"

        results.append(
            StepResult(
                step=number,
                action=ActionType.ASSERT,
                status=status,
                description=description,
                error_message=error,
                elapsed_ms=(time.monotonic() - started) * 1000,
            )
        )

    return results
