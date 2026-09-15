"""Login-redirect hard stop: expected vs unexpected, against a real browser.

Runs a real Chromium against the local auth-gate fixture server (307 -> /login),
which is the exact shape that made access-control scenarios impossible to pass
and made critical failures report the wrong cause.

Positive: a step marked expect_login_redirect passes when bounced to /login.
Negative: the same step without the mark still hard-stops (session expiry).
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


@pytest.fixture(scope="module")
def app_url() -> Iterator[str]:
    """Local app whose every protected path 307s to /login."""
    with auth_redirect_server() as base_url:
        yield base_url


@pytest.fixture()
async def engine() -> AsyncIterator[WebEngine]:
    """Real headless Chromium. Skips the test if the browser is not installed."""
    eng = WebEngine(EngineConfig(headless=True, speed="fast", screenshot_mode="on-failure"))
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
            found=True, x=1, y=1, confidence=0.99, method=MatchMethod.TEMPLATE
        )
    )
    return StepExecutor(engine, matcher, Humanizer(), Waiter(), Comparator(), tmp_path)


def _navigate(url: str, *, expect_redirect: bool | None) -> StepConfig:
    return StepConfig(
        step=1,
        action=ActionType.NAVIGATE,
        value=url,
        description="Open the protected home page while signed out",
        expect_login_redirect=expect_redirect,
    )


def _assert_url(*, expect_redirect: bool | None) -> StepConfig:
    return StepConfig(
        step=2,
        action=ActionType.ASSERT_URL,
        value="/login",
        description="Signed-out visitor is bounced to the login page",
        critical=True,
        message="A signed-out visitor saw the home page (access-control defect)",
        expect_login_redirect=expect_redirect,
    )


class TestExpectedLoginRedirect:
    """Positive: the redirect is the pass condition."""

    async def test_navigate_passes(self, executor: StepExecutor, app_url: str) -> None:
        result = await executor.execute_step(_navigate(f"{app_url}/", expect_redirect=True))
        assert result.status == StepStatus.PASSED, result.error_message

    async def test_critical_assert_url_passes(self, executor: StepExecutor, app_url: str) -> None:
        nav = await executor.execute_step(_navigate(f"{app_url}/", expect_redirect=True))
        assert nav.status == StepStatus.PASSED, nav.error_message

        result = await executor.execute_step(_assert_url(expect_redirect=True))
        assert result.status == StepStatus.PASSED, result.error_message


class TestUnexpectedLoginRedirect:
    """Negative: without the mark, a real session expiry is still caught."""

    async def test_navigate_still_fails(self, executor: StepExecutor, app_url: str) -> None:
        result = await executor.execute_step(_navigate(f"{app_url}/", expect_redirect=None))
        assert result.status == StepStatus.FAILED
        assert "redirect" in (result.error_message or "").lower()

    async def test_explicit_false_still_fails(self, executor: StepExecutor, app_url: str) -> None:
        """An explicit `expect_login_redirect: false` is not an opt-out of detection."""
        result = await executor.execute_step(_navigate(f"{app_url}/", expect_redirect=False))
        assert result.status == StepStatus.FAILED
        assert "redirect" in (result.error_message or "").lower()

    async def test_critical_failure_keeps_real_cause(
        self, executor: StepExecutor, app_url: str
    ) -> None:
        """step.message must not bury the reason the step actually died."""
        await executor.execute_step(_navigate(f"{app_url}/", expect_redirect=True))

        with pytest.raises(CriticalStepError) as exc:
            await executor.execute_step(_assert_url(expect_redirect=None))

        text = str(exc.value)
        assert "access-control defect" in text  # the author's interpretation survives
        assert "actual cause" in text  # ... and so does the real reason
        assert "redirect" in text.lower()
