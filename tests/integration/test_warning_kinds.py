"""A warning's closing advice has to be about that warning.

SC-913 finished with exactly one warning: a ``find_and_type`` step whose target
turned out to be a ``<select>``, which the step message explained precisely,
naming the option the dropdown was now showing and the action to use instead.
Under it the run summary printed, as it printed under every warning:

    A click that moves nothing usually means it missed its target — check the
    screenshots for those steps. An expectation written as a sentence was never
    checked at all — give it a type and a value.

Neither sentence was true of that run. The reader was sent to look for a dead
click and a prose expectation, found neither, and had to work out that the
advice was boilerplate. A summary that says the same thing whatever happened
is a summary nobody can trust the next time it says something specific.

Two things are measured here, and they are different claims:

* **The tag.** Every producer of a ``WARNING`` attaches the kind at the point
  it raises it, against a real browser, because what a ``<select>`` does to a
  keystroke is a fact about Chromium. Classifying afterwards by matching the
  message text would work today and break the next time someone improves the
  wording -- quietly, still printing confident advice about the wrong thing.

* **The selection.** Given a set of kinds, only the matching notes come out.
  That is a pure function and is tested as one, including the case this file
  exists for: a run whose only warning is a ``<select>`` must print neither the
  dead-click note nor the prose note.

The last class is the other direction. Narrowing what gets printed is the kind
of change that ends in printing nothing, so a run that really does contain a
dead click must still say so.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from aat.core.models import (
    WARNING_NOTES,
    ActionType,
    EngineConfig,
    MatchMethod,
    MatchResult,
    StepConfig,
    StepStatus,
    TargetSpec,
    WarningKind,
    warning_notes,
)
from aat.engine.comparator import Comparator
from aat.engine.executor import StepExecutor
from aat.engine.humanizer import Humanizer
from aat.engine.waiter import Waiter
from aat.engine.web import WebEngine
from tests.fixtures.signup_form_server import signup_form_server


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    with signup_form_server() as url:
        yield url


@pytest.fixture()
async def engine() -> AsyncIterator[WebEngine]:
    eng = WebEngine(EngineConfig(headless=True, speed="fast", screenshot_mode="off"))
    try:
        await eng.start()
    except Exception as e:  # noqa: BLE001 — environment without the browser binary
        pytest.skip(f"Chromium unavailable: {e}")
    try:
        yield eng
    finally:
        await eng.stop()


@pytest.fixture()
def executor(engine: WebEngine, tmp_path: Path) -> StepExecutor:
    # Stubbed to find nothing, so every warning here comes from the DOM route
    # under test rather than from a matcher that happened to succeed.
    matcher = AsyncMock()
    matcher.find = AsyncMock(
        return_value=MatchResult(
            found=False, x=0, y=0, confidence=0.0, method=MatchMethod.TEMPLATE
        )
    )
    return StepExecutor(engine, matcher, Humanizer(), Waiter(), Comparator(), tmp_path)


def _type_into(selector: str, text: str) -> StepConfig:
    return StepConfig(
        step=6,
        action=ActionType.FIND_AND_TYPE,
        target=TargetSpec(selector=selector),
        value=text,
        description=f"Fill {selector}",
        humanize=False,
    )


def _click(selector: str) -> StepConfig:
    return StepConfig(
        step=4,
        action=ActionType.FIND_AND_CLICK,
        target=TargetSpec(selector=selector),
        description=f"Click {selector}",
    )


def _type_by_text(label: str, text: str) -> StepConfig:
    """Name the field the way the SC-911 scenario did -- by label, not selector.

    The mis-landing defect only exists on this route: a step that names its
    target with a selector goes straight there and cannot land anywhere else.
    """
    return StepConfig(
        step=6,
        action=ActionType.FIND_AND_TYPE,
        target=TargetSpec(text=label),
        value=text,
        description=f"Fill the field labelled {label}",
        humanize=False,
    )


class TestTheTagComesFromTheProducer:
    """Each warning carries its kind out of the place that raised it."""

    async def test_select_typing_is_tagged_typed_value(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """SC-913's only warning, and the one that drew the wrong advice."""
        await engine.navigate(f"{base_url}/signup")

        result = await executor.execute_step(_type_into("#school", "2"))

        assert result.status == StepStatus.WARNING
        assert result.warning_kind == WarningKind.TYPED_VALUE

    async def test_readonly_field_is_tagged_typed_value(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """A second value rule, to show the tag belongs to the rule family.

        ``<select>`` and ``readonly`` are different checks reaching the same
        conclusion, and a tag attached to only one of them would leave the
        other silent -- the safe direction, but still a gap.
        """
        await engine.navigate(f"{base_url}/signup")

        result = await executor.execute_step(_type_into("#code", "ABCD"))

        assert result.status == StepStatus.WARNING
        assert result.warning_kind == WarningKind.TYPED_VALUE

    async def test_text_in_the_wrong_field_is_tagged_typed_destination(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """AAT-124's warning is a different kind and needs different advice.

        "The field refused the text" and "the text went into another field"
        are both typing warnings and lead the reader to opposite places: one
        to the element's type, the other to how the step names its target.
        """
        await engine.navigate(f"{base_url}/overlaid")

        result = await executor.execute_step(_type_by_text("이름", "에이더블유티"))

        assert result.status == StepStatus.WARNING
        assert result.warning_kind == WarningKind.TYPED_DESTINATION

    async def test_a_click_that_moves_nothing_is_tagged_click_no_effect(
        self, executor: StepExecutor, engine: WebEngine, base_url: str
    ) -> None:
        """The one kind whose producer sets no reason string at all.

        It is tagged by falling back rather than by being named, which is the
        opposite arrangement from the typing warnings and so the easiest one to
        get wrong. ``#notice`` is a paragraph: no listener, and not focusable,
        so not even a focus ring moves.
        """
        await engine.navigate(f"{base_url}/plain")

        result = await executor.execute_step(_click("#notice"))

        assert result.status == StepStatus.WARNING
        assert result.warning_kind == WarningKind.CLICK_NO_EFFECT


class TestTheNotesFollowTheKinds:
    """The selection itself: only what happened gets explained."""

    def test_a_select_only_run_says_nothing_about_clicks_or_prose(self) -> None:
        """The reported complaint, stated as the assertion it is."""
        notes = warning_notes({WarningKind.TYPED_VALUE})

        assert notes == [WARNING_NOTES[WarningKind.TYPED_VALUE]]
        joined = " ".join(notes)
        assert "missed its target" not in joined
        assert "written as a sentence" not in joined

    def test_a_dead_click_still_gets_its_advice(self) -> None:
        """The other direction: narrowing must not end in printing nothing."""
        notes = warning_notes({WarningKind.CLICK_NO_EFFECT})

        assert notes == [WARNING_NOTES[WarningKind.CLICK_NO_EFFECT]]
        assert "missed its target" in notes[0]

    def test_two_kinds_in_one_run_get_both_notes(self) -> None:
        notes = warning_notes({WarningKind.CLICK_NO_EFFECT, WarningKind.PROSE_EXPECTATION})

        assert len(notes) == 2
        assert WARNING_NOTES[WarningKind.CLICK_NO_EFFECT] in notes
        assert WARNING_NOTES[WarningKind.PROSE_EXPECTATION] in notes

    def test_order_is_the_enum_order_not_the_set_order(self) -> None:
        """Sets have no order, and a summary that reshuffles looks unstable."""
        forwards = warning_notes([WarningKind.CLICK_NO_EFFECT, WarningKind.PROSE_EXPECTATION])
        backwards = warning_notes([WarningKind.PROSE_EXPECTATION, WarningKind.CLICK_NO_EFFECT])

        assert forwards == backwards

    def test_no_warnings_means_no_notes(self) -> None:
        assert warning_notes(set()) == []

    def test_every_kind_has_a_note(self) -> None:
        """A kind added without an explanation would be silently unexplained.

        Silence is the right default for an *untagged* warning, but a kind
        someone deliberately defined and then forgot to describe is an
        oversight, and nothing else in the repository would notice it.
        """
        for kind in WarningKind:
            assert kind in WARNING_NOTES, kind


class TestTheSummaryIsWiredToTheSelection:
    """``aat run`` must use the selection rather than its own fixed text.

    The end-to-end route cannot be driven from a test: it passes the approval
    gate, which reads ``/dev/tty``, and bypassing that gate is forbidden. So
    this checks the wiring, which is where the defect was -- the notes existed
    nowhere and the summary printed two hard-coded sentences.
    """

    def test_run_cmd_calls_warning_notes(self) -> None:
        source = Path("src/aat/cli/commands/run_cmd.py").read_text(encoding="utf-8")

        assert "warning_notes(warning_kinds)" in source

    def test_run_cmd_no_longer_prints_the_fixed_pair(self) -> None:
        """The exact sentences from the report must be gone from the summary.

        Both now live in ``WARNING_NOTES`` under their own kinds; a copy left
        behind in the summary would print unconditionally again and nothing
        above would go red.
        """
        source = Path("src/aat/cli/commands/run_cmd.py").read_text(encoding="utf-8")

        assert "A click that moves nothing" not in source
        assert "An expectation written as a sentence" not in source

    def test_run_cmd_collects_kinds_from_both_intake_sites(self) -> None:
        """Step warnings and scenario-expectation warnings arrive separately.

        They are appended in two different loops, and tagging only one of them
        would leave prose expectations unexplained -- which is the half of the
        old message that was right for SC-911.
        """
        source = Path("src/aat/cli/commands/run_cmd.py").read_text(encoding="utf-8")

        assert source.count("warning_kinds.add(") == 2
