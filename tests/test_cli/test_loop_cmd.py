"""Tests for aat loop command."""

from __future__ import annotations

from typer.testing import CliRunner

from aat.cli.main import app

runner = CliRunner()


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
    assert "--max-loops" in result.output


def test_loop_help_shows_config() -> None:
    """aat loop --help shows --config option."""
    result = runner.invoke(app, ["loop", "--help"])
    assert result.exit_code == 0
    assert "--config" in result.output
