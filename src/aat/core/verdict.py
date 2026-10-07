"""The closing summary, written twice for two different readers.

``aat loop`` used to end with ``Loop FAILURE after 3 iteration(s)`` and a
``Reason: max loops exceeded``. That is accurate and it is addressed to
somebody who already knows what an iteration is and what the loop was trying
to do. The person this product is aimed at — someone who built a site with an
AI's help and wants to know whether it works — reads that line and learns
nothing they can act on.

So the ending is rendered in two registers from one set of facts:

``render_plain``
    What broke, what AWT did about it, where that leaves them, and how to put
    it back. No iteration counts, no category codes, no file diffs.

``render_developer``
    Everything the plain register left out, under its own heading.

Both read the same :class:`Verdict`, which is the only place the facts are
assembled. Two renderers over one structure, rather than each command writing
its own ending, follows ``build_reporter`` (AAT-111) and
``evaluate_scenario_expectations`` (AAT-115): a summary that says different
things depending on which command printed it is worse than no summary.

Nothing in here is allowed to overstate. "AWT fixed it" is only printed when
AWT wrote a file *and* the retest passed; when it could not, the plain
register says so in those words and hands the problem back to a person.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aat.core.models import LoopResult

#: How many paths to name before summarising the rest. A list of forty files
#: is not a plain-language sentence.
_MAX_NAMED_PATHS = 5

#: Where the fixes ended up, which decides what "undo" means.
WROTE_IN_PLACE = "auto"
WROTE_ON_BRANCH = "branch"
WROTE_NOTHING = "manual"
EDITED_SCENARIO = "scenario"


@dataclass(frozen=True)
class Verdict:
    """Everything both registers need, gathered once.

    Deliberately not a Pydantic model: it never crosses a process boundary and
    is never persisted. It exists so the two renderers cannot disagree about
    the facts.
    """

    passed: bool
    attempts: int
    #: One of the four ``WROTE_*``/``EDITED_*`` constants above.
    disposition: str
    #: Files AWT actually wrote. Not what the model proposed — AAT-122 split
    #: those apart because ``branch`` mode was reporting the proposal.
    applied_paths: tuple[str, ...] = ()
    #: ``(path, reason)`` for each change validation refused to write.
    refused: tuple[tuple[str, str], ...] = ()
    #: Fix branches created, in order.
    branches: tuple[str, ...] = ()
    #: How many times the scenario file itself was rewritten (``aat devqa``).
    scenario_edits: int = 0
    #: Fixes the person approved that were never written to disk. ``manual``
    #: mode prompts "Approve fix?" and then changes nothing, by design — but
    #: saying nothing about it leaves someone believing a fix landed.
    approved_but_unwritten: int = 0
    #: Short descriptions of the steps still failing at the end.
    failing_steps: tuple[str, ...] = ()
    #: Machine-ish reason the run stopped, when there is one.
    stopped_reason: str | None = None
    #: Where the written report landed, if one was written.
    report_hint: str | None = None
    commits: tuple[str, ...] = field(default=())

    @property
    def changed_anything(self) -> bool:
        return bool(self.applied_paths) or self.scenario_edits > 0


def verdict_from_loop(result: LoopResult, disposition: str) -> Verdict:
    """Collect the facts of a finished ``aat loop`` run."""
    applied: list[str] = []
    refused: list[tuple[str, str]] = []
    branches: list[str] = []
    commits: list[str] = []
    unwritten = 0

    for iteration in result.iterations:
        for path in iteration.applied_paths:
            if path not in applied:
                applied.append(path)
        refused.extend((r.path, r.reason) for r in iteration.refused_changes)
        if iteration.branch_name:
            branches.append(iteration.branch_name)
        if iteration.commit_hash:
            commits.append(iteration.commit_hash)
        if (
            iteration.approved
            and iteration.fix
            and iteration.fix.files_changed
            and not iteration.applied_paths
            and not iteration.refused_changes
        ):
            unwritten += 1

    failing: list[str] = []
    if result.iterations:
        from aat.core.models import StepStatus

        last = result.iterations[-1].test_result
        failing = [
            f"Step {s.step} ({s.action.value}) — {s.description}"
            + (f": {s.error_message}" if s.error_message else "")
            for s in last.steps
            if s.status in (StepStatus.FAILED, StepStatus.ERROR)
        ]

    return Verdict(
        passed=result.success,
        attempts=result.total_iterations,
        disposition=disposition,
        applied_paths=tuple(applied),
        refused=tuple(refused),
        branches=tuple(branches),
        approved_but_unwritten=unwritten,
        failing_steps=tuple(failing),
        stopped_reason=result.reason,
        commits=tuple(commits),
    )


# ----------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------


def _name_paths(paths: tuple[str, ...]) -> str:
    if len(paths) <= _MAX_NAMED_PATHS:
        return ", ".join(paths)
    shown = ", ".join(paths[:_MAX_NAMED_PATHS])
    return f"{shown} and {len(paths) - _MAX_NAMED_PATHS} more"


def _headline(verdict: Verdict) -> str:
    """The one line to read if you read nothing else."""
    if verdict.stopped_reason == "user denied fix":
        return "You turned down the fix, so nothing was changed. The test still fails."
    if verdict.passed and verdict.changed_anything:
        return "The test passes now. AWT changed something to get there — see below."
    if verdict.passed:
        return "The test passed. Nothing needed to change."
    if verdict.changed_anything:
        return (
            "The test still fails. AWT tried to fix it and could not — "
            "a person needs to look at this."
        )
    return "The test failed. AWT did not change anything — a person needs to look at this."


def _undo_line(verdict: Verdict) -> str | None:
    """How to put things back, in the one form that applies here.

    Mode-specific because the three modes leave the work in three different
    places, and the wrong instruction is worse than none: ``git checkout main``
    does nothing to files sitting uncommitted in the working tree, and
    ``git checkout -- <path>`` throws those files away for good.
    """
    if not verdict.applied_paths:
        return None
    if verdict.disposition == WROTE_ON_BRANCH:
        if not verdict.branches:
            return None
        return (
            f"The changes are on {', '.join(verdict.branches)}, not in your working "
            f"copy. To keep them: git merge {verdict.branches[-1]}. "
            f"To throw them away: git branch -D {' '.join(verdict.branches)}"
        )
    if verdict.disposition == WROTE_IN_PLACE:
        return (
            "The changes are in your files already, uncommitted. To throw them away: "
            f"git checkout -- {_name_paths(verdict.applied_paths)} — note this also "
            "discards any edits of your own to those same files."
        )
    return None


def render_plain(verdict: Verdict) -> list[str]:
    """The summary for someone who does not read stack traces."""
    lines = [_headline(verdict)]

    if verdict.applied_paths:
        count = len(verdict.applied_paths)
        noun = "file" if count == 1 else "files"
        lines.append(f"Changed {count} {noun}: {_name_paths(verdict.applied_paths)}")
    if verdict.scenario_edits:
        times = "once" if verdict.scenario_edits == 1 else f"{verdict.scenario_edits} times"
        lines.append(
            f"Rewrote the test itself {times} — the test was looking for the wrong "
            "thing on the page, not the page being wrong."
        )

    if verdict.refused:
        count = len(verdict.refused)
        noun = "change" if count == 1 else "changes"
        lines.append(
            f"Turned down {count} proposed {noun} that would have deleted a check "
            "instead of fixing anything. Those are listed below."
        )

    if verdict.approved_but_unwritten:
        lines.append(
            f"Worked out a fix for {verdict.approved_but_unwritten} of those and did "
            "not write it: this mode never touches your files. To have AWT apply a "
            "fix on a git branch and re-test it there, run again with "
            "--approval-mode branch."
        )

    undo = _undo_line(verdict)
    if undo:
        lines.append(undo)

    if not verdict.passed and verdict.failing_steps:
        lines.append(f"What is still broken: {verdict.failing_steps[0]}")
    if verdict.report_hint:
        lines.append(f"Full report: {verdict.report_hint}")

    return lines


def render_developer(verdict: Verdict) -> list[str]:
    """Everything the plain register left out."""
    lines = [
        f"Result: {'pass' if verdict.passed else 'fail'} "
        f"after {verdict.attempts} iteration(s), mode={verdict.disposition}"
    ]
    if verdict.stopped_reason:
        lines.append(f"Stopped because: {verdict.stopped_reason}")
    if verdict.branches:
        lines.append(f"Fix branches: {', '.join(verdict.branches)}")
    if verdict.commits:
        lines.append(f"Commits: {', '.join(verdict.commits)}")
    if verdict.applied_paths:
        lines.append(f"Files written: {', '.join(verdict.applied_paths)}")
    if verdict.approved_but_unwritten:
        lines.append(
            f"Approved but not written: {verdict.approved_but_unwritten} "
            "(manual mode applies nothing)"
        )
    if verdict.scenario_edits:
        lines.append(f"Scenario file rewrites: {verdict.scenario_edits}")
    for path, reason in verdict.refused:
        lines.append(f"Refused {path}: {reason}")
    for step in verdict.failing_steps:
        lines.append(f"Still failing: {step}")
    return lines


def render(verdict: Verdict) -> list[str]:
    """Both registers, plain first, developer detail indented beneath it."""
    lines = list(render_plain(verdict))
    detail = render_developer(verdict)
    if detail:
        lines.append("")
        lines.append("Details for a developer:")
        lines.extend(f"  {line}" for line in detail)
    return lines
