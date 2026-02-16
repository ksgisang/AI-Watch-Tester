"""Tests for aat analyze command."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from aat.cli.main import app

runner = CliRunner()


def test_analyze_help() -> None:
    """aat analyze --help shows command help."""
    result = runner.invoke(app, ["analyze", "--help"])
    assert result.exit_code == 0
    assert "Analyze" in result.output


def test_analyze_nonexistent_file() -> None:
    """aat analyze with nonexistent file exits with error."""
    result = runner.invoke(app, ["analyze", "/nonexistent/spec.md"])
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_analyze_directory_not_file(tmp_path: Path) -> None:
    """aat analyze with a directory path exits with error."""
    result = runner.invoke(app, ["analyze", str(tmp_path)])
    assert result.exit_code == 1
    assert "not a file" in result.output


def test_analyze_success(tmp_path: Path) -> None:
    """aat analyze parses document and calls AI adapter."""
    # Create a test document
    doc = tmp_path / "spec.md"
    doc.write_text("# Login Screen\n\nUser enters credentials.", encoding="utf-8")

    # Create config file to avoid search
    config_file = tmp_path / "aat.config.yaml"
    config_file.write_text("project_name: test\n", encoding="utf-8")

    mock_parser = AsyncMock()
    mock_parser.parse.return_value = ("# Login Screen\nUser enters credentials.", [])
    mock_parser.supported_extensions = [".md", ".txt"]

    mock_adapter = AsyncMock()
    mock_adapter.analyze_document.return_value = {
        "screens": [{"name": "Login"}],
        "elements": [{"name": "Username"}, {"name": "Password"}],
        "flows": [{"name": "Login Flow"}],
    }

    with (
        patch("aat.cli.commands.analyze_cmd._get_parser", return_value=mock_parser),
        patch("aat.cli.commands.analyze_cmd._get_adapter", return_value=mock_adapter),
        patch("aat.cli.commands.analyze_cmd.load_config") as mock_load,
    ):
        mock_cfg = MagicMock()
        mock_cfg.data_dir = str(tmp_path / ".aat")
        mock_load.return_value = mock_cfg

        result = runner.invoke(app, ["analyze", str(doc)])
        assert result.exit_code == 0
        assert "Parsed document" in result.output
        assert "Screens:" in result.output
        assert "Elements:" in result.output
        assert "Flows:" in result.output
        assert "Saved analysis" in result.output


def test_analyze_no_parser(tmp_path: Path) -> None:
    """aat analyze with unsupported extension exits with error."""
    doc = tmp_path / "data.csv"
    doc.write_text("col1,col2\n", encoding="utf-8")

    with (
        patch("aat.cli.commands.analyze_cmd._get_parser", return_value=None),
        patch("aat.cli.commands.analyze_cmd.load_config") as mock_load,
    ):
        mock_cfg = MagicMock()
        mock_cfg.data_dir = str(tmp_path / ".aat")
        mock_load.return_value = mock_cfg

        result = runner.invoke(app, ["analyze", str(doc)])
        assert result.exit_code == 1
        assert "No parser" in result.output


def test_analyze_saves_json_output(tmp_path: Path) -> None:
    """aat analyze saves analysis result to JSON file."""
    doc = tmp_path / "design.md"
    doc.write_text("# Design\n\nSome content.", encoding="utf-8")

    data_dir = tmp_path / ".aat"

    mock_parser = AsyncMock()
    mock_parser.parse.return_value = ("# Design\nSome content.", [])
    mock_parser.supported_extensions = [".md", ".txt"]

    analysis_result = {
        "screens": [{"name": "Home"}],
        "elements": [],
        "flows": [],
    }
    mock_adapter = AsyncMock()
    mock_adapter.analyze_document.return_value = analysis_result

    with (
        patch("aat.cli.commands.analyze_cmd._get_parser", return_value=mock_parser),
        patch("aat.cli.commands.analyze_cmd._get_adapter", return_value=mock_adapter),
        patch("aat.cli.commands.analyze_cmd.load_config") as mock_load,
    ):
        mock_cfg = MagicMock()
        mock_cfg.data_dir = str(data_dir)
        mock_load.return_value = mock_cfg

        result = runner.invoke(app, ["analyze", str(doc)])
        assert result.exit_code == 0

        # Verify JSON file was created
        json_file = data_dir / "analysis" / "design_analysis.json"
        assert json_file.exists()

        import json

        saved = json.loads(json_file.read_text(encoding="utf-8"))
        assert saved["screens"] == [{"name": "Home"}]
