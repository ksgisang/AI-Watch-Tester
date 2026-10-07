"""Tests for aat loop command."""

from __future__ import annotations

import asyncio
import re

import pytest
from typer.testing import CliRunner

from aat.cli.commands import loop_cmd
from aat.cli.main import app

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_loop_command_exists() -> None:
    """aat loop is registered and shows help."""
    result = runner.invoke(app, ["loop", "--help"])
    assert result.exit_code == 0
    assert "scenarios" in result.output.lower() or "SCENARIOS_PATH" in result.output


def test_loop_nonexistent_path() -> None:
    """aat loop fails with a nonexistent scenario path."""
    result = runner.invoke(app, ["loop", "/nonexistent/scenarios"])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_loop_help_shows_max_loops() -> None:
    """aat loop --help shows --max-loops option."""
    result = runner.invoke(app, ["loop", "--help"])
    assert result.exit_code == 0
    assert "--max-loops" in _strip_ansi(result.output)


def test_loop_help_shows_config() -> None:
    """aat loop --help shows --config option."""
    result = runner.invoke(app, ["loop", "--help"])
    assert result.exit_code == 0
    assert "--config" in _strip_ansi(result.output)


def test_loop_help_shows_approval_mode() -> None:
    """aat loop --help shows --approval-mode option."""
    result = runner.invoke(app, ["loop", "--help"])
    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert "--approval-mode" in output


# ---------------------------------------------------------------------------
# The auto-mode warning (AAT-122)
# ---------------------------------------------------------------------------


def test_help_names_branch_as_the_unattended_choice() -> None:
    """``auto`` is the obvious-looking pick for "just do it"; ``branch`` is
    the same loop with the changes parked somewhere reversible, so the help
    text has to say so rather than leave it to be discovered."""
    result = runner.invoke(app, ["loop", "--help"])
    # Rich wraps the option help across terminal lines and box borders.
    output = re.sub(r"[\s│╭╰─╯]+", " ", _strip_ansi(result.output))

    assert "recommended for unattended runs" in output
    assert "throwaway git branch" in output


def _run_loop_until_config(monkeypatch: pytest.MonkeyPatch, mode: str) -> str:
    """Enter ``_loop`` far enough to see the warning, then stop.

    Stopping at ``load_config`` keeps this away from a browser while still
    exercising the real call site — the point of the test is *when* the
    warning fires, not what the function prints in isolation.
    """

    def _stop(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("stopped before the loop starts")

    monkeypatch.setattr(loop_cmd, "load_config", _stop)

    with pytest.raises(RuntimeError, match="stopped before the loop starts"):
        asyncio.run(loop_cmd._loop("scenarios", None, None, mode))

    return ""


def test_auto_mode_says_what_it_does_before_doing_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run_loop_until_config(monkeypatch, "auto")
    output = _strip_ansi(capsys.readouterr().out)

    assert "writes AI-generated changes straight into" in output
    assert "Nobody reads" in output
    # It must not oversell the screening it does have.
    assert "cannot tell a real repair" in output
    assert "--approval-mode branch" in output


def test_the_warning_is_not_a_prompt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``auto`` exists so a pipeline can run unattended.

    If this ever becomes a blocking question it breaks the one job the mode
    has, and the run hangs in CI with nobody there to answer.
    """
    _run_loop_until_config(monkeypatch, "auto")
    output = _strip_ansi(capsys.readouterr().out)

    assert "[y/N]" not in output
    assert "?" not in output


def test_manual_and_branch_modes_do_not_print_the_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for mode in ("manual", "branch"):
        _run_loop_until_config(monkeypatch, mode)
        output = _strip_ansi(capsys.readouterr().out)
        assert "straight into" not in output, mode
