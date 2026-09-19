"""Remembered coordinates, against a real browser.

The defect these tests pin down came out of a nine-scenario run against a live
service: AWT remembered where a button had been, used that memory ahead of the
selector the scenario had written down, clicked empty space on the next page,
and reported the step as PASSED. The failure only surfaced several steps later,
and it looked like a defect in the product rather than in the tool.

Positive — what must keep working:
  * a target with no selector is still found and remembered,
  * the memory is really used on the next run (proved by disabling every other
    way of finding the element),
  * a stable input field is still typed into by memory alone.

Negative — what must never happen again:
  * a remembered position must not beat a selector the scenario named,
  * a click that moves nothing must not be reported as PASSED,
  * a position that stopped working must lose confidence and be forgotten,
  * `learn_coords=False` and step-level `learn: false` must neither read the
    memory nor write to it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from aat.core.models import (
    ActionType,
    EngineConfig,
    MatchMethod,
    MatchResult,
    StepConfig,
    StepStatus,
    TargetSpec,
)
from aat.engine.comparator import Comparator
from aat.engine.executor import StepExecutor
from aat.engine.humanizer import Humanizer
from aat.engine.waiter import Waiter
from aat.engine.web import WebEngine
from aat.learning.store import LearnedStore
from tests.fixtures.coord_drift_server import coord_drift_server

# Spacer heights: the same button, high on the page and far down it.
SHORT_PAGE = 40
TALL_PAGE = 900


@pytest.fixture(scope="module")
def quiz_url() -> Iterator[str]:
    """Local page whose button height follows the content above it."""
    with coord_drift_server() as base_url:
        yield base_url


@pytest.fixture()
async def engine() -> AsyncIterator[WebEngine]:
    """Real headless Chromium. Skips the test if the browser is not installed."""
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
def store(tmp_path: Path) -> LearnedStore:
    return LearnedStore(tmp_path / "learned.db")


def _executor(
    engine: WebEngine,
    store: LearnedStore,
    tmp_path: Path,
    *,
    learn_coords: bool = True,
) -> StepExecutor:
    """Executor whose matcher finds nothing.

    Image matching is out of scope here, and a matcher that always "finds"
    something would hide a fallback firing when it should not have: any step
    that reaches the matcher fails loudly instead.
    """
    matcher = AsyncMock()
    matcher.find = AsyncMock(
        return_value=MatchResult(
            found=False, x=0, y=0, confidence=0.0, method=MatchMethod.TEMPLATE
        )
    )
    return StepExecutor(
        engine,
        matcher,
        Humanizer(),
        Waiter(),
        Comparator(),
        tmp_path,
        learned_store=store,
        learn_coords=learn_coords,
    )


def _click_grade(
    *, selector: str | None = None, learn: bool | None = None, step: int = 1
) -> StepConfig:
    return StepConfig(
        step=step,
        action=ActionType.FIND_AND_CLICK,
        target=TargetSpec(text="Grade it", selector=selector),
        description="Press the grade button",
        learn=learn,
    )


def _type_nickname(*, selector: str | None = None, step: int = 1) -> StepConfig:
    return StepConfig(
        step=step,
        action=ActionType.FIND_AND_TYPE,
        target=TargetSpec(text="Nickname", selector=selector),
        value="haneul",
        description="Fill in the nickname field",
    )


async def _open(engine: WebEngine, quiz_url: str, pad: int) -> None:
    await engine.navigate(f"{quiz_url}/?pad={pad}")


async def _clicks(engine: WebEngine) -> list[str]:
    """What the page itself saw being clicked, in order."""
    result: list[str] = await engine.page.evaluate("window.__clicks")
    return result


async def _panel_shown(engine: WebEngine) -> bool:
    shown: bool = await engine.page.evaluate(
        "getComputedStyle(document.getElementById('panel')).display !== 'none'"
    )
    return shown


async def _field(engine: WebEngine, element_id: str) -> str:
    value: str = await engine.page.evaluate(f"document.getElementById('{element_id}').value")
    return value


async def _box(engine: WebEngine, element_id: str) -> dict[str, float]:
    box: dict[str, float] = await engine.page.evaluate(
        f"(() => {{ const r = document.getElementById('{element_id}')"
        ".getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; })()"
    )
    return box


def _memory(store: LearnedStore, name: str) -> dict[str, Any] | None:
    for row in store.list_state_coords():
        if row["target_name"] == name:
            return row
    return None


def _blind_the_search(engine: WebEngine, executor: StepExecutor) -> None:
    """Disable every way of locating an element except the remembered position.

    After this, a step that still clicks the right thing can only have done it
    from memory — which is what the positive tests need to prove.
    """
    engine.find_text_position = AsyncMock(return_value=None)  # type: ignore[method-assign]
    engine.force_click_by_text = AsyncMock(return_value=False)  # type: ignore[method-assign]
    executor._find_input_field = AsyncMock(return_value=None)  # type: ignore[method-assign]


class TestLearningStillWorks:
    """Positive: remembering positions is still useful, and still happens."""

    async def test_target_without_selector_is_found_and_remembered(
        self, engine: WebEngine, store: LearnedStore, quiz_url: str, tmp_path: Path
    ) -> None:
        executor = _executor(engine, store, tmp_path)
        await _open(engine, quiz_url, SHORT_PAGE)

        result = await executor.execute_step(_click_grade())

        assert result.status == StepStatus.PASSED, result.error_message
        assert await _panel_shown(engine)

        remembered = _memory(store, "Grade it")
        assert remembered is not None, "a click that worked was not remembered"
        box = await _box(engine, "grade")
        assert box["x"] <= remembered["correct_x"] <= box["x"] + box["w"]
        assert box["y"] <= remembered["correct_y"] <= box["y"] + box["h"]

    async def test_second_run_clicks_from_memory_alone(
        self, engine: WebEngine, store: LearnedStore, quiz_url: str, tmp_path: Path
    ) -> None:
        """The remembered position does the work when nothing else can find it."""
        executor = _executor(engine, store, tmp_path)
        await _open(engine, quiz_url, SHORT_PAGE)
        first = await executor.execute_step(_click_grade())
        assert first.status == StepStatus.PASSED, first.error_message

        await _open(engine, quiz_url, SHORT_PAGE)  # fresh page, same layout
        _blind_the_search(engine, executor)

        second = await executor.execute_step(_click_grade(step=2))

        assert second.status == StepStatus.PASSED, second.error_message
        assert await _panel_shown(engine), "the remembered position did not hit the button"

    async def test_stable_input_is_typed_into_from_memory(
        self, engine: WebEngine, store: LearnedStore, quiz_url: str, tmp_path: Path
    ) -> None:
        """The case learning was worth having: a login field that never moves."""
        executor = _executor(engine, store, tmp_path)
        await _open(engine, quiz_url, SHORT_PAGE)
        first = await executor.execute_step(_type_nickname())
        assert first.status == StepStatus.PASSED, first.error_message
        assert await _field(engine, "nickname") == "haneul"
        assert _memory(store, "Nickname") is not None

        await _open(engine, quiz_url, SHORT_PAGE)
        _blind_the_search(engine, executor)

        second = await executor.execute_step(_type_nickname(step=2))

        assert second.status == StepStatus.PASSED, second.error_message
        assert await _field(engine, "nickname") == "haneul"


class TestSelectorBeatsMemory:
    """Negative: what the scenario wrote down outranks what the tool guessed."""

    async def test_selector_wins_over_a_stale_position(
        self, engine: WebEngine, store: LearnedStore, quiz_url: str, tmp_path: Path
    ) -> None:
        """The field defect: learn on a short page, run against a tall one."""
        executor = _executor(engine, store, tmp_path)
        await _open(engine, quiz_url, SHORT_PAGE)
        assert (await executor.execute_step(_click_grade())).status == StepStatus.PASSED
        learned_y = (_memory(store, "Grade it") or {})["correct_y"]

        await _open(engine, quiz_url, TALL_PAGE)
        moved_to = await _box(engine, "grade")
        assert moved_to["y"] > learned_y + 100, "fixture did not actually move the button"
        _blind_the_search(engine, executor)  # only selector or memory can act

        result = await executor.execute_step(_click_grade(selector="#grade", step=2))

        assert result.status == StepStatus.PASSED, result.error_message
        assert await _panel_shown(engine), "the selector did not reach the button"
        assert "grade" in await _clicks(engine)

    async def test_planted_position_is_ignored_when_a_selector_names_the_field(
        self, engine: WebEngine, store: LearnedStore, quiz_url: str, tmp_path: Path
    ) -> None:
        """A wrong memory pointing at the neighbouring field must not be used."""
        executor = _executor(engine, store, tmp_path)
        await _open(engine, quiz_url, SHORT_PAGE)
        note = await _box(engine, "note")
        store.save_state_coords(
            "Nickname", "normal", int(note["x"] + note["w"] / 2), int(note["y"] + note["h"] / 2)
        )

        result = await executor.execute_step(_type_nickname(selector="#nickname"))

        assert result.status == StepStatus.PASSED, result.error_message
        assert await _field(engine, "nickname") == "haneul"
        assert await _field(engine, "note") == "", "the planted position was used anyway"

    async def test_planted_position_is_used_when_no_selector_is_given(
        self, engine: WebEngine, store: LearnedStore, quiz_url: str, tmp_path: Path
    ) -> None:
        """Control for the test above: without a selector the memory does act.

        Without this, the previous test would also pass if remembered
        coordinates had simply stopped working altogether.
        """
        executor = _executor(engine, store, tmp_path)
        await _open(engine, quiz_url, SHORT_PAGE)
        note = await _box(engine, "note")
        store.save_state_coords(
            "Nickname", "normal", int(note["x"] + note["w"] / 2), int(note["y"] + note["h"] / 2)
        )

        result = await executor.execute_step(_type_nickname())

        assert result.status == StepStatus.PASSED, result.error_message
        assert await _field(engine, "note") == "haneul", "the memory was not consulted"


class TestClickWithNoEffect:
    """Negative: a click that moved nothing is not a pass."""

    async def test_stale_position_click_is_reported_as_warning(
        self, engine: WebEngine, store: LearnedStore, quiz_url: str, tmp_path: Path
    ) -> None:
        executor = _executor(engine, store, tmp_path)
        await _open(engine, quiz_url, SHORT_PAGE)
        assert (await executor.execute_step(_click_grade())).status == StepStatus.PASSED

        await _open(engine, quiz_url, TALL_PAGE)  # the button moved out from under it

        result = await executor.execute_step(_click_grade(step=2))

        assert result.status == StepStatus.WARNING, (
            f"a click into empty space came out {result.status.value}"
        )
        assert result.status != StepStatus.PASSED
        assert "no visible change" in (result.error_message or "")
        assert not await _panel_shown(engine)
        assert "grade" not in await _clicks(engine)

    async def test_position_that_stopped_working_loses_confidence(
        self, engine: WebEngine, store: LearnedStore, quiz_url: str, tmp_path: Path
    ) -> None:
        executor = _executor(engine, store, tmp_path)
        await _open(engine, quiz_url, SHORT_PAGE)
        assert (await executor.execute_step(_click_grade())).status == StepStatus.PASSED
        before = (_memory(store, "Grade it") or {})["confidence"]

        await _open(engine, quiz_url, TALL_PAGE)
        await executor.execute_step(_click_grade(step=2))

        after = _memory(store, "Grade it")
        assert after is not None  # one miss decays it; it is not yet below the floor
        assert after["confidence"] < before, "a position that missed kept its confidence"

    async def test_a_position_that_keeps_missing_is_forgotten(
        self, engine: WebEngine, store: LearnedStore, quiz_url: str, tmp_path: Path
    ) -> None:
        """Planted just above the floor, so a single miss drops it out of use."""
        executor = _executor(engine, store, tmp_path)
        await _open(engine, quiz_url, SHORT_PAGE)
        store.save_state_coords("Grade it", "normal", 5, 5, confidence=0.7)

        result = await executor.execute_step(_click_grade())

        assert result.status == StepStatus.WARNING, result.error_message
        assert store.find_state_coords("Grade it", "normal") is None, (
            "a position that does nothing is still being offered"
        )

    async def test_a_miss_is_never_learned(
        self, engine: WebEngine, store: LearnedStore, quiz_url: str, tmp_path: Path
    ) -> None:
        """Clicking empty space must not teach the tool that empty space works."""
        executor = _executor(engine, store, tmp_path)
        await _open(engine, quiz_url, SHORT_PAGE)
        store.save_state_coords("Grade it", "normal", 5, 5, confidence=0.7)

        await executor.execute_step(_click_grade())

        assert _memory(store, "Grade it") is None


class TestLearningCanBeTurnedOff:
    """Negative: the switches must stop both reading and writing."""

    async def test_no_learn_run_neither_reads_nor_writes(
        self, engine: WebEngine, store: LearnedStore, quiz_url: str, tmp_path: Path
    ) -> None:
        executor = _executor(engine, store, tmp_path, learn_coords=False)
        await _open(engine, quiz_url, SHORT_PAGE)
        note = await _box(engine, "note")
        store.save_state_coords(
            "Nickname", "normal", int(note["x"] + note["w"] / 2), int(note["y"] + note["h"] / 2)
        )

        result = await executor.execute_step(_type_nickname())

        assert result.status == StepStatus.PASSED, result.error_message
        assert await _field(engine, "nickname") == "haneul", "the memory was read anyway"
        assert await _field(engine, "note") == ""
        assert _memory(store, "Grade it") is None

        await _open(engine, quiz_url, SHORT_PAGE)
        assert (await executor.execute_step(_click_grade(step=2))).status == StepStatus.PASSED
        assert _memory(store, "Grade it") is None, "--no-learn still wrote to the store"

    async def test_step_level_learn_false_stores_nothing(
        self, engine: WebEngine, store: LearnedStore, quiz_url: str, tmp_path: Path
    ) -> None:
        """For modal buttons and choice overlays: this target is not learnable."""
        executor = _executor(engine, store, tmp_path)
        await _open(engine, quiz_url, SHORT_PAGE)

        result = await executor.execute_step(_click_grade(learn=False))

        assert result.status == StepStatus.PASSED, result.error_message
        assert await _panel_shown(engine)
        assert _memory(store, "Grade it") is None, "a step marked learn: false was learned"
