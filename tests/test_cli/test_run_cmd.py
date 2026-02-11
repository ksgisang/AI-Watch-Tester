"""Tests for aat run command."""

from __future__ import annotations

from typer.testing import CliRunner

from aat.cli.main import app

runner = CliRunner()


def test_run_nonexistent_path() -> None:
    """aat run fails with a nonexistent scenario path."""
    result = runner.invoke(app, ["run", "/nonexistent/scenarios"])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_run_command_exists() -> None:
    """aat run is registered and shows help."""
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "scenarios" in result.output.lower() or "SCENARIOS_PATH" in result.output
