"""Tests for DevQALoop orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from aat.core.exceptions import LoopError
from aat.core.loop import DevQALoop
from aat.core.models import (
    ActionType,
    AnalysisResult,
    Config,
    FileChange,
    FixResult,
    Scenario,
    Severity,
    StepConfig,
    StepResult,
    StepStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(max_loops: int = 3) -> Config:
    return Config(max_loops=max_loops, reports_dir="/tmp/aat_test_reports")


def _make_scenario() -> Scenario:
    return Scenario(
        id="SC-001",
        name="Login test",
        steps=[
            StepConfig(
                step=1,
                action=ActionType.NAVIGATE,
                description="Navigate to login",
                value="https://example.com/login",
            ),
        ],
    )


def _make_passed_step() -> StepResult:
    return StepResult(
        step=1,
        action=ActionType.NAVIGATE,
        status=StepStatus.PASSED,
        description="Navigate to login",
        elapsed_ms=100.0,
    )


def _make_failed_step() -> StepResult:
    return StepResult(
        step=1,
        action=ActionType.NAVIGATE,
        status=StepStatus.FAILED,
        description="Navigate to login",
        error_message="Connection refused",
        elapsed_ms=5000.0,
    )


def _make_analysis() -> AnalysisResult:
    return AnalysisResult(
        cause="Server down",
        suggestion="Check server status",
        severity=Severity.CRITICAL,
        related_files=["src/server.py"],
    )


def _make_fix() -> FixResult:
    return FixResult(
        description="Restart server",
        files_changed=[
            FileChange(
                path="src/server.py",
                original="old",
                modified="new",
            )
        ],
        confidence=0.8,
    )


def _make_mocks(
    step_results: list[list[StepResult]] | None = None,
) -> tuple[Any, ...]:
    """Create mock executor, adapter, reporter, engine.

    step_results: list of lists of StepResult, one per call to execute_step.
    Each inner list is one scenario execution's steps in sequence.
    """
    executor = AsyncMock()
    adapter = AsyncMock()
    reporter = AsyncMock()
    engine = AsyncMock()

    if step_results:
        flat = [s for group in step_results for s in group]
        executor.execute_step.side_effect = flat

    adapter.analyze_failure.return_value = _make_analysis()
    adapter.generate_fix.return_value = _make_fix()
    reporter.generate.return_value = Path("/tmp/report.md")

    return executor, adapter, reporter, engine


# ---------------------------------------------------------------------------
# Tests: all-pass scenario
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_pass_single_iteration() -> None:
    """All tests pass on first iteration -> success, 1 iteration."""
    executor, adapter, reporter, engine = _make_mocks(
        step_results=[[_make_passed_step()]]
    )

    loop = DevQALoop(
        config=_make_config(),
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
    )

    result = await loop.run([_make_scenario()])

    assert result.success is True
    assert result.total_iterations == 1
    assert len(result.iterations) == 1
    assert result.iterations[0].test_result.passed is True
    assert result.iterations[0].analysis is None
    assert result.iterations[0].fix is None

    engine.start.assert_called_once()
    engine.stop.assert_called_once()
    reporter.generate.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: fail -> analyze -> approve -> fix -> re-test pass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_then_fix_then_pass() -> None:
    """Fail -> analyze -> approve -> fix -> re-test pass = success after 2 iterations."""
    executor, adapter, reporter, engine = _make_mocks(
        step_results=[
            [_make_failed_step()],   # iteration 1: fail
            [_make_passed_step()],   # iteration 2: pass
        ]
    )

    approval_calls: list[str] = []

    def approve_callback(text: str) -> bool:
        approval_calls.append(text)
        return True

    loop = DevQALoop(
        config=_make_config(),
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
        approval_callback=approve_callback,
    )

    result = await loop.run([_make_scenario()])

    assert result.success is True
    assert result.total_iterations == 2
    assert len(result.iterations) == 2

    # First iteration: failed, has analysis and fix
    it1 = result.iterations[0]
    assert it1.test_result.passed is False
    assert it1.analysis is not None
    assert it1.fix is not None
    assert it1.approved is True

    # Second iteration: passed
    it2 = result.iterations[1]
    assert it2.test_result.passed is True

    assert len(approval_calls) == 1
    adapter.analyze_failure.assert_called_once()
    adapter.generate_fix.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: fail -> deny
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_deny_fix() -> None:
    """Fail -> analyze -> deny fix = failure with reason 'user denied fix'."""
    executor, adapter, reporter, engine = _make_mocks(
        step_results=[[_make_failed_step()]]
    )

    loop = DevQALoop(
        config=_make_config(),
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
        approval_callback=lambda _: False,
    )

    result = await loop.run([_make_scenario()])

    assert result.success is False
    assert result.total_iterations == 1
    assert result.reason == "user denied fix"
    assert result.iterations[0].approved is False
    assert result.iterations[0].analysis is not None
    assert result.iterations[0].fix is None

    adapter.generate_fix.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: max_loops exceeded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_loops_exceeded() -> None:
    """All iterations fail -> max_loops exceeded."""
    executor, adapter, reporter, engine = _make_mocks(
        step_results=[
            [_make_failed_step()],   # iteration 1
            [_make_failed_step()],   # iteration 2
        ]
    )

    loop = DevQALoop(
        config=_make_config(max_loops=2),
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
        approval_callback=lambda _: True,
    )

    result = await loop.run([_make_scenario()])

    assert result.success is False
    assert result.total_iterations == 2
    assert result.reason == "max loops exceeded"
    assert len(result.iterations) == 2


# ---------------------------------------------------------------------------
# Tests: engine lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engine_stop_called_on_error() -> None:
    """engine.stop() is called even if the loop raises an error."""
    executor = AsyncMock()
    adapter = AsyncMock()
    reporter = AsyncMock()
    engine = AsyncMock()

    executor.execute_step.side_effect = RuntimeError("unexpected")

    loop = DevQALoop(
        config=_make_config(),
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
    )

    with pytest.raises(LoopError, match="DevQA Loop failed"):
        await loop.run([_make_scenario()])

    engine.stop.assert_called_once()
