"""AAT custom exception hierarchy.

All exceptions inherit from AATError.
StepExecutionError carries step context for recording in StepResult.
"""


class AATError(Exception):
    """Base exception for all AAT errors."""


class ConfigError(AATError):
    """Configuration file load/validation error."""


class ScenarioError(AATError):
    """Scenario YAML parsing/validation error."""


class EngineError(AATError):
    """Test engine error (browser launch failure, etc.)."""


class MatchError(AATError):
    """Image matching error (target image load failure, etc.)."""


class AdapterError(AATError):
    """AI Adapter error (API call failure, response parse error, etc.)."""


class ParserError(AATError):
    """Document parser error."""


class ReporterError(AATError):
    """Report generation error."""


class StepExecutionError(AATError):
    """Step execution error. Recorded in StepResult, does not crash the scenario."""

    def __init__(self, message: str, step: int, action: str) -> None:
        self.step = step
        self.action = action
        super().__init__(f"Step {step} ({action}): {message}")


class CriticalStepError(AATError):
    """Critical step failed — test must stop immediately.

    ``message`` is usually the scenario author's interpretation (step.message):
    what a broken assertion would *mean*. A step can die for reasons that have
    nothing to do with that assertion, so ``cause`` carries the underlying
    error and is reported alongside it — never in its place.
    """

    def __init__(self, message: str, step: int, action: str, cause: str = "") -> None:
        self.step = step
        self.action = action
        self.message = message
        # Nothing to add when the interpretation already is the cause
        self.cause = cause if cause and cause != message else ""
        self.detail = f"{message}\n  ↳ actual cause: {self.cause}" if self.cause else message
        super().__init__(f"CRITICAL Step {step} ({action}): {self.detail}")


class LoopError(AATError):
    """DevQA Loop error."""


class GitOpsError(AATError):
    """Git operations error (branch, commit, checkout, etc.)."""


class LearningError(AATError):
    """Learning data storage/query error."""


class DashboardError(AATError):
    """Web dashboard error (server start, WebSocket, etc.)."""
