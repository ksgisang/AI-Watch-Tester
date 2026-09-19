"""Tests for PDFReporter's HTML — the part that carries the content.

Printing is checked separately against a real browser in
tests/integration/test_pdf_report.py; everything here is about what the page
says, because that is what a person reads off the report.
"""

from __future__ import annotations

import base64
from pathlib import Path  # noqa: TC003

from aat.core.models import (
    ActionType,
    AnalysisResult,
    FileChange,
    FixResult,
    LoopIteration,
    LoopResult,
    Severity,
    StepResult,
    StepStatus,
    TestResult,
)
from aat.reporters import REPORTER_REGISTRY
from aat.reporters.pdf import PDFReporter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
    "IQAAAABJRU5ErkJggg=="
)


def _step(
    number: int,
    status: StepStatus,
    *,
    description: str = "Click the grade button",
    error: str | None = None,
    before: str | None = None,
    after: str | None = None,
) -> StepResult:
    return StepResult(
        step=number,
        action=ActionType.FIND_AND_CLICK,
        status=status,
        description=description,
        error_message=error,
        screenshot_before=before,
        screenshot_after=after,
        elapsed_ms=120.0,
    )


def _result(steps: list[StepResult], *, passed: bool = True) -> TestResult:
    failed = sum(1 for s in steps if s.status == StepStatus.FAILED)
    return TestResult(
        scenario_id="SC-001",
        scenario_name="Grade a question",
        passed=passed,
        steps=steps,
        total_steps=len(steps),
        passed_steps=sum(1 for s in steps if s.status == StepStatus.PASSED),
        failed_steps=failed,
        duration_ms=4200.0,
    )


def _screenshot(tmp_path: Path, name: str) -> str:
    path = tmp_path / name
    path.write_bytes(_PNG)
    return str(path)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_pdf_is_a_registered_format() -> None:
    """The format can be asked for by name, like markdown."""
    assert REPORTER_REGISTRY["pdf"] is PDFReporter
    assert PDFReporter().format_name == "pdf"


# ---------------------------------------------------------------------------
# What the page says
# ---------------------------------------------------------------------------


class TestStatusIsNotOverstated:
    """A warned run must not read as a clean pass anywhere on the page."""

    def test_clean_run_says_pass(self) -> None:
        html = PDFReporter().render_html(_result([_step(1, StepStatus.PASSED)]))
        assert ">PASS<" in html
        assert "WARNING" not in html

    def test_warned_run_does_not_say_pass_alone(self) -> None:
        """The banner is what a reader remembers, so it carries the warning."""
        steps = [
            _step(1, StepStatus.PASSED),
            _step(2, StepStatus.WARNING, error="click had no visible effect"),
        ]
        html = PDFReporter().render_html(_result(steps, passed=True))
        assert "PASS WITH WARNINGS" in html
        assert ">PASS<" not in html
        assert "changed nothing on screen" in html

    def test_failed_run_says_fail(self) -> None:
        steps = [_step(1, StepStatus.FAILED, error="element not found: 채점")]
        html = PDFReporter().render_html(_result(steps, passed=False))
        assert ">FAIL<" in html
        assert "element not found: 채점" in html

    def test_a_clean_run_carries_no_warning_note(self) -> None:
        html = PDFReporter().render_html(_result([_step(1, StepStatus.PASSED)]))
        assert "changed nothing on screen" not in html


