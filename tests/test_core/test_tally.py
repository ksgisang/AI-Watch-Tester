"""What a pass is worth once the scenario has already broken.

SC-901 reported "22 of 24 steps passed" for a run in which the signup never
happened: step 6 failed to pick a school, no account was created, and the
eighteen steps after it ran against a login screen and passed as they went. The
tally was arithmetically correct and told the reader the opposite of the truth.

These tests pin the rule and, more importantly, the two properties that made it
the chosen fix:

* a post-failure pass is recorded as UNVERIFIED rather than counted,
* and it **cannot turn a green run red** -- the demotion only fires after a
  failure, and a failure has already set the exit code. The alternative fix
  (raising assert failures to aborts) would have gone red on scenarios that
  pass today in other people's repositories.

The wiring tests at the bottom check the source rather than driving the CLI.
`aat run` cannot be reached end-to-end from a test without going through the
`/dev/tty` approval gate, and the project's security rules forbid bypassing it.
What they can establish is that both commands call the shared rule, which is
the thing that was missing -- the defect was an absence, so an absence is what
they are aimed at. They cannot prove the call happens at the right moment; the
integration coverage for that lives with the executor.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aat.core.models import StepResult, StepStatus
from aat.core.tally import demote_if_flow_broken, unverified_note

SRC = Path(__file__).resolve().parents[2] / "src" / "aat"


def _step(number: int, status: StepStatus, *, error: str | None = None) -> StepResult:
    return StepResult(
        step=number,
        action="find_and_click",
        description=f"Step {number}",
        status=status,
        elapsed_ms=1,
        error_message=error,
    )


class TestDemotion:
    def test_a_pass_after_a_failure_is_not_counted(self) -> None:
        result = demote_if_flow_broken(_step(7, StepStatus.PASSED), broke_at=6)
        assert result.status == StepStatus.UNVERIFIED

    def test_a_pass_before_any_failure_is_untouched(self) -> None:
        original = _step(3, StepStatus.PASSED)
        assert demote_if_flow_broken(original, broke_at=None) is original

    def test_the_note_names_the_step_that_broke(self) -> None:
        """Without the number the reader has to go find the failure themselves."""
        result = demote_if_flow_broken(_step(7, StepStatus.PASSED), broke_at=6)
        assert result.error_message is not None
        assert "step 6" in result.error_message

    def test_the_note_survives_not_knowing_which_step_broke(self) -> None:
        assert "an earlier step" in unverified_note(None)

    @pytest.mark.parametrize(
        "status",
        [StepStatus.FAILED, StepStatus.ERROR, StepStatus.WARNING, StepStatus.SKIPPED],
    )
    def test_only_passes_are_demoted(self, status: StepStatus) -> None:
        """A failure after a failure is still a failure, and a warning already
        says it verified nothing. Rewriting either would lose information."""
        original = _step(7, status, error="the original reason")
        assert demote_if_flow_broken(original, broke_at=6) is original

    def test_an_existing_error_message_is_not_overwritten_on_a_failure(self) -> None:
        """The same claim from the reader's side: the cause of the failure is
        still there to read after the sweep has run over it."""
        original = _step(7, StepStatus.FAILED, error="Text 'x' not visible on page")
        assert (
            demote_if_flow_broken(original, broke_at=6).error_message
            == "Text 'x' not visible on page"
        )

    def test_demotion_does_not_mutate_its_input(self) -> None:
        """The caller appends the returned result to the report. If the rule
        edited in place, a caller that kept the original would silently get the
        rewritten one."""
        original = _step(7, StepStatus.PASSED)
        demote_if_flow_broken(original, broke_at=6)
        assert original.status == StepStatus.PASSED
        assert original.error_message is None


class TestCannotTurnGreenRed:
    """The property the chosen fix was chosen for."""

    def test_unverified_requires_a_prior_failure(self) -> None:
        """Stated as a loop over every status: no input the rule could be given
        comes back UNVERIFIED while `broke_at` is None, so a run with no
        failures cannot acquire an UNVERIFIED step, so its exit code cannot
        change. UNVERIFIED itself is excluded because nothing produces one to
        feed in -- the rule is the only thing that makes them.
        """
        for status in StepStatus:
            if status == StepStatus.UNVERIFIED:
                continue
            result = demote_if_flow_broken(_step(1, status), broke_at=None)
            assert result.status != StepStatus.UNVERIFIED, status


class TestBothCommandsUseTheSameRule:
    @pytest.mark.parametrize(
        "path",
        ["cli/commands/run_cmd.py", "core/loop.py"],
    )
    def test_the_runner_calls_the_shared_rule(self, path: str) -> None:
        source = (SRC / path).read_text(encoding="utf-8")
        assert "demote_if_flow_broken" in source, (
            f"{path} does not apply the post-failure rule; a scenario would "
            "report a different tally depending on which command ran it"
        )

    def test_the_classifier_ignores_unverified_steps(self) -> None:
        """`aat loop` asks the AI why the run failed. Handing it a step whose
        only message is "not counted" makes it diagnose the wrong problem."""
        source = (SRC / "core" / "loop.py").read_text(encoding="utf-8")
        assert "StepStatus.UNVERIFIED," in source
