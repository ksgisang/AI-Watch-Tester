"""Navigation judged by its URL, against a real browser.

The defect came out of the very first scenario a new user would write. A
`navigate` step marked `critical: true` was scored like a click: the screen had
to repaint more than half its pixels or the step hard-failed. A plain page
repaints almost nothing, so the step died while the diagnostic printed the
proof it had worked — `URL:` and `PAGE_TITLE:` on the lines below the failure —
and then pointed `FIX_TARGET` at the perfectly good scenario.

Pixels are the wrong instrument. "Did we go there?" has an exact answer in the
URL and the browser already holds it. These tests run against the local
auth-gate fixture server, which serves both shapes the fix has to get right: a
sparse white page that barely repaints, and a 307 to somewhere else.

Positive:
  * a sparse page passes a critical navigate, and the repaint really is small
    enough that the old threshold would have failed it,
  * a redirect passes and the landing URL is what gets reported.
Negative:
  * a navigate that never left the previous page is still not a pass.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from aat.core.exceptions import CriticalStepError
from aat.core.models import (
    ActionType,
    EngineConfig,
    MatchMethod,
    MatchResult,
    StepConfig,
    StepStatus,
)
from aat.engine.comparator import Comparator
from aat.engine.executor import StepExecutor
from aat.engine.humanizer import Humanizer
from aat.engine.waiter import Waiter
from aat.engine.web import WebEngine
from tests.fixtures.auth_redirect_server import auth_redirect_server

# The threshold a critical navigate used to be held to, borrowed from the
# click rules. Kept here as a number so the regression test can show that the
# page it navigates to would not have cleared it.
OLD_CLICK_THRESHOLD = 0.50


@pytest.fixture(scope="module")
def plain_url() -> Iterator[str]:
    """Local app that serves `/` as an ordinary page, no redirect."""
    with auth_redirect_server(public_paths=("/",)) as base_url:
        yield base_url


@pytest.fixture(scope="module")
def gated_url() -> Iterator[str]:
    """Local app where every path 307s to /login."""
    with auth_redirect_server() as base_url:
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
def executor(engine: WebEngine, tmp_path: Path) -> StepExecutor:
    matcher = AsyncMock()
    matcher.find = AsyncMock(
        return_value=MatchResult(
            found=False, x=0, y=0, confidence=0.0, method=MatchMethod.TEMPLATE
        )
    )
    return StepExecutor(engine, matcher, Humanizer(), Waiter(), Comparator(), tmp_path)


def _open(url: str, *, critical: bool = False, message: str | None = None) -> StepConfig:
    # `message` is left out rather than passed as None: the field is a plain
    # `str` with a default, so None is a validation error.
    extra = {"message": message} if message is not None else {}
    return StepConfig(
        step=1,
        action=ActionType.NAVIGATE,
        value=url,
        description="Open the target site",
        critical=critical,
        expect_login_redirect=True,
        **extra,
    )


class TestSparsePage:
    """Positive: the page a new user actually points AWT at."""

    async def test_critical_navigate_passes(self, executor: StepExecutor, plain_url: str) -> None:
        result = await executor.execute_step(_open(f"{plain_url}/", critical=True))
        assert result.status == StepStatus.PASSED, result.error_message

    async def test_the_repaint_is_too_small_for_the_old_rule(
        self, executor: StepExecutor, engine: WebEngine, plain_url: str
    ) -> None:
        """Proof that the page under test is the shape that used to hard-fail.

        Without this the test above would pass for the wrong reason: a page that
        happens to repaint 80% of the screen clears the old threshold too, and
        the regression would go unnoticed the next time someone reorganises the
        action tables.
        """
        before = await engine.screenshot()
        await engine.navigate(f"{plain_url}/")
        after = await engine.screenshot()

        ratio = StepExecutor._compute_change_ratio(before, after)
        assert ratio < OLD_CLICK_THRESHOLD, (
            f"the fixture page repaints {ratio:.1%}, which the old rule would have "
            "accepted — this test no longer reproduces the defect"
        )


class TestRedirect:
    """Positive: following the server's redirect is not a test failure."""

    async def test_a_redirect_passes(self, executor: StepExecutor, gated_url: str) -> None:
        result = await executor.execute_step(_open(f"{gated_url}/dashboard", critical=True))
        assert result.status == StepStatus.PASSED, result.error_message

    async def test_the_landing_url_is_where_we_ended_up(
        self, executor: StepExecutor, engine: WebEngine, gated_url: str
    ) -> None:
        await executor.execute_step(_open(f"{gated_url}/dashboard", critical=True))
        assert "/login" in await engine.get_url()


class TestNeverLeft:
    """Negative: standing still is still not arriving."""

    async def test_a_critical_navigate_that_goes_nowhere_fails(
        self, executor: StepExecutor, plain_url: str
    ) -> None:
        """Second navigate to the page we are already on, with navigation blocked.

        The server answers `/` normally, so the only way to stage "the browser
        never left" against a real Chromium is to take the navigation away and
        let the URL check speak for itself.
        """
        await executor.execute_step(_open(f"{plain_url}/"))

        async def _refuse(_url: str) -> None:
            """Accept the call and go nowhere, like a dead link."""

        engine_navigate = executor._engine.navigate
        executor._engine.navigate = _refuse  # type: ignore[method-assign]
        try:
            with pytest.raises(CriticalStepError) as exc:
                await executor.execute_step(_open(f"{plain_url}/elsewhere", critical=True))
        finally:
            executor._engine.navigate = engine_navigate  # type: ignore[method-assign]

        text = str(exc.value)
        assert "did not leave" in text
        assert "/elsewhere" in text  # what was asked for is in the message

    async def test_the_scenario_message_does_not_bury_the_urls(
        self, executor: StepExecutor, plain_url: str
    ) -> None:
        """A step.message is added to the fact, never substituted for it."""
        await executor.execute_step(_open(f"{plain_url}/"))

        async def _refuse(_url: str) -> None:
            pass

        engine_navigate = executor._engine.navigate
        executor._engine.navigate = _refuse  # type: ignore[method-assign]
        try:
            with pytest.raises(CriticalStepError) as exc:
                await executor.execute_step(
                    _open(
                        f"{plain_url}/elsewhere",
                        critical=True,
                        message="The study app is unreachable",
                    )
                )
        finally:
            executor._engine.navigate = engine_navigate  # type: ignore[method-assign]

        text = str(exc.value)
        assert "The study app is unreachable" in text  # the author's wording survives
        assert "did not leave" in text  # ... and so does the reason
