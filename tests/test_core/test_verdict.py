"""Tests for the two-register closing summary (AAT-122).

What these lock is mostly wording, which is unusual for a test suite and
deliberate here: the plain register is the only part of AWT addressed to
someone who cannot read the rest of the output. If it overstates what AWT
did, nothing downstream corrects it.
"""

from __future__ import annotations

from datetime import datetime

from aat.core.models import (
    ActionType,
    FileChange,
    FixResult,
    LoopIteration,
    LoopResult,
    RefusedChange,
    StepResult,
    StepStatus,
    TestResult,
)
from aat.core.verdict import (
    EDITED_SCENARIO,
    WROTE_IN_PLACE,
    WROTE_NOTHING,
    WROTE_ON_BRANCH,
    Verdict,
    render,
    render_developer,
    render_plain,
    verdict_from_loop,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _step(status: StepStatus = StepStatus.PASSED, error: str | None = None) -> StepResult:
    return StepResult(
        step=3,
        action=ActionType.FIND_AND_CLICK,
        status=status,
        description="Click the login button",
        error_message=error,
        elapsed_ms=10.0,
    )


def _test_result(*, passed: bool, steps: list[StepResult] | None = None) -> TestResult:
    steps = steps if steps is not None else [_step()]
    failed = sum(1 for s in steps if s.status in (StepStatus.FAILED, StepStatus.ERROR))
    return TestResult(
        scenario_id="SC-001",
        scenario_name="Login",
        passed=passed,
        steps=steps,
        total_steps=len(steps),
        passed_steps=len(steps) - failed,
        failed_steps=failed,
        duration_ms=10.0,
    )


def _fix() -> FixResult:
    return FixResult(
        description="fix it",
        files_changed=[FileChange(path="src/a.py", original="a", modified="b")],
        confidence=0.7,
    )


def _iteration(
    number: int = 1,
    *,
    passed: bool = False,
    applied: list[str] | None = None,
    refused: list[RefusedChange] | None = None,
    branch: str | None = None,
    commit: str | None = None,
    approved: bool | None = None,
    with_fix: bool = False,
    steps: list[StepResult] | None = None,
) -> LoopIteration:
    return LoopIteration(
        iteration=number,
        test_result=_test_result(passed=passed, steps=steps),
        fix=_fix() if with_fix else None,
        approved=approved,
        branch_name=branch,
        commit_hash=commit,
        applied_paths=applied or [],
        refused_changes=refused or [],
        timestamp=datetime(2026, 10, 7, 12, 0, 0),
    )


def _loop_result(
    iterations: list[LoopIteration],
    *,
    success: bool,
    reason: str | None = None,
) -> LoopResult:
    return LoopResult(
        success=success,
        total_iterations=len(iterations),
        iterations=iterations,
        reason=reason,
        duration_ms=100.0,
    )


# ---------------------------------------------------------------------------
# verdict_from_loop
# ---------------------------------------------------------------------------


def test_collects_applied_paths_without_repeating_them() -> None:
    """The same file touched twice is one changed file, not two."""
    result = _loop_result(
        [
            _iteration(1, applied=["src/a.py"]),
            _iteration(2, applied=["src/a.py", "src/b.py"], passed=True),
        ],
        success=True,
    )

    verdict = verdict_from_loop(result, WROTE_IN_PLACE)

    assert verdict.applied_paths == ("src/a.py", "src/b.py")
    assert verdict.passed is True
    assert verdict.attempts == 2


def test_collects_refusals_branches_and_commits() -> None:
    result = _loop_result(
        [
            _iteration(
                1,
                applied=["src/a.py"],
                refused=[RefusedChange(path="src/b.py", reason="Fix removes 1 `assert`")],
                branch="aat/fix-001",
                commit="abc1234",
            )
        ],
        success=False,
        reason="max loops exceeded",
    )

    verdict = verdict_from_loop(result, WROTE_ON_BRANCH)

    assert verdict.refused == (("src/b.py", "Fix removes 1 `assert`"),)
    assert verdict.branches == ("aat/fix-001",)
    assert verdict.commits == ("abc1234",)
    assert verdict.stopped_reason == "max loops exceeded"


def test_counts_an_approved_fix_that_was_never_written() -> None:
    """Manual mode's "Approve fix?" leads nowhere; the count says so."""
    result = _loop_result(
        [_iteration(1, approved=True, with_fix=True)],
        success=False,
        reason="max loops exceeded",
    )

    verdict = verdict_from_loop(result, WROTE_NOTHING)

    assert verdict.approved_but_unwritten == 1
    assert verdict.applied_paths == ()


def test_a_refused_fix_is_not_counted_as_unwritten() -> None:
    """Refused and never-applied are different answers, counted separately."""
    result = _loop_result(
        [
            _iteration(
                1,
                approved=True,
                with_fix=True,
                refused=[RefusedChange(path="src/a.py", reason="Fix removes 1 `assert`")],
            )
        ],
        success=False,
    )

    verdict = verdict_from_loop(result, WROTE_IN_PLACE)

    assert verdict.approved_but_unwritten == 0
    assert len(verdict.refused) == 1


def test_failing_steps_come_from_the_last_attempt() -> None:
    """What is broken now, not what was broken three attempts ago."""
    result = _loop_result(
        [
            _iteration(1, steps=[_step(StepStatus.FAILED, "old problem")]),
            _iteration(2, steps=[_step(StepStatus.FAILED, "Element not found")]),
        ],
        success=False,
        reason="max loops exceeded",
    )

    verdict = verdict_from_loop(result, WROTE_NOTHING)

    assert len(verdict.failing_steps) == 1
    assert "Element not found" in verdict.failing_steps[0]
    assert "old problem" not in verdict.failing_steps[0]


# ---------------------------------------------------------------------------
# The plain register
# ---------------------------------------------------------------------------


def test_plain_claims_a_fix_only_when_something_was_written() -> None:
    verdict = Verdict(
        passed=True,
        attempts=2,
        disposition=WROTE_IN_PLACE,
        applied_paths=("src/a.py",),
    )

    headline = render_plain(verdict)[0]

    assert headline == "The test passes now. AWT changed something to get there — see below."


def test_plain_does_not_claim_a_fix_when_nothing_was_written() -> None:
    """Passing on the first try is not AWT having repaired anything."""
    verdict = Verdict(passed=True, attempts=1, disposition=WROTE_NOTHING)

    assert render_plain(verdict)[0] == "The test passed. Nothing needed to change."


def test_plain_hands_an_unfixed_failure_back_to_a_person() -> None:
    verdict = Verdict(
        passed=False,
        attempts=3,
        disposition=WROTE_IN_PLACE,
        applied_paths=("src/a.py",),
        stopped_reason="max loops exceeded",
    )

    headline = render_plain(verdict)[0]

    assert "still fails" in headline
    assert "a person needs to look at this" in headline


def test_plain_says_nothing_changed_when_the_user_declined() -> None:
    verdict = Verdict(
        passed=False,
        attempts=1,
        disposition=WROTE_NOTHING,
        stopped_reason="user denied fix",
    )

    assert render_plain(verdict)[0].startswith("You turned down the fix")


def test_plain_names_the_files_it_changed() -> None:
    verdict = Verdict(
        passed=True,
        attempts=2,
        disposition=WROTE_IN_PLACE,
        applied_paths=("src/a.py", "src/b.py"),
    )

    body = "\n".join(render_plain(verdict))

    assert "Changed 2 files: src/a.py, src/b.py" in body


def test_plain_summarises_a_long_file_list() -> None:
    """A list of forty paths is not a plain-language sentence."""
    verdict = Verdict(
        passed=True,
        attempts=1,
        disposition=WROTE_IN_PLACE,
        applied_paths=tuple(f"src/f{i}.py" for i in range(8)),
    )

    body = "\n".join(render_plain(verdict))

    assert "and 3 more" in body
    assert "src/f7.py" not in body


def test_plain_explains_a_refusal_without_jargon() -> None:
    verdict = Verdict(
        passed=False,
        attempts=1,
        disposition=WROTE_IN_PLACE,
        refused=(("src/a.py", "Fix removes 1 `assert` with no replacement"),),
    )

    body = "\n".join(render_plain(verdict))

    assert "Turned down 1 proposed change" in body
    assert "deleted a check" in body


def test_plain_discloses_an_approved_fix_that_was_never_applied() -> None:
    """Otherwise the person walks away believing a fix landed."""
    verdict = Verdict(
        passed=False,
        attempts=1,
        disposition=WROTE_NOTHING,
        approved_but_unwritten=1,
    )

    body = "\n".join(render_plain(verdict))

    assert "did not write it" in body
    assert "--approval-mode branch" in body


def test_plain_describes_a_scenario_rewrite_as_what_it_is() -> None:
    verdict = Verdict(
        passed=True,
        attempts=2,
        disposition=EDITED_SCENARIO,
        scenario_edits=1,
    )

    body = "\n".join(render_plain(verdict))

    assert "Rewrote the test itself once" in body
    assert "not the page being wrong" in body
    assert render_plain(verdict)[0].startswith("The test passes now")


def test_plain_points_at_the_first_broken_step_and_the_report() -> None:
    verdict = Verdict(
        passed=False,
        attempts=1,
        disposition=WROTE_NOTHING,
        failing_steps=("Step 3 (find_and_click) — Click the login button: not found",),
        report_hint="reports",
    )

    body = "\n".join(render_plain(verdict))

    assert "What is still broken: Step 3 (find_and_click)" in body
    assert "Full report: reports" in body


# ---------------------------------------------------------------------------
# Undo — mode-specific, because the wrong instruction destroys work
# ---------------------------------------------------------------------------


def test_undo_for_branch_mode_points_at_the_branch() -> None:
    verdict = Verdict(
        passed=True,
        attempts=1,
        disposition=WROTE_ON_BRANCH,
        applied_paths=("src/a.py",),
        branches=("aat/fix-001", "aat/fix-002"),
    )

    body = "\n".join(render_plain(verdict))

    assert "not in your working copy" in body
    assert "git merge aat/fix-002" in body
    assert "git branch -D aat/fix-001 aat/fix-002" in body
    # The in-place instruction would discard the user's own edits here.
    assert "git checkout --" not in body


def test_undo_for_auto_mode_warns_what_discarding_also_takes() -> None:
    verdict = Verdict(
        passed=True,
        attempts=1,
        disposition=WROTE_IN_PLACE,
        applied_paths=("src/a.py",),
    )

    body = "\n".join(render_plain(verdict))

    assert "git checkout -- src/a.py" in body
    assert "discards any edits of your own" in body
    assert "git branch -D" not in body


def test_no_undo_line_when_nothing_was_written() -> None:
    verdict = Verdict(passed=True, attempts=1, disposition=WROTE_NOTHING)

    body = "\n".join(render_plain(verdict))

    assert "git " not in body


def test_no_branch_undo_line_without_a_branch_to_name() -> None:
    """Better silence than ``git branch -D`` with nothing after it."""
    verdict = Verdict(
        passed=True,
        attempts=1,
        disposition=WROTE_ON_BRANCH,
        applied_paths=("src/a.py",),
    )

    body = "\n".join(render_plain(verdict))

    assert "git " not in body


# ---------------------------------------------------------------------------
# The developer register
# ---------------------------------------------------------------------------


def test_developer_register_carries_the_detail_the_plain_one_drops() -> None:
    verdict = Verdict(
        passed=False,
        attempts=3,
        disposition=WROTE_ON_BRANCH,
        applied_paths=("src/a.py",),
        refused=(("src/b.py", "Fix removes 1 `assert` with no replacement"),),
        branches=("aat/fix-001",),
        commits=("abc1234",),
        failing_steps=("Step 3 (find_and_click) — Click the login button",),
        stopped_reason="max loops exceeded",
    )

    body = "\n".join(render_developer(verdict))

    assert "Result: fail after 3 iteration(s), mode=branch" in body
    assert "Stopped because: max loops exceeded" in body
    assert "Fix branches: aat/fix-001" in body
    assert "Commits: abc1234" in body
    assert "Files written: src/a.py" in body
    assert "Refused src/b.py: Fix removes 1 `assert` with no replacement" in body
    assert "Still failing: Step 3 (find_and_click)" in body


def test_developer_register_lists_every_failing_step() -> None:
    """The plain register shows one; this one shows all of them."""
    verdict = Verdict(
        passed=False,
        attempts=1,
        disposition=WROTE_NOTHING,
        failing_steps=("Step 3 (find_and_click) — a", "Step 7 (assert) — b"),
    )

    body = "\n".join(render_developer(verdict))

    assert "Still failing: Step 3 (find_and_click) — a" in body
    assert "Still failing: Step 7 (assert) — b" in body


def test_render_puts_the_plain_register_first() -> None:
    verdict = Verdict(
        passed=True,
        attempts=1,
        disposition=WROTE_IN_PLACE,
        applied_paths=("src/a.py",),
    )

    lines = render(verdict)

    assert lines[0] == render_plain(verdict)[0]
    assert "Details for a developer:" in lines
    detail_at = lines.index("Details for a developer:")
    assert all(line.startswith("  ") for line in lines[detail_at + 1 :])


def test_changed_anything_covers_both_kinds_of_change() -> None:
    assert not Verdict(passed=True, attempts=1, disposition=WROTE_NOTHING).changed_anything
    assert Verdict(
        passed=True, attempts=1, disposition=WROTE_IN_PLACE, applied_paths=("a",)
    ).changed_anything
    assert Verdict(
        passed=True, attempts=1, disposition=EDITED_SCENARIO, scenario_edits=1
    ).changed_anything
