"""Tests for DevQALoop orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aat.core.exceptions import LoopError
from aat.core.loop import DevQALoop
from aat.core.models import (
    ActionType,
    AnalysisResult,
    ApprovalMode,
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


def _make_config(
    max_loops: int = 3,
    approval_mode: ApprovalMode = ApprovalMode.MANUAL,
    source_path: str = ".",
) -> Config:
    return Config(
        max_loops=max_loops,
        reports_dir="/tmp/aat_test_reports",
        approval_mode=approval_mode,
        source_path=source_path,
    )


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
# Tests: all-pass scenario (manual mode, default)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_pass_single_iteration() -> None:
    """All tests pass on first iteration -> success, 1 iteration."""
    executor, adapter, reporter, engine = _make_mocks(step_results=[[_make_passed_step()]])

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
# Tests: fail -> analyze -> approve -> fix -> re-test pass (manual)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_then_fix_then_pass() -> None:
    """Fail -> analyze -> approve -> fix -> re-test pass = success after 2 iterations."""
    executor, adapter, reporter, engine = _make_mocks(
        step_results=[
            [_make_failed_step()],  # iteration 1: fail
            [_make_passed_step()],  # iteration 2: pass
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
# Tests: fail -> deny (manual)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_deny_fix() -> None:
    """Fail -> analyze -> deny fix = failure with reason 'user denied fix'."""
    executor, adapter, reporter, engine = _make_mocks(step_results=[[_make_failed_step()]])

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
# Tests: max_loops exceeded (manual)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_loops_exceeded() -> None:
    """All iterations fail -> max_loops exceeded."""
    executor, adapter, reporter, engine = _make_mocks(
        step_results=[
            [_make_failed_step()],  # iteration 1
            [_make_failed_step()],  # iteration 2
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


# ---------------------------------------------------------------------------
# Tests: skip_engine_lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skip_engine_lifecycle() -> None:
    """skip_engine_lifecycle=True skips engine.start() and engine.stop()."""
    executor, adapter, reporter, engine = _make_mocks(step_results=[[_make_passed_step()]])

    loop = DevQALoop(
        config=_make_config(),
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
    )

    result = await loop.run([_make_scenario()], skip_engine_lifecycle=True)

    assert result.success is True
    engine.start.assert_not_called()
    engine.stop.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: branch mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_branch_mode_creates_branch_and_commits() -> None:
    """Branch mode: creates branch, applies fix, commits, retests."""
    # iteration 1: fail, then retest on branch: pass
    # iteration 2 (after branch handler returns retest pass): loop sees pass
    executor, adapter, reporter, engine = _make_mocks(
        step_results=[
            [_make_failed_step()],  # initial test: fail
            [_make_passed_step()],  # retest on branch: pass
        ]
    )

    git_ops = AsyncMock()
    git_ops.is_git_repo.return_value = True
    git_ops.has_uncommitted_changes.return_value = False
    git_ops.apply_file_changes.return_value = [Path("/tmp/src/server.py")]
    git_ops.commit_changes.return_value = "abc1234"

    # Make on_fix_branch work as an async context manager
    git_ops.on_fix_branch = MagicMock()
    ctx = AsyncMock()
    git_ops.on_fix_branch.return_value = ctx

    loop = DevQALoop(
        config=_make_config(approval_mode=ApprovalMode.BRANCH),
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
        git_ops=git_ops,
    )

    result = await loop.run([_make_scenario()])

    # The retest passed, so the iteration records pass
    assert len(result.iterations) == 1
    it = result.iterations[0]
    assert it.branch_name == "aat/fix-001"
    assert it.commit_hash == "abc1234"
    assert it.fix is not None
    assert it.analysis is not None

    git_ops.on_fix_branch.assert_called_once_with("aat/fix-001")
    git_ops.apply_file_changes.assert_called_once()
    git_ops.commit_changes.assert_called_once()


@pytest.mark.asyncio
async def test_branch_mode_no_git_repo_raises() -> None:
    """Branch mode without git repo raises LoopError."""
    executor, adapter, reporter, engine = _make_mocks()

    git_ops = AsyncMock()
    git_ops.is_git_repo.return_value = False

    loop = DevQALoop(
        config=_make_config(approval_mode=ApprovalMode.BRANCH),
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
        git_ops=git_ops,
    )

    with pytest.raises(LoopError, match="requires a git repository"):
        await loop.run([_make_scenario()])


@pytest.mark.asyncio
async def test_branch_mode_no_git_ops_raises() -> None:
    """Branch mode without GitOps instance raises LoopError."""
    executor, adapter, reporter, engine = _make_mocks()

    loop = DevQALoop(
        config=_make_config(approval_mode=ApprovalMode.BRANCH),
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
        # git_ops not provided
    )

    with pytest.raises(LoopError, match="requires GitOps instance"):
        await loop.run([_make_scenario()])


@pytest.mark.asyncio
async def test_branch_mode_uncommitted_changes_raises() -> None:
    """Branch mode with uncommitted changes raises LoopError."""
    executor, adapter, reporter, engine = _make_mocks()

    git_ops = AsyncMock()
    git_ops.is_git_repo.return_value = True
    git_ops.has_uncommitted_changes.return_value = True

    loop = DevQALoop(
        config=_make_config(approval_mode=ApprovalMode.BRANCH),
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
        git_ops=git_ops,
    )

    with pytest.raises(LoopError, match="clean working tree"):
        await loop.run([_make_scenario()])


# ---------------------------------------------------------------------------
# Tests: auto mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_mode_applies_fix_directly(tmp_path: Path) -> None:
    """Auto mode: applies fix directly to disk, retests."""
    executor, adapter, reporter, engine = _make_mocks(
        step_results=[
            [_make_failed_step()],  # initial test: fail
            [_make_passed_step()],  # retest after fix: pass
        ]
    )

    loop = DevQALoop(
        config=_make_config(
            approval_mode=ApprovalMode.AUTO,
            source_path=str(tmp_path),
        ),
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
    )

    result = await loop.run([_make_scenario()])

    # Retest passed, so iteration has pass result
    assert len(result.iterations) == 1
    it = result.iterations[0]
    assert it.approved is True
    assert it.fix is not None

    # File should have been written
    assert (tmp_path / "src" / "server.py").read_text() == "new"
