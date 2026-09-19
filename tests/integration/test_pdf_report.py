"""Printing a report, against the browser that does the printing.

The HTML is checked in tests/test_reporters/test_pdf.py. What is left to prove
is that Chromium turns it into a file that is actually a PDF, since that is the
whole reason the feature carries no PDF library of its own.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

import pytest

from aat.core.exceptions import ReporterError
from aat.core.models import ActionType, StepResult, StepStatus, TestResult
from aat.reporters.pdf import PDFReporter


def _result() -> TestResult:
    steps = [
        StepResult(
            step=1,
            action=ActionType.NAVIGATE,
            status=StepStatus.PASSED,
            description="Open the study app",
            elapsed_ms=800.0,
        ),
        StepResult(
            step=2,
            action=ActionType.FIND_AND_CLICK,
            status=StepStatus.WARNING,
            description="Click 채점",
            error_message="click had no visible effect (0.0% change)",
            elapsed_ms=1900.0,
        ),
    ]
    return TestResult(
        scenario_id="SC-001",
        scenario_name="Grade a question",
        passed=True,
        steps=steps,
        total_steps=2,
        passed_steps=1,
        failed_steps=0,
        duration_ms=2700.0,
    )


async def test_generate_writes_a_real_pdf(tmp_path: Path) -> None:
    """The returned path is a PDF, and the HTML it came from stays put."""
    written = await PDFReporter().generate(_result(), tmp_path)

    assert written == tmp_path / "report.pdf"
    assert written.read_bytes().startswith(b"%PDF-")
    assert written.stat().st_size > 1000

    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    assert "PASS WITH WARNINGS" in html
    assert "Click 채점" in html


async def test_a_directory_that_does_not_exist_yet_is_created(tmp_path: Path) -> None:
    written = await PDFReporter().generate(_result(), tmp_path / "reports" / "SC-001")
    assert written.exists()


async def test_an_unreadable_output_directory_is_reported_as_such(tmp_path: Path) -> None:
    """A report that cannot be written says so instead of failing silently."""
    blocker = tmp_path / "reports"
    blocker.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ReporterError) as excinfo:
        await PDFReporter().generate(_result(), blocker)

    assert "report" in str(excinfo.value).lower()
