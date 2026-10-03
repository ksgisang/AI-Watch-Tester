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

    def test_keeps_the_message_without_the_prefix(self) -> None:
        """A caller already printing "Step N (action)" should not have to repeat it.

        ``str(err)`` carries the prefix because the message usually travels
        alone. ``raw_message`` is the same sentence with the label removed, for
        the one caller that prints its own — see TestCriticalStepError.
        """
        err = StepExecutionError("element not found", step=3, action="find_and_click")

        assert str(err) == "Step 3 (find_and_click): element not found"
        assert err.raw_message == "element not found"


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


class TestCriticalStepErrorFromAStepFailure:
    """How the executor builds the exception, as the user reads it.

    These assert on the exact text because the text is the product here: this is
    the line a person sees when a run stops, and §9-4 of the analysis report is
    a record of that line sending someone to debug the wrong application.
    """

    @staticmethod
    def _as_the_executor_does(inner: StepExecutionError, author_message: str = "") -> str:
        """Mirror executor.py's critical-step branch."""
        reason = getattr(inner, "raw_message", "") or str(inner)
        return str(
            CriticalStepError(
                author_message or reason,
                step=inner.step,
                action=inner.action,
                cause=reason,
            )
        )

    def test_the_step_label_is_printed_once(self) -> None:
        """The regression. Passing the prefixed str(e) printed it twice.

        "CRITICAL Step 3 (find_and_click): Step 3 (find_and_click): element not
        found" reads like a quote of someone else's error, and the reason is
        pushed to the far right of the line where it is easiest to miss.
        """
        inner = StepExecutionError("element not found", step=3, action="find_and_click")

        text = self._as_the_executor_does(inner)

        assert text == "CRITICAL Step 3 (find_and_click): element not found"
        assert text.count("Step 3 (find_and_click)") == 1

    def test_the_authors_wording_does_not_replace_the_reason(self) -> None:
        """Both lines survive: what the author expected, and what actually broke."""
        inner = StepExecutionError("Login redirect detected", step=2, action="assert_url")

        text = self._as_the_executor_does(inner, "A signed-out visitor saw the home page")

        assert "A signed-out visitor saw the home page" in text
        assert "↳ actual cause: Login redirect detected" in text
        # ... and the cause line does not repeat the step it is already under
        assert text.count("Step 2 (assert_url)") == 1

    def test_an_error_with_no_step_context_still_reports_its_reason(self) -> None:
        """MatchError and friends have no raw_message; str() is all there is."""
        inner = MatchError("target image failed to load")

        reason = getattr(inner, "raw_message", "") or str(inner)
        text = str(CriticalStepError(reason, step=1, action="find_and_click", cause=reason))

        assert text == "CRITICAL Step 1 (find_and_click): target image failed to load"
