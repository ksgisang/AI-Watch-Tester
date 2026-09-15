"""Tests for exception hierarchy."""

import pytest

from aat.core.exceptions import (
    AATError,
    AdapterError,
    ConfigError,
    CriticalStepError,
    EngineError,
    LearningError,
    LoopError,
    MatchError,
    ParserError,
    ReporterError,
    ScenarioError,
    StepExecutionError,
)


class TestExceptionHierarchy:
    def test_all_inherit_from_aat_error(self) -> None:
        exceptions = [
            ConfigError,
            ScenarioError,
            EngineError,
            MatchError,
            AdapterError,
            ParserError,
            ReporterError,
            StepExecutionError,
            LoopError,
            LearningError,
        ]
        for exc_cls in exceptions:
            assert issubclass(exc_cls, AATError)

    def test_aat_error_is_exception(self) -> None:
        assert issubclass(AATError, Exception)

    def test_catch_base(self) -> None:
        with pytest.raises(AATError):
            raise ConfigError("bad config")

    def test_catch_specific(self) -> None:
        with pytest.raises(ConfigError):
            raise ConfigError("missing field")


class TestStepExecutionError:
    def test_attributes(self) -> None:
        err = StepExecutionError("element not found", step=3, action="find_and_click")
        assert err.step == 3
        assert err.action == "find_and_click"

    def test_message_format(self) -> None:
        err = StepExecutionError("timeout", step=5, action="assert")
        assert str(err) == "Step 5 (assert): timeout"

    def test_is_aat_error(self) -> None:
        err = StepExecutionError("fail", step=1, action="click")
        assert isinstance(err, AATError)


class TestCriticalStepError:
    """The step's own message must never replace the real reason it died."""

    def test_reports_both_message_and_cause(self) -> None:
        err = CriticalStepError(
            "A signed-out visitor saw the home page (access-control defect)",
            step=2,
            action="assert_url",
            cause="Step 2 (assert_url): Login redirect detected after step 2.",
        )
        text = str(err)
        assert "CRITICAL Step 2 (assert_url):" in text
        assert "access-control defect" in text
        assert "↳ actual cause: Step 2 (assert_url): Login redirect detected" in text
        assert err.cause.startswith("Step 2")

    def test_single_line_when_cause_matches_message(self) -> None:
        """A genuinely broken assertion says the same thing twice — so say it once."""
        err = CriticalStepError("URL mismatch", step=1, action="assert_url", cause="URL mismatch")
        assert str(err) == "CRITICAL Step 1 (assert_url): URL mismatch"
        assert err.cause == ""

    def test_single_line_without_cause(self) -> None:
        err = CriticalStepError("boom", step=1, action="click")
        assert str(err) == "CRITICAL Step 1 (click): boom"
        assert err.detail == "boom"

    def test_attributes(self) -> None:
        err = CriticalStepError("msg", step=4, action="find_and_click", cause="real reason")
        assert err.step == 4
        assert err.action == "find_and_click"
        assert err.message == "msg"
        assert isinstance(err, AATError)
