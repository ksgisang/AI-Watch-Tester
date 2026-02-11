"""Tests for aat init command."""

from __future__ import annotations

import os

from typer.testing import CliRunner

from aat.cli.main import app

runner = CliRunner()


def test_init_creates_directories(tmp_path: object, monkeypatch: object) -> None:
    """aat init creates .aat/ and scenarios/ directories."""
    from pathlib import Path

    assert isinstance(tmp_path, Path)

    import pytest

    mp = pytest.MonkeyPatch() if not hasattr(monkeypatch, "chdir") else monkeypatch  # type: ignore[attr-defined]
    assert hasattr(mp, "chdir")
    mp.chdir(tmp_path)  # type: ignore[union-attr]

    result = runner.invoke(app, ["init", "--name", "test-project"])
    assert result.exit_code == 0
    assert (tmp_path / ".aat").is_dir()
    assert (tmp_path / "scenarios").is_dir()


def test_init_creates_config_file(tmp_path: object, monkeypatch: object) -> None:
    """aat init creates aat.config.yaml."""
    from pathlib import Path

    assert isinstance(tmp_path, Path)

    import pytest

    mp = pytest.MonkeyPatch() if not hasattr(monkeypatch, "chdir") else monkeypatch  # type: ignore[attr-defined]
    assert hasattr(mp, "chdir")
    mp.chdir(tmp_path)  # type: ignore[union-attr]

    result = runner.invoke(app, ["init", "--name", "test-project"])
    assert result.exit_code == 0

    config_file = tmp_path / "aat.config.yaml"
    assert config_file.exists()
    content = config_file.read_text(encoding="utf-8")
    assert "test-project" in content


def test_init_appends_gitignore(tmp_path: object, monkeypatch: object) -> None:
    """aat init appends AAT entries to .gitignore if it exists."""
    from pathlib import Path

    assert isinstance(tmp_path, Path)

    import pytest

    mp = pytest.MonkeyPatch() if not hasattr(monkeypatch, "chdir") else monkeypatch  # type: ignore[attr-defined]
    assert hasattr(mp, "chdir")
    mp.chdir(tmp_path)  # type: ignore[union-attr]

    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("node_modules/\n", encoding="utf-8")

    result = runner.invoke(app, ["init", "--name", "test-project"])
    assert result.exit_code == 0

    content = gitignore.read_text(encoding="utf-8")
    assert "node_modules/" in content
    assert ".aat/config.yaml" in content


def test_init_no_duplicate_gitignore(tmp_path: object, monkeypatch: object) -> None:
    """aat init does not duplicate .gitignore entries on second run."""
    from pathlib import Path

    assert isinstance(tmp_path, Path)

    import pytest

    mp = pytest.MonkeyPatch() if not hasattr(monkeypatch, "chdir") else monkeypatch  # type: ignore[attr-defined]
    assert hasattr(mp, "chdir")
    mp.chdir(tmp_path)  # type: ignore[union-attr]

    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("node_modules/\n", encoding="utf-8")

    runner.invoke(app, ["init"])
    runner.invoke(app, ["init"])

    content = gitignore.read_text(encoding="utf-8")
    assert content.count(".aat/config.yaml") == 1


def test_init_success_message(tmp_path: object, monkeypatch: object) -> None:
    """aat init shows success message."""
    from pathlib import Path

    assert isinstance(tmp_path, Path)

    import pytest

    mp = pytest.MonkeyPatch() if not hasattr(monkeypatch, "chdir") else monkeypatch  # type: ignore[attr-defined]
    assert hasattr(mp, "chdir")
    mp.chdir(tmp_path)  # type: ignore[union-attr]

    result = runner.invoke(app, ["init", "--name", "my-app"])
    assert result.exit_code == 0
    assert "my-app" in result.output
    assert "initialized successfully" in result.output


def test_init_custom_options(tmp_path: object, monkeypatch: object) -> None:
    """aat init respects --source and --url options."""
    from pathlib import Path

    assert isinstance(tmp_path, Path)

    import pytest

    mp = pytest.MonkeyPatch() if not hasattr(monkeypatch, "chdir") else monkeypatch  # type: ignore[attr-defined]
    assert hasattr(mp, "chdir")
    mp.chdir(tmp_path)  # type: ignore[union-attr]

    # Unset any AAT env vars that could interfere
    for key in list(os.environ):
        if key.startswith("AAT_"):
            mp.delenv(key, raising=False)  # type: ignore[union-attr]

    result = runner.invoke(
        app, ["init", "--name", "custom", "--source", "/src", "--url", "https://example.com"]
    )
    assert result.exit_code == 0

    config_file = tmp_path / "aat.config.yaml"
    content = config_file.read_text(encoding="utf-8")
    assert "custom" in content
    assert "/src" in content
    assert "https://example.com" in content
