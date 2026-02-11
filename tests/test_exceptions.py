"""Tests for exception hierarchy."""

import pytest

from aat.core.exceptions import (
    AATError,
    AdapterError,
    ConfigError,
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
