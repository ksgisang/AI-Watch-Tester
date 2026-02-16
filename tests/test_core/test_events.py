"""Tests for the AAT event system."""

from __future__ import annotations

import re

import pytest

from aat.core.events import CLIEventHandler, MessageBuffer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cli() -> CLIEventHandler:
    return CLIEventHandler()


@pytest.fixture
def buf() -> MessageBuffer:
    return MessageBuffer()


# ---------------------------------------------------------------------------
# Tests: CLIEventHandler
# ---------------------------------------------------------------------------


class TestCLIEventHandler:
    """Tests for CLIEventHandler terminal output."""

    def test_info(self, cli: CLIEventHandler, capsys: pytest.CaptureFixture[str]) -> None:
        """info() prints a plain message to stdout."""
        cli.info("hello world")
        captured = capsys.readouterr()
        assert "hello world" in captured.out

    def test_success(self, cli: CLIEventHandler, capsys: pytest.CaptureFixture[str]) -> None:
        """success() prints [OK] prefix with the message."""
        cli.success("all good")
        captured = capsys.readouterr()
        text = _strip_ansi(captured.out)
        assert "[OK] all good" in text

    def test_warning(self, cli: CLIEventHandler, capsys: pytest.CaptureFixture[str]) -> None:
        """warning() prints [WARN] prefix with the message."""
        cli.warning("careful")
        captured = capsys.readouterr()
        text = _strip_ansi(captured.out)
        assert "[WARN] careful" in text

    def test_error(self, cli: CLIEventHandler, capsys: pytest.CaptureFixture[str]) -> None:
        """error() prints [ERROR] prefix to stderr."""
        cli.error("something broke")
        captured = capsys.readouterr()
        text = _strip_ansi(captured.err)
        assert "[ERROR] something broke" in text

    def test_step_start(self, cli: CLIEventHandler, capsys: pytest.CaptureFixture[str]) -> None:
        """step_start() prints step progress without newline."""
        cli.step_start(1, 5, "Navigate to page")
        captured = capsys.readouterr()
        text = _strip_ansi(captured.out)
        assert "Step 1/5" in text
        assert "Navigate to page" in text

    def test_step_result_passed(
        self,
        cli: CLIEventHandler,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """step_result() prints OK when step passes."""
        cli.step_result(1, passed=True, description="Navigate")
        captured = capsys.readouterr()
        text = _strip_ansi(captured.out)
        assert "OK" in text

    def test_step_result_failed(
        self,
        cli: CLIEventHandler,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """step_result() prints FAILED when step fails."""
        cli.step_result(2, passed=False, description="Click button")
        captured = capsys.readouterr()
        text = _strip_ansi(captured.out)
        assert "FAILED" in text

    def test_step_result_failed_with_error(
        self,
        cli: CLIEventHandler,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """step_result() prints FAILED with reason when error is provided."""
        cli.step_result(2, passed=False, description="Click button", error="Element not found")
        captured = capsys.readouterr()
        text = _strip_ansi(captured.out)
        assert "FAILED" in text
        assert "Element not found" in text

    def test_progress(self, cli: CLIEventHandler, capsys: pytest.CaptureFixture[str]) -> None:
        """progress() prints label with current/total counter."""
        cli.progress("Analyzing docs", 2, 5)
        captured = capsys.readouterr()
        text = _strip_ansi(captured.out)
        assert "(2/5)" in text
        assert "Analyzing docs" in text

    def test_prompt(
        self,
        cli: CLIEventHandler,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """prompt() asks user for input via typer.prompt."""
        monkeypatch.setattr("typer.prompt", lambda question: "user_answer")
        result = cli.prompt("What is your name?")
        assert result == "user_answer"

    def test_prompt_with_options(
        self,
        cli: CLIEventHandler,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """prompt() prints numbered options before asking for input."""
        monkeypatch.setattr("typer.prompt", lambda question: "2")
        result = cli.prompt("Select provider", options=["claude", "openai", "ollama"])
        captured = capsys.readouterr()
        text = _strip_ansi(captured.out)
        assert "[1] claude" in text
        assert "[2] openai" in text
        assert "[3] ollama" in text
        assert result == "2"

    def test_section(self, cli: CLIEventHandler, capsys: pytest.CaptureFixture[str]) -> None:
        """section() prints a visual separator with the title."""
        cli.section("Test Results")
        captured = capsys.readouterr()
        text = _strip_ansi(captured.out)
        assert "=" * 50 in text
        assert "Test Results" in text


# ---------------------------------------------------------------------------
# Tests: MessageBuffer
# ---------------------------------------------------------------------------


class TestMessageBuffer:
    """Tests for MessageBuffer message collection."""

    def test_info_appends_message(self, buf: MessageBuffer) -> None:
        """info() adds an info-type message."""
        buf.info("hello")
        assert len(buf.messages) == 1
        assert buf.messages[0] == {"type": "info", "text": "hello"}

    def test_success_appends_message(self, buf: MessageBuffer) -> None:
        """success() adds a success-type message."""
        buf.success("done")
        assert buf.messages[0]["type"] == "success"
        assert buf.messages[0]["text"] == "done"

    def test_warning_appends_message(self, buf: MessageBuffer) -> None:
        """warning() adds a warning-type message."""
        buf.warning("careful")
        assert buf.messages[0]["type"] == "warning"

    def test_error_appends_message(self, buf: MessageBuffer) -> None:
        """error() adds an error-type message."""
        buf.error("oops")
        assert buf.messages[0]["type"] == "error"
        assert buf.messages[0]["text"] == "oops"

    def test_step_start_appends_message(self, buf: MessageBuffer) -> None:
        """step_start() adds a step_start message with step/total."""
        buf.step_start(1, 5, "Navigate")
        msg = buf.messages[0]
        assert msg["type"] == "step_start"
        assert msg["step"] == 1
        assert msg["total"] == 5
        assert msg["text"] == "Navigate"

    def test_step_result_appends_message(self, buf: MessageBuffer) -> None:
        """step_result() adds a step_result message with passed/error fields."""
        buf.step_result(2, passed=False, description="Click", error="Not found")
        msg = buf.messages[0]
        assert msg["type"] == "step_result"
        assert msg["step"] == 2
        assert msg["passed"] is False
        assert msg["text"] == "Click"
        assert msg["error"] == "Not found"

    def test_step_result_no_error(self, buf: MessageBuffer) -> None:
        """step_result() stores None error when not provided."""
        buf.step_result(1, passed=True, description="Navigate")
        msg = buf.messages[0]
        assert msg["passed"] is True
        assert msg["error"] is None

    def test_progress_appends_message(self, buf: MessageBuffer) -> None:
        """progress() adds a progress message with current/total."""
        buf.progress("Analyzing", 3, 10)
        msg = buf.messages[0]
        assert msg["type"] == "progress"
        assert msg["current"] == 3
        assert msg["total"] == 10

    def test_prompt_returns_empty_string(self, buf: MessageBuffer) -> None:
        """prompt() returns empty string (placeholder for messenger override)."""
        result = buf.prompt("Choose one", options=["a", "b"])
        assert result == ""
        msg = buf.messages[0]
        assert msg["type"] == "prompt"
        assert msg["options"] == ["a", "b"]

    def test_section_appends_message(self, buf: MessageBuffer) -> None:
        """section() adds a section-type message."""
        buf.section("Results")
        assert buf.messages[0] == {"type": "section", "text": "Results"}

    def test_to_text_formats_all_types(self, buf: MessageBuffer) -> None:
        """to_text() formats collected messages as plain text."""
        buf.section("Report")
        buf.success("Tests passed")
        buf.error("Connection failed")
        buf.step_result(1, passed=True, description="Navigate")
        buf.step_result(2, passed=False, description="Click button")
        buf.info("Done")

        text = buf.to_text()
        lines = text.split("\n")

        assert "--- Report ---" in lines[0]
        assert "[OK] Tests passed" in lines[1]
        assert "[ERROR] Connection failed" in lines[2]
        assert "Step 1: OK" in lines[3]
        assert "Navigate" in lines[3]
        assert "Step 2: FAILED" in lines[4]
        assert "Click button" in lines[4]
        assert "Done" in lines[5]

    def test_to_text_empty_buffer(self, buf: MessageBuffer) -> None:
        """to_text() returns empty string when no messages collected."""
        assert buf.to_text() == ""

    def test_multiple_messages_accumulate(self, buf: MessageBuffer) -> None:
        """Messages accumulate across multiple calls."""
        buf.info("first")
        buf.info("second")
        buf.warning("third")
        assert len(buf.messages) == 3
