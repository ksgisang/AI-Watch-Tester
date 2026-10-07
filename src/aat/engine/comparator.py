"""Comparator — ExpectedResult evaluation against engine state.

Checks assertions like text_visible, url_contains, screenshot_match
against the current state of the test engine.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING

import cv2
import numpy as np

from aat.core.exceptions import StepExecutionError
from aat.core.models import ActionType, AssertType, ExpectedResult, StepResult, StepStatus
from aat.engine.overlay import overlay_hidden
from aat.engine.sweep import sweep_viewports

if TYPE_CHECKING:
    from aat.core.models import Scenario, StepConfig
    from aat.engine.base import BaseEngine

logger = logging.getLogger(__name__)

# Tesseract's default (PSM 3, full auto) read the bottom of a Flutter login
# card and nothing else -- it missed both target phrases in all four
# image/language combinations measured. PSM 6 was the only mode that hit in
# every one of them, so it goes first; 4 and 11 each recover cases 6 misses.
_OCR_PSM_MODES = (6, 4, 11)

# How many screens down the ``text_visible`` OCR fallback looks. Lower than the
# sweep's own default because the cap here is set by Tesseract's price, not by
# how far pages scroll: each missing frame costs up to two image variants x two
# languages x three PSM modes, at roughly half a second each.
_OCR_SWEEP_SCREENS = 4

# Mirrors ``MatchingConfig.ocr_languages``. Duplicated as a literal rather than
# imported so that constructing a bare ``Comparator()`` -- which eight call
# sites still do -- reads Korean instead of silently running as English.
_DEFAULT_OCR_LANGUAGES = ("eng", "kor")


def _collapse_whitespace(value: str, case_insensitive: bool) -> str:
    """Strip every run of whitespace, for comparing OCR output to an expectation."""
    collapsed = "".join(value.split())
    return collapsed.lower() if case_insensitive else collapsed


class Comparator:
    """Compare expected results against actual engine state."""

    def __init__(self, ocr_languages: list[str] | None = None) -> None:
        """
        Args:
            ocr_languages: Tesseract languages for the ``text_visible`` OCR
                fallback. Pass ``config.matching.ocr_languages`` so a user who
                configured the setting actually gets it; the default is the
                same list the model declares, so callers that pass nothing are
                no worse off.
        """
        self._ocr_languages = list(ocr_languages or _DEFAULT_OCR_LANGUAGES)

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
                if found:
                    logger.info(
                        "text_visible %r satisfied by OCR, not the DOM (canvas-rendered text)",
                        expected.value,
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

    async def _ocr_text_check(
        self,
        engine: BaseEngine,
        text: str,
        case_insensitive: bool = False,
    ) -> bool:
        """Fallback: check text via OCR on screenshot (for Canvas/Flutter).

        Measured against a real Flutter CanvasKit login screen, this path had
        three faults, and fixing any two of them still read nothing:

        1. No ``lang``, so Tesseract ran as English and returned noise
           (``AIAO| YOAIL}R?``) for Korean. ``MatchingConfig.ocr_languages``
           already defaulted to ``eng + kor`` and ``OCRMatcher`` honoured it --
           this one path ignored the setting the user had configured.
        2. Tesseract's default page segmentation (PSM 3) skipped the whole
           centre of the card and found neither target phrase in any
           image/language combination measured. PSM 6/4/11 read it.
        3. Even once read, ``'학원 관리 시스템' in '학원관리시스템'`` is False.
           Tesseract inserts and drops spaces freely in CJK, so both sides are
           whitespace-collapsed before comparing.

        ``preprocess_for_ocr`` is tried too, but as a *second* image rather
        than a fix: on the same screenshot it rescued one phrase (hit at PSM
        4/6/11 instead of 6 alone) and cost the other (6 alone instead of
        4/6/11). It is a trade, not an improvement, so the cheap plain
        greyscale -- a quarter of the pixels, and half the OCR time measured
        -- goes first and the upscaled variant only runs if nothing matched.

        Looser whitespace is deliberate here and nowhere else: this runs only
        after the DOM check has already failed, so the alternative to a fuzzy
        match is no match at all.

        It reads this screen and then each screen further down. A canvas app's
        text is in the pixels and nowhere else, so text below the fold was
        invisible to this check and the assert failed about a page that was
        showing exactly what it was asked to show -- one scroll away.
        """
        try:
            # `type: ignore` has to come first: mypy does not see one that
            # follows another comment on the same line, and the import is only
            # here to find out whether the package is installed at all.
            import pytesseract  # type: ignore[import-untyped] # noqa: F401
        except ImportError:
            logger.debug("pytesseract not installed; skipping OCR fallback")
            return False

        needle = _collapse_whitespace(text, case_insensitive)
        if not needle:
            return False

        async def probe(frame: bytes) -> bool | None:
            # ``None`` means "not in this frame, keep going"; the sweep stops
            # on any non-None, so a False would end it after one screen.
            return self._frame_contains_text(frame, needle, case_insensitive) or None

        # The overlay stays hidden for the whole sweep rather than per capture.
        # The sweep takes its own screenshots and knows nothing about
        # ``#awt-overlay``, and a failing assert paints the expected text into
        # that bar verbatim -- so a single unhidden frame is enough to
        # manufacture a pass out of AWT's own complaint.
        async with self._overlay_hidden(engine):
            hit = await sweep_viewports(engine, probe, max_screens=_OCR_SWEEP_SCREENS)
        return hit is True

    def _frame_contains_text(
        self,
        screenshot: bytes | None,
        needle: str,
        case_insensitive: bool,
    ) -> bool:
        """Whether one captured frame reads as containing *needle*.

        Split out of :meth:`_ocr_text_check` so the sweep can hand it one
        frame at a time. ``needle`` arrives already whitespace-collapsed.
        """
        import pytesseract  # type: ignore[import-untyped,import-not-found]

        if not screenshot:
            return False
        img = cv2.imdecode(np.frombuffer(screenshot, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return False

        for variant in self._image_variants(img):
            for lang in self._ocr_language_candidates():
                for psm in _OCR_PSM_MODES:
                    try:
                        raw: str = pytesseract.image_to_string(
                            variant, lang=lang, config=f"--oem 3 --psm {psm}"
                        )
                    except Exception as e:
                        # A missing traineddata file fails identically for
                        # every PSM, so move on to the next language instead
                        # of paying for three identical failures.
                        logger.debug("OCR fallback failed for lang=%s: %s", lang, e)
                        break
                    if needle in _collapse_whitespace(raw, case_insensitive):
                        logger.debug("OCR fallback matched with lang=%s psm=%d", lang, psm)
                        return True
        return False

    @staticmethod
    def _image_variants(img: np.ndarray) -> Iterator[np.ndarray]:
        """Plain greyscale first, then the enhanced-and-upscaled version.

        Lazy on purpose: the second variant costs a 2x resize plus CLAHE and a
        convolution, and on a page where the first one matches, that work is
        never done.
        """
        yield cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        from aat.matchers.ocr import preprocess_for_ocr

        yield preprocess_for_ocr(img)

    def _ocr_language_candidates(self) -> list[str]:
        """Configured languages first, then plain English as a safety net.

        If the user has no ``kor.traineddata`` installed, asking for
        ``eng+kor`` raises and would otherwise lose the English reading this
        path used to manage. Falling back keeps the fix from being a
        regression for anyone with a bare Tesseract install.
        """
        joined = "+".join(self._ocr_languages)
        return [joined] if joined == "eng" else [joined, "eng"]

    @staticmethod
    @contextlib.asynccontextmanager
    async def _overlay_hidden(engine: BaseEngine) -> AsyncIterator[None]:
        """Hold AWT's own progress bar hidden for the duration of the block.

        ``aat run`` paints a ``#awt-overlay`` bar carrying the step
        description, and a failing assert repaints it with the message
        ``Text '<expected>' not visible on page``. OCR reading that bar would
        find the expected text in AWT's own complaint and report the
        assertion as passed -- a false pass manufactured by the tool.

        A context manager rather than a wrapper around one capture because the
        OCR check now sweeps: it takes several screenshots through code that
        knows nothing about the overlay, and one unhidden frame is enough.

        ``WebEngine.screenshot`` now hides the bar on its own, so this is the
        outer of two nested guards. It is kept rather than deleted because the
        sweep also scrolls and settles between captures, and because an engine
        that forgets to hide (a stub, a future engine) should not be able to
        reintroduce the false pass. Nesting is safe: the depth counter in
        ``engine/overlay.py`` is what makes the inner restore a no-op instead of
        putting back the ``none`` the outer guard had just written.
        """
        page = getattr(engine, "page", None)
        async with overlay_hidden(page):
            yield

    @classmethod
    async def _screenshot_without_overlay(cls, engine: BaseEngine) -> bytes | None:
        """One capture with the overlay hidden, for callers that want just one."""
        async with cls._overlay_hidden(engine):
            try:
                return await engine.screenshot()
            except Exception as e:
                logger.debug("Screenshot failed during OCR fallback: %s", e)
                return None

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
