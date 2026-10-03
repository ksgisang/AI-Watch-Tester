"""Self-healing, against a real browser.

Everything else about healing is tested against mock pages, and a mock page can
be made to agree with any claim. The claim here is the product's differentiator,
so it is worth measuring the way §5 measured its absence: open real Chromium,
rename the selector the scenario names, and see whether a picture banked before
the rename still finds the button.

The page is styled by class and identified by id, so the rename changes the
selector and not one pixel (`tests/fixtures/selector_rename_server.py`). That is
the ordinary shape of the failure: a component is renamed and a suite of
selector-based scenarios goes red overnight.

Positive — what must work:
  * a run banks a picture of what the DOM found, and a later run whose selector
    no longer matches finds the element from that picture,
  * the healed click lands on the button itself, which the page confirms,
  * `--fast` heals too, since it is the mode every surface recommends.

Negative — what must never happen:
  * with nothing banked, the renamed selector must simply fail (otherwise the
    positive result above proves nothing),
  * a picture banked for one host must not answer for another,
  * a button that no longer looks the same must not be healed from an old
    picture — a confident click on the wrong element is the AAT-109 failure.

Two things only a real browser could have shown, both about the *other* thing a
successful run leaves behind — the position it remembered:
  * healing was dead code. A remembered position was consulted first, and since
    run one both banks a picture and learns a position, run two passed on the
    position and never reached the picture. Every mock-based test was green.
    Fixed by ordering evidence before guess (executor, Priority 0.9 then 1.0).
  * remembered positions were not scoped by host, unlike pictures. Recorded
    below as a strict xfail, because a comment does not run -- and the marker
    is what announced the fix when AAT-115 scoped them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from aat.core.models import (
    ActionType,
    EngineConfig,
    MatchingConfig,
    MatchMethod,
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
from aat.matchers import template_store
from aat.matchers.hybrid import HybridMatcher
from aat.matchers.template import TemplateMatcher
from tests.fixtures.selector_rename_server import selector_rename_server

#: The selector the scenario was written against, and the id after the rename.
OLD_ID = "grade"
NEW_ID = "grade-v2"


@pytest.fixture(scope="module")
def quiz_url() -> Iterator[str]:
    """Local page whose button id — and only its id — follows the query."""
    with selector_rename_server() as base_url:
        yield base_url


async def _browser(*, fast: bool) -> WebEngine:
    engine = WebEngine(
        EngineConfig(headless=True, speed="fast", screenshot_mode="off", fast_mode=fast)
    )
    try:
        await engine.start()
    except Exception as e:  # noqa: BLE001 — environment without the browser binary
        pytest.skip(f"Chromium unavailable: {e}")
    return engine


@pytest.fixture()
async def engine() -> AsyncIterator[WebEngine]:
    """Real headless Chromium, full matcher chain."""
    eng = await _browser(fast=False)
    try:
        yield eng
    finally:
        await eng.stop()


@pytest.fixture()
async def fast_engine() -> AsyncIterator[WebEngine]:
    """Real headless Chromium in the mode every surface recommends."""
    eng = await _browser(fast=True)
    try:
        yield eng
    finally:
        await eng.stop()


def _executor(engine: WebEngine, tmp_path: Path, *, remember: bool = True) -> StepExecutor:
    """Executor with a real template matcher — the thing under test.

    A new executor per run on purpose: nothing may be carried between runs in
    memory, because the store on disk is the only channel healing is allowed to
    use. The scenario file and the store are all a second run would really have.

    ``remember=False`` drops the learned-coordinate store. Use it for the tests
    that ask what the *picture* does, because a remembered position is the other
    thing a successful run leaves behind and it answers first: with it in place,
    a step can pass without the picture being consulted at all, and the test
    would be measuring the wrong fallback.
    """
    return StepExecutor(
        engine,
        HybridMatcher([TemplateMatcher(MatchingConfig())]),
        Humanizer(),
        Waiter(),
        Comparator(),
        tmp_path,
        learned_store=LearnedStore(tmp_path / "learned.db") if remember else None,
    )


def _click_grade() -> StepConfig:
    """A selector-only step: the shape healing exists for.

    No ``text``, deliberately. A caption would let Playwright's text search find
    the renamed button through the DOM, and then the picture would never be
    consulted — the test would pass while proving nothing.
    """
    return StepConfig(
        step=1,
        action=ActionType.FIND_AND_CLICK,
        target=TargetSpec(selector=f"#{OLD_ID}"),
        description="Press the grade button",
    )


async def _open(engine: WebEngine, base_url: str, button_id: str, text: str = "") -> None:
    query = f"/?id={button_id}"
    if text:
        query += f"&text={text}"
    await engine.navigate(f"{base_url}{query}")


async def _clicks(engine: WebEngine) -> list[str]:
    """What the page itself saw being clicked, in order."""
    seen: list[str] = await engine.page.evaluate("window.__clicks")
    return seen


async def _panel_shown(engine: WebEngine) -> bool:
    shown: bool = await engine.page.evaluate(
        "getComputedStyle(document.getElementById('panel')).display !== 'none'"
    )
    return shown


def _banked(host_url: str) -> list[str]:
    """Names filed under the host in `host_url`."""
    scope = template_store.scope_for(host_url)
    return [entry.target for entry in template_store.inventory(scope)]


@pytest.mark.asyncio
async def test_a_run_banks_a_picture_of_what_the_dom_found(
    engine: WebEngine, quiz_url: str, tmp_path: Path
) -> None:
    """The precondition. Healing can only ever be as good as what was banked."""
    await _open(engine, quiz_url, OLD_ID)

    result = await _executor(engine, tmp_path).execute_step(_click_grade())

    assert result.status == StepStatus.PASSED
    assert result.match_result is not None
    assert result.match_result.method == MatchMethod.PLAYWRIGHT
    assert f"#{OLD_ID}" in _banked(quiz_url), "the selector-only step must bank under its selector"


@pytest.mark.asyncio
async def test_a_renamed_selector_is_healed_by_the_earlier_picture(
    engine: WebEngine, quiz_url: str, tmp_path: Path
) -> None:
    """The differentiator, end to end, in a real browser.

    Run one finds the button through the DOM and banks its picture. Then the
    button is renamed and the scenario is left untouched, so the DOM lookup has
    nothing to return. The step still passes, and the page confirms the click
    landed on the button rather than on background.
    """
    await _open(engine, quiz_url, OLD_ID)
    assert (await _executor(engine, tmp_path).execute_step(_click_grade())).status == (
        StepStatus.PASSED
    )

    await _open(engine, quiz_url, NEW_ID)  # the rename; same pixels, new id

    healed = await _executor(engine, tmp_path).execute_step(_click_grade())

    assert healed.status == StepStatus.PASSED
    assert healed.match_result is not None
    assert healed.match_result.method == MatchMethod.SAVED_TEMPLATE
    assert NEW_ID in await _clicks(engine), "the heal must land on the button, not near it"
    assert await _panel_shown(engine), "the page must react, or nothing was really pressed"


@pytest.mark.asyncio
async def test_fast_mode_heals_in_a_real_browser(
    fast_engine: WebEngine, quiz_url: str, tmp_path: Path
) -> None:
    """`aat run --skill-mode --fast` is what the docs, the skill and MCP all run.

    It used to raise before anything visual happened, so the one command users
    were told to use was the one command that could never heal.
    """
    await _open(fast_engine, quiz_url, OLD_ID)
    assert (await _executor(fast_engine, tmp_path).execute_step(_click_grade())).status == (
        StepStatus.PASSED
    )

    await _open(fast_engine, quiz_url, NEW_ID)

    healed = await _executor(fast_engine, tmp_path).execute_step(_click_grade())

    assert healed.status == StepStatus.PASSED
    assert healed.match_result is not None
    assert healed.match_result.method == MatchMethod.SAVED_TEMPLATE
    assert NEW_ID in await _clicks(fast_engine)


@pytest.mark.asyncio
async def test_without_a_banked_picture_the_rename_simply_fails(
    engine: WebEngine, quiz_url: str, tmp_path: Path
) -> None:
    """The control. Without this, the test above could be passing for any reason."""
    await _open(engine, quiz_url, NEW_ID)

    result = await _executor(engine, tmp_path).execute_step(_click_grade())

    assert result.status == StepStatus.FAILED
    assert await _clicks(engine) == [], "nothing should have been clicked"
    assert not await _panel_shown(engine)


@pytest.mark.asyncio
async def test_a_picture_banked_for_another_host_does_not_heal(
    engine: WebEngine, quiz_url: str, tmp_path: Path
) -> None:
    """Same bytes, same port, different host — and that has to be enough to refuse.

    `127.0.0.1` and `localhost` serve the identical page here, which makes this
    the strictest form of the question: the picture would match perfectly. It is
    still refused, because losing a heal costs one failed step while a wrong one
    reports a test that never ran.
    """
    loopback = quiz_url
    by_name = quiz_url.replace("127.0.0.1", "localhost")

    await _open(engine, loopback, OLD_ID)
    assert (
        await _executor(engine, tmp_path, remember=False).execute_step(_click_grade())
    ).status == (StepStatus.PASSED)
    assert _banked(loopback), "the picture must exist for the refusal to mean anything"
    assert not _banked(by_name)

    await _open(engine, by_name, NEW_ID)

    result = await _executor(engine, tmp_path, remember=False).execute_step(_click_grade())

    assert result.status == StepStatus.FAILED
    assert await _clicks(engine) == []


@pytest.mark.asyncio
async def test_a_coordinate_learned_on_another_host_must_not_be_reused(
    engine: WebEngine, quiz_url: str, tmp_path: Path
) -> None:
    """The same question as above, asked of the *other* thing a run leaves behind.

    Pictures were scoped by host and remembered positions were not, so the run
    below refused the picture, correctly, and then clicked a coordinate it had
    learned on a different host anyway — reporting a pass because the button
    happened not to have moved. On two genuinely different applications sharing
    a widget name that click lands on whatever occupies those pixels.

    This test is what found it: the host refusal looked like it worked until the
    learned store was taken out of the way. AAT-115 gave ``LearnedStore`` the
    same host key the picture bank already had, which is what makes the refusal
    below real rather than accidental.
    """
    loopback = quiz_url
    by_name = quiz_url.replace("127.0.0.1", "localhost")

    await _open(engine, loopback, OLD_ID)
    assert (await _executor(engine, tmp_path).execute_step(_click_grade())).status == (
        StepStatus.PASSED
    )

    await _open(engine, by_name, NEW_ID)

    result = await _executor(engine, tmp_path).execute_step(_click_grade())

    assert result.status == StepStatus.FAILED, "a position learned elsewhere is not evidence"


@pytest.mark.asyncio
async def test_a_button_that_no_longer_looks_the_same_is_not_healed(
    engine: WebEngine, quiz_url: str, tmp_path: Path
) -> None:
    """A month-old picture describes a screen that had a month to change.

    When the element really is gone, the honest answer is a failed step. Healing
    from a picture that no longer resembles anything on screen would produce the
    AAT-109 failure in its worst form: a confident click somewhere else,
    reported as a pass.
    """
    await _open(engine, quiz_url, OLD_ID)
    assert (
        await _executor(engine, tmp_path, remember=False).execute_step(_click_grade())
    ).status == (StepStatus.PASSED)

    await _open(engine, quiz_url, NEW_ID, text="Send answer now")

    result = await _executor(engine, tmp_path, remember=False).execute_step(_click_grade())

    assert result.status == StepStatus.FAILED
    assert await _clicks(engine) == []


@pytest.mark.asyncio
async def test_a_heal_does_not_rewrite_the_picture_it_healed_from(
    engine: WebEngine, quiz_url: str, tmp_path: Path
) -> None:
    """Otherwise the crop drifts: each heal re-centres on the last heal's error."""
    await _open(engine, quiz_url, OLD_ID)
    assert (await _executor(engine, tmp_path).execute_step(_click_grade())).status == (
        StepStatus.PASSED
    )
    picture = template_store.path_for(template_store.scope_for(quiz_url), f"#{OLD_ID}")
    before = picture.read_bytes()

    await _open(engine, quiz_url, NEW_ID)
    healed = await _executor(engine, tmp_path).execute_step(_click_grade())

    assert healed.match_result is not None
    assert healed.match_result.method == MatchMethod.SAVED_TEMPLATE
    assert picture.read_bytes() == before
