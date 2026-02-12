"""Tests for aat start command."""

from __future__ import annotations

import re

from typer.testing import CliRunner

from aat.cli.main import app

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_start_command_exists() -> None:
    """aat start is registered and shows help."""
    result = runner.invoke(app, ["start", "--help"])
    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert "start" in output.lower()


def test_start_help_shows_config_option() -> None:
    """aat start --help shows --config option."""
    result = runner.invoke(app, ["start", "--help"])
    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert "--config" in output
