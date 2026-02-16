"""Tests for MarkdownReporter."""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003

import pytest

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
from aat.reporters.markdown import MarkdownReporter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_test_result(passed: bool = True) -> TestResult:
    steps = [
        StepResult(
            step=1,
            action=ActionType.NAVIGATE,
            status=StepStatus.PASSED,
            description="Navigate to page",
            elapsed_ms=150.0,
        ),
        StepResult(
            step=2,
            action=ActionType.FIND_AND_CLICK,
            status=StepStatus.PASSED if passed else StepStatus.FAILED,
            description="Click button",
            error_message=None if passed else "Element not found",
            elapsed_ms=300.0,
        ),
    ]
    return TestResult(
        scenario_id="SC-001",
        scenario_name="Login test",
        passed=passed,
        steps=steps,
        total_steps=2,
        passed_steps=2 if passed else 1,
        failed_steps=0 if passed else 1,
        duration_ms=450.0,
    )


def _make_loop_result(success: bool = True) -> LoopResult:
    tr1 = _make_test_result(passed=False)
    tr2 = _make_test_result(passed=True)

    iterations = [
        LoopIteration(
            iteration=1,
            test_result=tr1,
            analysis=AnalysisResult(
                cause="Button not found",
                suggestion="Update selector",
                severity=Severity.CRITICAL,
                related_files=["src/app.py"],
            ),
            fix=FixResult(
                description="Updated selector",
                files_changed=[
                    FileChange(
                        path="src/app.py",
                        original="old",
                        modified="new",
                        description="Fixed",
                    )
                ],
                confidence=0.9,
            ),
            approved=True,
        ),
        LoopIteration(
            iteration=2,
            test_result=tr2,
        ),
    ]

    return LoopResult(
        success=success,
        total_iterations=2,
        iterations=iterations,
        reason=None if success else "max loops exceeded",
        duration_ms=5000.0,
    )


@pytest.fixture
def reporter() -> MarkdownReporter:
    return MarkdownReporter()


# ---------------------------------------------------------------------------
# Tests: format_name
# ---------------------------------------------------------------------------


def test_format_name(reporter: MarkdownReporter) -> None:
    """format_name returns 'markdown'."""
    assert reporter.format_name == "markdown"


# ---------------------------------------------------------------------------
# Tests: generate with TestResult
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_test_result(reporter: MarkdownReporter, tmp_path: Path) -> None:
    """generate creates report.md and summary.json for TestResult."""
    result = _make_test_result(passed=True)
    report_path = await reporter.generate(result, tmp_path)

    assert report_path == tmp_path / "report.md"
    assert report_path.exists()
    assert (tmp_path / "summary.json").exists()

    # Check markdown content
    content = report_path.read_text()
    assert "# Test Report:" in content
    assert "SC-001" in content
    assert "Login test" in content
    assert "PASS" in content
    assert "navigate" in content

    # Check summary JSON
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["passed"] is True
    assert summary["total_steps"] == 2
    assert summary["passed_steps"] == 2
    assert summary["failed_steps"] == 0


@pytest.mark.asyncio
async def test_generate_failed_test_result(reporter: MarkdownReporter, tmp_path: Path) -> None:
    """generate includes error messages for failed steps."""
    result = _make_test_result(passed=False)
    report_path = await reporter.generate(result, tmp_path)

    content = report_path.read_text()
    assert "FAIL" in content
    assert "Element not found" in content

    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["passed"] is False
    assert summary["failed_steps"] == 1


# ---------------------------------------------------------------------------
# Tests: generate with LoopResult
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_loop_result(reporter: MarkdownReporter, tmp_path: Path) -> None:
    """generate creates report.md and summary.json for LoopResult."""
    result = _make_loop_result(success=True)
    report_path = await reporter.generate(result, tmp_path)

    assert report_path.exists()

    content = report_path.read_text()
    assert "# DevQA Loop Report" in content
    assert "SUCCESS" in content
    assert "Iteration 1" in content
    assert "Iteration 2" in content
    assert "Button not found" in content
    assert "Updated selector" in content
    assert "90%" in content  # confidence

    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["success"] is True
    assert summary["total_iterations"] == 2


@pytest.mark.asyncio
async def test_generate_creates_output_dir(reporter: MarkdownReporter, tmp_path: Path) -> None:
    """generate creates output_dir if it doesn't exist."""
    out = tmp_path / "nested" / "dir"
    result = _make_test_result()
    report_path = await reporter.generate(result, out)

    assert report_path.exists()
    assert out.exists()


@pytest.mark.asyncio
async def test_summary_json_is_valid(reporter: MarkdownReporter, tmp_path: Path) -> None:
    """summary.json is valid JSON with expected keys."""
    result = _make_test_result()
    await reporter.generate(result, tmp_path)

    summary_path = tmp_path / "summary.json"
    data = json.loads(summary_path.read_text())
    assert "passed" in data
    assert "total_steps" in data
    assert "duration_ms" in data


# ---------------------------------------------------------------------------
# Tests: registry
# ---------------------------------------------------------------------------


def test_reporter_registry() -> None:
    """MarkdownReporter is registered in REPORTER_REGISTRY."""
    from aat.reporters import REPORTER_REGISTRY

    assert "markdown" in REPORTER_REGISTRY
    assert REPORTER_REGISTRY["markdown"] is MarkdownReporter
