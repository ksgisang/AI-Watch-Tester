"""Tests for DevQALoop orchestrator."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aat.core.exceptions import LoopError
from aat.core.loop import DevQALoop, _removed_guards
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
    # Fix is now generated BEFORE approval (so user can see diff)
    assert result.iterations[0].fix is not None

    adapter.generate_fix.assert_called_once()


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


# ---------------------------------------------------------------------------
# Tests: guard-removal screening (AAT-122)
# ---------------------------------------------------------------------------


def _change(path: str, original: str, modified: str) -> FileChange:
    return FileChange(path=path, original=original, modified=modified)


def _loop_for(tmp_path: Path) -> DevQALoop:
    executor, adapter, reporter, engine = _make_mocks()
    return DevQALoop(
        config=_make_config(approval_mode=ApprovalMode.AUTO, source_path=str(tmp_path)),
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
    )


def test_removed_guards_reports_any_net_loss_of_a_hard_guard() -> None:
    """Dropping one `assert` is reported even though others remain."""
    before = "assert a\nassert b\nraise ValueError()\n"
    after = "assert a\nraise ValueError()\n"

    assert _removed_guards(before, after) == "1 `assert`"


def test_removed_guards_ignores_a_hard_guard_that_was_added() -> None:
    """More checks than before is not a loss."""
    assert _removed_guards("assert a\n", "assert a\nassert b\n") == ""


def test_removed_guards_tolerates_partial_loss_of_a_soft_guard() -> None:
    """A fix that collapses two branches into one is ordinary refactoring.

    Soft guards are refused only when every last one disappears — the same
    calibration the pre-existing "removes all import statements" rule uses.
    Refusing on any net loss here would block most real fixes.
    """
    before = "if a:\n    x()\nif b:\n    y()\n"
    after = "if a or b:\n    x()\n"

    assert _removed_guards(before, after) == ""


def test_removed_guards_refuses_when_every_soft_guard_disappears() -> None:
    before = "if a:\n    x()\nif b:\n    y()\n"
    after = "x()\ny()\n"

    assert _removed_guards(before, after) == "every `if` (2)"


def test_removed_guards_does_not_count_keywords_inside_longer_words() -> None:
    """`assertEqual` contains `assert`; `notify` contains `if`.

    Substring counting turns ordinary deletions into refusals: dropping one
    of two ``assertEqual`` calls looks like losing an ``assert``, and deleting
    the last ``notify`` looks like every branch in the file disappearing.
    """
    # Hard guard: the real `assert` survives, only an `assertEqual` goes.
    assert (
        _removed_guards(
            "self.assertEqual(a, b)\nself.assertEqual(c, d)\nassert x\n",
            "self.assertEqual(a, b)\nassert x\n",
        )
        == ""
    )

    # Soft guard: nothing in either side is a branch to begin with.
    assert _removed_guards("verify(a)\nnotify(b)\n", "verify(a)\n") == ""


def test_removed_guards_ignores_guard_words_in_comments() -> None:
    """Deleting a comment that mentions a check is not deleting the check."""
    before = "# raise if the token is stale\nx()\n"
    after = "x()\n"

    assert _removed_guards(before, after) == ""


def test_validate_fix_refuses_a_fix_that_deletes_a_check(tmp_path: Path) -> None:
    loop = _loop_for(tmp_path)

    safe, reason = loop._validate_fix(
        _change(
            "src/auth.py",
            "def login(token):\n    if not token:\n        raise ValueError('no token')\n"
            "    return True\n",
            "def login(token):\n    return True\n",
        )
    )

    assert safe is False
    assert "raise" in reason
    assert "every `if`" in reason


def test_validate_fix_allows_a_fix_that_keeps_its_checks(tmp_path: Path) -> None:
    loop = _loop_for(tmp_path)

    safe, reason = loop._validate_fix(
        _change(
            "src/auth.py",
            "def login(token):\n    if not token:\n        raise ValueError('no token')\n"
            "    return True\n",
            "def login(token):\n    if not token:\n        raise ValueError('missing token')\n"
            "    return bool(token)\n",
        )
    )

    assert safe is True
    assert reason == ""


def test_validate_fix_leaves_prose_files_alone(tmp_path: Path) -> None:
    """The guard check is scoped to code extensions on purpose.

    Run over Markdown it would refuse any edit that drops a sentence
    containing the word "if".
    """
    loop = _loop_for(tmp_path)

    safe, _ = loop._validate_fix(
        _change("README.md", "Use it if you want to.\nSee also.\n", "See also.\n")
    )

    assert safe is True


def test_validate_fix_compares_against_the_file_on_disk_not_the_model_story(
    tmp_path: Path,
) -> None:
    """``change.original`` is the model's account of its own input.

    A model that hands back only the lines it kept makes every before/after
    comparison come out clean. The file on disk cannot be talked down.
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text(
        "def login(token):\n    if not token:\n        raise ValueError('no token')\n"
        "    return True\n",
        encoding="utf-8",
    )

    loop = _loop_for(tmp_path)

    safe, reason = loop._validate_fix(
        _change(
            "src/auth.py",
            # The model reports an input that never had the check in it.
            "def login(token):\n    return True\n",
            "def login(token):\n    return True\n",
        )
    )

    assert safe is False
    assert "raise" in reason