class TestContent:
    """The report has to be readable on its own, away from the terminal."""

    def test_every_step_is_listed_with_its_status(self) -> None:
        steps = [
            _step(1, StepStatus.PASSED, description="Open the app"),
            _step(2, StepStatus.SKIPPED, description="Dismiss the banner"),
            _step(3, StepStatus.FAILED, description="Submit", error="timeout"),
        ]
        html = PDFReporter().render_html(_result(steps, passed=False))
        for text in ("Open the app", "Dismiss the banner", "Submit", "timeout"):
            assert text in html
        assert "SKIPPED" in html

    def test_markup_in_a_description_is_escaped(self) -> None:
        """Descriptions come out of a YAML file someone wrote by hand."""
        steps = [_step(1, StepStatus.PASSED, description="Click <b>me</b> & wait")]
        html = PDFReporter().render_html(_result(steps))
        assert "Click <b>me</b>" not in html
        assert "&lt;b&gt;me&lt;/b&gt;" in html
        assert "&amp; wait" in html

    def test_loop_report_carries_the_analysis_and_the_fix(self) -> None:
        iteration = LoopIteration(
            iteration=1,
            test_result=_result([_step(1, StepStatus.FAILED, error="timeout")], passed=False),
            analysis=AnalysisResult(
                cause="The button is rendered after the fetch resolves",
                suggestion="Wait for the network to settle",
                severity=Severity.CRITICAL,
                confidence=0.8,
            ),
            fix=FixResult(
                description="Await the fetch before rendering",
                files_changed=[
                    FileChange(
                        path="src/app/page.tsx",
                        original="render()",
                        modified="await fetchAll(); render()",
                    )
                ],
                confidence=0.75,
            ),
            branch_name="aat/fix-001",
            commit_hash="abc1234",
        )
        loop = LoopResult(
            success=False,
            total_iterations=1,
            iterations=[iteration],
            reason="max loops reached",
            duration_ms=9000.0,
        )
        html = PDFReporter().render_html(loop)
        assert "DevQA Loop Report" in html
        assert "Iteration 1" in html
        assert "The button is rendered after the fetch resolves" in html
        assert "src/app/page.tsx" in html
        assert "aat/fix-001" in html
        assert "abc1234" in html
        assert "max loops reached" in html


class TestScreenshots:
    """Screenshots travel inside the file, so the PDF can be sent on its own."""

    def test_failures_bring_their_screenshots(self, tmp_path: Path) -> None:
        steps = [
            _step(1, StepStatus.PASSED, after=_screenshot(tmp_path, "ok.png")),
            _step(
                2,
                StepStatus.FAILED,
                error="timeout",
                before=_screenshot(tmp_path, "bad_before.png"),
                after=_screenshot(tmp_path, "bad_after.png"),
            ),
        ]
        html = PDFReporter().render_html(_result(steps, passed=False))
        assert html.count("data:image/png;base64,") == 2
        assert "Step 2 · before" in html
        assert "Step 2 · after" in html
        assert "Step 1 ·" not in html

    def test_a_warned_step_brings_its_screenshots_too(self, tmp_path: Path) -> None:
        """Comparing before and after is how a missed click is recognised."""
        steps = [
            _step(
                1,
                StepStatus.WARNING,
                error="click had no visible effect",
                before=_screenshot(tmp_path, "w_before.png"),
                after=_screenshot(tmp_path, "w_after.png"),
            )
        ]
        html = PDFReporter().render_html(_result(steps))
        assert html.count("data:image/png;base64,") == 2

    def test_all_includes_passed_steps(self, tmp_path: Path) -> None:
        steps = [
            _step(1, StepStatus.PASSED, after=_screenshot(tmp_path, "one.png")),
            _step(2, StepStatus.PASSED, after=_screenshot(tmp_path, "two.png")),
        ]
        html = PDFReporter(screenshots="all").render_html(_result(steps))
        assert html.count("data:image/png;base64,") == 2

    def test_none_embeds_nothing(self, tmp_path: Path) -> None:
        steps = [_step(1, StepStatus.FAILED, after=_screenshot(tmp_path, "bad.png"))]
        html = PDFReporter(screenshots="none").render_html(_result(steps, passed=False))
        assert "data:image" not in html

    def test_a_missing_screenshot_does_not_cost_the_report(self, tmp_path: Path) -> None:
        """A file that was moved or never written leaves its slot out, no more."""
        steps = [
            _step(
                1,
                StepStatus.FAILED,
                error="timeout",
                before=str(tmp_path / "never_written.png"),
                after=_screenshot(tmp_path, "real.png"),
            )
        ]
        html = PDFReporter().render_html(_result(steps, passed=False))
        assert html.count("data:image/png;base64,") == 1
        assert "timeout" in html
