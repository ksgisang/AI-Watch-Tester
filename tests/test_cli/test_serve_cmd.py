"""Tests for 'aat serve' command."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from aat.cli.main import app

runner = CliRunner()


class TestServeCommand:
    """Tests for the serve command."""

    def test_serve_without_uvicorn_exits(self) -> None:
        """serve command fails gracefully if uvicorn is not installed."""
        with patch.dict("sys.modules", {"uvicorn": None}):
            result = runner.invoke(app, ["serve", "--no-open"])
            # Should fail because uvicorn import fails
            assert result.exit_code != 0

    def test_serve_appears_in_help(self) -> None:
        """serve command is registered in CLI help."""
        result = runner.invoke(app, ["--help"])
        assert "serve" in result.output

    def test_serve_help(self) -> None:
        """serve --help shows description."""
        result = runner.invoke(app, ["serve", "--help"])
        assert result.exit_code == 0
        assert "dashboard" in result.output.lower() or "single process" in result.output.lower()