def test_validate_fix_trusts_the_model_original_for_a_file_that_does_not_exist(
    tmp_path: Path,
) -> None:
    """A path with nothing behind it is a new file, and empty is the truth."""
    loop = _loop_for(tmp_path)

    safe, reason = loop._validate_fix(
        _change("src/brand_new.py", "", "def handler():\n    return 1\n")
    )

    assert safe is True
    assert reason == ""


def test_screen_changes_splits_the_proposal_and_keeps_the_reason(tmp_path: Path) -> None:
    loop = _loop_for(tmp_path)

    fix = FixResult(
        description="two changes",
        files_changed=[
            _change("src/ok.py", "x = 1\n", "x = 2\n"),
            _change(
                "src/bad.py",
                "if a:\n    raise ValueError()\n",
                "pass\n",
            ),
        ],
        confidence=0.5,
    )

    safe_changes, refused = loop._screen_changes(fix)

    assert [c.path for c in safe_changes] == ["src/ok.py"]
    assert len(refused) == 1
    assert refused[0].path == "src/bad.py"
    assert "raise" in refused[0].reason


# ---------------------------------------------------------------------------
# Tests: the iteration records what landed, not what was proposed (AAT-122)
# ---------------------------------------------------------------------------


def _mixed_fix() -> FixResult:
    return FixResult(
        description="one good change, one that guts a check",
        files_changed=[
            FileChange(path="src/ok.py", original="x = 1\n", modified="x = 2\n"),
            FileChange(
                path="src/bad.py",
                original="if a:\n    raise ValueError()\n",
                modified="pass\n",
            ),
        ],
        confidence=0.5,
    )


@pytest.mark.asyncio
async def test_auto_mode_records_only_what_it_wrote(tmp_path: Path) -> None:
    """The refused change is neither written nor counted as applied."""
    executor, adapter, reporter, engine = _make_mocks(
        step_results=[[_make_failed_step()], [_make_passed_step()]]
    )
    adapter.generate_fix.return_value = _mixed_fix()

    loop = DevQALoop(
        config=_make_config(approval_mode=ApprovalMode.AUTO, source_path=str(tmp_path)),
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
    )

    result = await loop.run([_make_scenario()])

    it = result.iterations[0]
    assert it.applied_paths == ["src/ok.py"]
    assert [r.path for r in it.refused_changes] == ["src/bad.py"]

    assert (tmp_path / "src" / "ok.py").read_text() == "x = 2\n"
    assert not (tmp_path / "src" / "bad.py").exists()

    # The proposal itself is kept intact — it is what the report shows.
    assert it.fix is not None
    assert len(it.fix.files_changed) == 2


