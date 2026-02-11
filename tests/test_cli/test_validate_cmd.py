"""Tests for aat validate command."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

import yaml
from typer.testing import CliRunner

from aat.cli.main import app

runner = CliRunner()

_VALID_SCENARIO = {
    "id": "SC-001",
    "name": "Test Login",
    "description": "Test login flow",
    "steps": [
        {
            "step": 1,
            "action": "navigate",
            "description": "Go to login page",
            "value": "https://example.com/login",
        },
    ],
}

_INVALID_SCENARIO = {
    "id": "INVALID",  # Does not match SC-NNN pattern
    "name": "Bad Scenario",
    "steps": [
        {
            "step": 1,
            "action": "navigate",
            "description": "Go somewhere",
            "value": "https://example.com",
        },
    ],
}


def _write_yaml(path: Path, data: object) -> None:
    """Write data as YAML to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False)


def test_validate_valid_file(tmp_path: Path) -> None:
    """aat validate succeeds with a valid scenario file."""
    scenario_file = tmp_path / "valid.yaml"
    _write_yaml(scenario_file, _VALID_SCENARIO)

    result = runner.invoke(app, ["validate", str(scenario_file)])
    assert result.exit_code == 0
    assert "OK" in result.output
    assert "1 OK" in result.output


def test_validate_invalid_file(tmp_path: Path) -> None:
    """aat validate fails with an invalid scenario file."""
    scenario_file = tmp_path / "invalid.yaml"
    _write_yaml(scenario_file, _INVALID_SCENARIO)

    result = runner.invoke(app, ["validate", str(scenario_file)])
    assert result.exit_code == 1
    assert "ERROR" in result.output


def test_validate_directory(tmp_path: Path) -> None:
    """aat validate processes all YAML files in a directory."""
    _write_yaml(tmp_path / "a.yaml", _VALID_SCENARIO)
    _write_yaml(tmp_path / "b.yaml", _INVALID_SCENARIO)

    result = runner.invoke(app, ["validate", str(tmp_path)])
    assert result.exit_code == 1
    assert "1 OK" in result.output
    assert "1 ERROR" in result.output


def test_validate_nonexistent_path() -> None:
    """aat validate fails with a nonexistent path."""
    result = runner.invoke(app, ["validate", "/nonexistent/path"])
    assert result.exit_code == 1
    assert "does not exist" in result.output


def test_validate_empty_directory(tmp_path: Path) -> None:
    """aat validate fails when directory has no YAML files."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    result = runner.invoke(app, ["validate", str(empty_dir)])
    assert result.exit_code == 1
    assert "No YAML files" in result.output


def test_validate_all_valid(tmp_path: Path) -> None:
    """aat validate returns exit code 0 when all scenarios are valid."""
    scenario_2 = dict(_VALID_SCENARIO)
    scenario_2["id"] = "SC-002"
    _write_yaml(tmp_path / "a.yaml", _VALID_SCENARIO)
    _write_yaml(tmp_path / "b.yaml", scenario_2)

    result = runner.invoke(app, ["validate", str(tmp_path)])
    assert result.exit_code == 0
    assert "2 OK, 0 ERROR" in result.output
