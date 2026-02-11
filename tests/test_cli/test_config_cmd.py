"""Tests for aat config command."""

from __future__ import annotations

import os
from pathlib import Path  # noqa: TC003

import yaml
from typer.testing import CliRunner

from aat.cli.main import app
from aat.core.config import save_config
from aat.core.models import Config

runner = CliRunner()


def _create_config(tmp_path: Path) -> Path:
    """Create a default config file in tmp_path and return its path."""
    config = Config()
    config_path = tmp_path / "aat.config.yaml"
    save_config(config, config_path)
    return config_path


def test_config_show(tmp_path: Path, monkeypatch: object) -> None:
    """aat config show prints config as YAML."""
    import pytest

    mp = pytest.MonkeyPatch() if not hasattr(monkeypatch, "chdir") else monkeypatch  # type: ignore[attr-defined]
    assert hasattr(mp, "chdir")
    mp.chdir(tmp_path)  # type: ignore[union-attr]

    # Unset any AAT env vars
    for key in list(os.environ):
        if key.startswith("AAT_"):
            mp.delenv(key, raising=False)  # type: ignore[union-attr]

    config_path = _create_config(tmp_path)

    result = runner.invoke(app, ["config", "show", "--config", str(config_path)])
    assert result.exit_code == 0
    assert "project_name" in result.output
    assert "aat-project" in result.output


def test_config_show_no_config(tmp_path: Path, monkeypatch: object) -> None:
    """aat config show with no config file uses defaults."""
    import pytest

    mp = pytest.MonkeyPatch() if not hasattr(monkeypatch, "chdir") else monkeypatch  # type: ignore[attr-defined]
    assert hasattr(mp, "chdir")
    mp.chdir(tmp_path)  # type: ignore[union-attr]

    # Unset any AAT env vars
    for key in list(os.environ):
        if key.startswith("AAT_"):
            mp.delenv(key, raising=False)  # type: ignore[union-attr]

    result = runner.invoke(app, ["config", "show"])
    # Should succeed with defaults even without config file
    assert result.exit_code == 0
    assert "project_name" in result.output


def test_config_set(tmp_path: Path, monkeypatch: object) -> None:
    """aat config set updates a config value."""
    import pytest

    mp = pytest.MonkeyPatch() if not hasattr(monkeypatch, "chdir") else monkeypatch  # type: ignore[attr-defined]
    assert hasattr(mp, "chdir")
    mp.chdir(tmp_path)  # type: ignore[union-attr]

    # Unset any AAT env vars
    for key in list(os.environ):
        if key.startswith("AAT_"):
            mp.delenv(key, raising=False)  # type: ignore[union-attr]

    config_path = _create_config(tmp_path)

    result = runner.invoke(
        app, ["config", "set", "ai.provider", "openai", "--config", str(config_path)]
    )
    assert result.exit_code == 0
    assert "Set ai.provider = openai" in result.output

    # Verify the file was updated
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["ai"]["provider"] == "openai"


def test_config_set_nested_key(tmp_path: Path, monkeypatch: object) -> None:
    """aat config set handles deeply nested dotted keys."""
    import pytest

    mp = pytest.MonkeyPatch() if not hasattr(monkeypatch, "chdir") else monkeypatch  # type: ignore[attr-defined]
    assert hasattr(mp, "chdir")
    mp.chdir(tmp_path)  # type: ignore[union-attr]

    # Unset any AAT env vars
    for key in list(os.environ):
        if key.startswith("AAT_"):
            mp.delenv(key, raising=False)  # type: ignore[union-attr]

    config_path = _create_config(tmp_path)

    result = runner.invoke(
        app, ["config", "set", "engine.browser", "firefox", "--config", str(config_path)]
    )
    assert result.exit_code == 0

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["engine"]["browser"] == "firefox"