@pytest.mark.asyncio
async def test_branch_mode_commits_only_the_screened_changes(tmp_path: Path) -> None:
    """Branch mode used to record the unfiltered proposal while writing part."""
    executor, adapter, reporter, engine = _make_mocks(
        step_results=[[_make_failed_step()], [_make_passed_step()]]
    )
    adapter.generate_fix.return_value = _mixed_fix()

    git_ops = AsyncMock()
    git_ops.is_git_repo.return_value = True
    git_ops.has_uncommitted_changes.return_value = False
    git_ops.apply_file_changes.return_value = [Path("/tmp/src/ok.py")]
    git_ops.commit_changes.return_value = "abc1234"
    git_ops.on_fix_branch = MagicMock(return_value=AsyncMock())

    loop = DevQALoop(
        config=_make_config(
            approval_mode=ApprovalMode.BRANCH,
            source_path=str(tmp_path),
        ),
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
        git_ops=git_ops,
    )

    result = await loop.run([_make_scenario()])

    it = result.iterations[0]
    assert it.applied_paths == ["src/ok.py"]
    assert [r.path for r in it.refused_changes] == ["src/bad.py"]

    handed_to_git = git_ops.apply_file_changes.call_args.args[0]
    assert [c.path for c in handed_to_git] == ["src/ok.py"]


@pytest.mark.asyncio
async def test_manual_mode_approval_writes_nothing(tmp_path: Path) -> None:
    """Manual mode asks "Approve fix?" and then applies nothing, by design.

    This test exists to keep that visible. The ending discloses it through
    ``Verdict.approved_but_unwritten``, which is only correct as long as
    ``applied_paths`` stays empty here.
    """
    executor, adapter, reporter, engine = _make_mocks(
        step_results=[[_make_failed_step()], [_make_failed_step()]]
    )

    loop = DevQALoop(
        config=_make_config(
            max_loops=1,
            approval_mode=ApprovalMode.MANUAL,
            source_path=str(tmp_path),
        ),
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
        approval_callback=lambda _: True,
    )

    result = await loop.run([_make_scenario()])

    it = result.iterations[0]
    assert it.approved is True
    assert it.fix is not None
    assert it.fix.files_changed  # a fix was produced
    assert it.applied_paths == []  # and none of it was written
    assert it.refused_changes == []
    assert not (tmp_path / "src").exists()


# ---------------------------------------------------------------------------
# Tests: the loop re-tests the scenario it was given (AAT-122)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_retests_the_original_scenario_unmodified(tmp_path: Path) -> None:
    """Every retest runs the scenario the user approved, not an edited one.

    This is the one mechanical line between "fixing the code" and "making the
    test agree with the code". ``aat loop`` has never rewritten a scenario;
    this locks that, so a future convenience that quietly relaxes a failing
    step has to break a test to get in.
    """
    executor, adapter, reporter, engine = _make_mocks(
        step_results=[
            [_make_failed_step()],  # iteration 1
            [_make_failed_step()],  # retest inside the auto handler
            [_make_failed_step()],  # iteration 2
            [_make_failed_step()],  # retest inside the auto handler
        ]
    )

    scenario = _make_scenario()
    before = scenario.model_dump(mode="json")

    loop = DevQALoop(
        config=_make_config(
            max_loops=2,
            approval_mode=ApprovalMode.AUTO,
            source_path=str(tmp_path),
        ),
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
    )

    await loop.run([scenario])

    assert scenario.model_dump(mode="json") == before

    # And every step the executor saw came from that same scenario object.
    executed = [call.args[0] for call in executor.execute_step.call_args_list]
    assert executed
    assert all(step is scenario.steps[0] for step in executed)
