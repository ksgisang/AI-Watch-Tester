"""What a pass is worth once the scenario has already broken.

A scenario is a sequence, not a bag of independent checks. SC-901 signed up,
then logged in, then looked for the approval notice. When step 6 failed to
pick a school, no account was created -- and the eighteen steps after it went
on running against a login screen, passing as they went. The run reported
"22 of 24 passed" for an execution in which the thing under test never
happened once. The reader of that line has no way to tell.

So a ``PASSED`` that occurs after a failure in the same scenario is recorded as
:attr:`~aat.core.models.StepStatus.UNVERIFIED`. The step did run and it did not
error; what it cannot do is stand as evidence, because the state it was acting
on is not the state the scenario describes.

Two properties are deliberate:

* **It cannot turn a green run red.** The demotion only fires after a failure,
  and a failure has already set the exit code to 1. Raising assert failures to
  aborts (the other way to fix the inflated tally) would have gone red on
  scenarios that pass today, in other people's repositories.
* **One rule, every surface.** Because the status itself changes, the console
  line, the Markdown table, the PDF table, ``last_run.json`` and
  ``TestResult.passed_steps`` all agree without each of them being taught the
  rule separately.

This lives in ``core`` rather than beside either caller: ``aat run``
(``cli/commands/run_cmd.py``) and ``aat loop`` (``core/loop.py``) both need it,
and ``core`` is not allowed to import from ``cli``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aat.core.models import StepStatus

if TYPE_CHECKING:
    from aat.core.models import StepResult


def unverified_note(broke_at: int | None) -> str:
    """Why this step's pass was not counted, in the words the reader needs."""
    where = f"step {broke_at}" if broke_at is not None else "an earlier step"
    return (
        f"not counted: {where} had already failed, so this ran on a screen "
        "the scenario never reached — its pass is not evidence"
    )


def demote_if_flow_broken(result: StepResult, broke_at: int | None) -> StepResult:
    """Record a post-failure pass as UNVERIFIED instead of PASSED.

    ``broke_at`` is the step number of the first failure in this scenario, or
    ``None`` while nothing has failed yet. Anything other than a ``PASSED``
    result is returned untouched: a failure after a failure is still a failure,
    and a warning still verified nothing, which is what a warning already says.
    """
    if broke_at is None or result.status != StepStatus.PASSED:
        return result
    return result.model_copy(
        update={
            "status": StepStatus.UNVERIFIED,
            "error_message": unverified_note(broke_at),
        }
    )
