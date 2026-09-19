"""Tests for aat run command."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003
from typing import Any

import pytest
import typer.main
from typer.testing import CliRunner

from aat.cli.commands.run_cmd import _build_test_result, _exit_code, _write_reports
from aat.cli.main import app
from aat.core.models import (
    ActionType,
    Scenario,
    StepConfig,
    StepResult,
    StepStatus,
    TestResult,
)

runner = CliRunner()


def _flags(command: str) -> set[str]:
    """Every flag a command accepts, read off the command itself."""
    group: Any = typer.main.get_command(app)
    return {name for param in group.commands[command].params for name in param.opts}


def test_run_nonexistent_path() -> None:
    """aat run fails with a nonexistent scenario path."""
    result = runner.invoke(app, ["run", "/nonexistent/scenarios"])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_run_command_exists() -> None:
    """aat run is registered and shows help."""
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "scenarios" in result.output.lower() or "SCENARIOS_PATH" in result.output


def test_run_offers_no_learn() -> None:
    """The switch that turns remembered coordinates off is on the command.

    Read off the command rather than out of --help: the rendered help box is
    laid out for whatever terminal width the suite happens to run at, so a
    narrow one wraps or clips the option column and the switch vanishes from
    the text while still being perfectly usable.
    """
    assert "--no-learn" in _flags("run")


def test_run_offers_report() -> None:
    """A run can write its own report."""
    assert "--report" in _flags("run")


def test_loop_offers_report_format() -> None:
    """So can a loop, in either format."""
    assert "--report-format" in _flags("loop")


def test_unknown_report_format_stops_before_the_browser_opens() -> None:
    """The format is checked up front — after a long run is too late."""
    result = runner.invoke(app, ["run", "/nonexistent/scenarios", "--report", "powerpoint"])
    assert result.exit_code == 1
    assert "powerpoint" in result.output
    assert "pdf" in result.output


class TestBuildTestResult:
    """What the reporter is handed after a scenario finishes."""

    def _scenario(self) -> Scenario:
        return Scenario(
            id="SC-001",
            name="Grade a question",
            steps=[
                StepConfig(
                    step=1,
                    action=ActionType.NAVIGATE,
                    value="https://example.com",
                    description="Open the app",
                )
            ],
        )

    def _step(self, number: int, status: StepStatus) -> StepResult:
        return StepResult(
            step=number,
            action=ActionType.FIND_AND_CLICK,
            status=status,
            description=f"Step {number}",
        )

    def test_counts_match_the_steps(self) -> None:
        steps = [
            self._step(1, StepStatus.PASSED),
            self._step(2, StepStatus.WARNING),
            self._step(3, StepStatus.FAILED),
        ]
        result = _build_test_result(self._scenario(), steps, 1234.0)

        assert result.scenario_id == "SC-001"
        assert result.total_steps == 3
        assert result.passed_steps == 1
        assert result.failed_steps == 1
        assert result.duration_ms == 1234.0
        assert result.passed is False

    def test_a_warned_run_is_not_counted_as_failed(self) -> None:
        """A warning is its own thing: not a pass, and not a failure either."""
        steps = [self._step(1, StepStatus.PASSED), self._step(2, StepStatus.WARNING)]
        result = _build_test_result(self._scenario(), steps, 10.0)

        assert result.failed_steps == 0
        assert result.passed_steps == 1
        assert result.total_steps == 2


class TestWriteReports:
    """Where the reports land, and what happens when one cannot be written."""

    def _result(self, scenario_id: str) -> TestResult:
        step = StepResult(
            step=1,
            action=ActionType.NAVIGATE,
            status=StepStatus.PASSED,
            description="Open the app",
        )
        return TestResult(
            scenario_id=scenario_id,
            scenario_name="Run",
            passed=True,
            steps=[step],
            total_steps=1,
            passed_steps=1,
            failed_steps=0,
            duration_ms=5.0,
        )

    async def test_one_directory_per_scenario(self, tmp_path: Path) -> None:
        """Scenarios must not overwrite each other's report."""
        results = [self._result("SC-001"), self._result("SC-002")]

        await _write_reports("markdown", results, tmp_path)

        assert (tmp_path / "SC-001" / "report.md").exists()
        assert (tmp_path / "SC-002" / "report.md").exists()

    async def test_a_report_that_fails_does_not_stop_the_rest(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The run already happened; paperwork must not swallow its result."""
        (tmp_path / "SC-001").write_text("in the way", encoding="utf-8")

        results = [self._result("SC-001"), self._result("SC-002")]
        await _write_reports("markdown", results, tmp_path)

        assert (tmp_path / "SC-002" / "report.md").exists()
        assert "SC-001" in capsys.readouterr().err


class TestExitCode:
    """What the process tells the pipeline that called it."""

    def test_clean_run_is_zero(self) -> None:
        assert (
            _exit_code(
                had_critical=False,
                total_failed=0,
                total_skipped=0,
                total_warned=0,
                strict_mode=False,
            )
            == 0
        )

    def test_a_step_that_changed_nothing_is_not_a_clean_exit(self) -> None:
        """The whole point: a warning must not leave the pipeline green."""
        assert (
            _exit_code(
                had_critical=False,
                total_failed=0,
                total_skipped=0,
                total_warned=1,
                strict_mode=False,
            )
            == 3
        )

    def test_a_real_failure_outranks_a_warning(self) -> None:
        assert (
            _exit_code(
                had_critical=False,
                total_failed=1,
                total_skipped=0,
                total_warned=2,
                strict_mode=False,
            )
            == 1
        )

    def test_critical_outranks_everything(self) -> None:
        assert (
            _exit_code(
                had_critical=True,
                total_failed=1,
                total_skipped=1,
                total_warned=1,
                strict_mode=True,
            )
            == 2
        )

    def test_skips_only_fail_under_strict(self) -> None:
        kwargs = {"had_critical": False, "total_failed": 0, "total_skipped": 2, "total_warned": 0}
        assert _exit_code(**kwargs, strict_mode=False) == 0
        assert _exit_code(**kwargs, strict_mode=True) == 1
