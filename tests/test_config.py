"""Tests for Config loading, saving, and 3-layer merge."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aat.core.config import (
    DEFAULT_CONFIG_FILENAME,
    _deep_merge,
    _load_yaml,
    load_config,
    save_config,
)
from aat.core.exceptions import ConfigError
from aat.core.models import Config

# ── Defaults ──


class TestConfigDefaults:
    def test_default_values(self) -> None:
        config = Config()
        assert config.project_name == "aat-project"
        assert config.source_path == "."
        assert config.url == ""
        assert config.max_loops == 10

    def test_nested_defaults(self) -> None:
        config = Config()
        assert config.ai.provider == "claude"
        assert config.engine.browser == "chromium"
        assert config.matching.confidence_threshold == 0.85
        assert config.humanizer.enabled is True

    def test_is_base_settings(self) -> None:
        from pydantic_settings import BaseSettings

        assert issubclass(Config, BaseSettings)


# ── YAML Loading ──


class TestYAMLLoading:
    def test_load_from_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / DEFAULT_CONFIG_FILENAME
        yaml_file.write_text(
            yaml.dump({"project_name": "my-project", "url": "https://example.com"}),
            encoding="utf-8",
        )
        config = load_config(config_path=yaml_file)
        assert config.project_name == "my-project"
        assert config.url == "https://example.com"

    def test_load_nested_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / DEFAULT_CONFIG_FILENAME
        yaml_file.write_text(
            yaml.dump(
                {
                    "ai": {"provider": "openai", "model": "gpt-4"},
                    "engine": {"headless": True, "browser": "firefox"},
                }
            ),
            encoding="utf-8",
        )
        config = load_config(config_path=yaml_file)
        assert config.ai.provider == "openai"
        assert config.ai.model == "gpt-4"
        assert config.engine.headless is True
        assert config.engine.browser == "firefox"

    def test_load_empty_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / DEFAULT_CONFIG_FILENAME
        yaml_file.write_text("", encoding="utf-8")
        config = load_config(config_path=yaml_file)
        assert config.project_name == "aat-project"

    def test_load_nonexistent_path_uses_defaults(self) -> None:
        config = load_config(config_path=Path("/nonexistent/aat.config.yaml"))
        assert config.project_name == "aat-project"

    def test_load_invalid_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / DEFAULT_CONFIG_FILENAME
        yaml_file.write_text("project_name: [invalid: yaml: {{", encoding="utf-8")
        with pytest.raises(ConfigError, match="Failed to parse YAML"):
            load_config(config_path=yaml_file)

    def test_load_non_mapping_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / DEFAULT_CONFIG_FILENAME
        yaml_file.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ConfigError, match="must be a YAML mapping"):
            _load_yaml(yaml_file)


# ── Environment Variable Merge ──


class TestEnvVarMerge:
    def test_env_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AAT_PROJECT_NAME", "env-project")
        config = load_config(config_path=Path("/nonexistent/config.yaml"))
        assert config.project_name == "env-project"

    def test_env_nested(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AAT_AI__PROVIDER", "openai")
        monkeypatch.setenv("AAT_AI__MODEL", "gpt-4o")
        config = load_config(config_path=Path("/nonexistent/config.yaml"))
        assert config.ai.provider == "openai"
        assert config.ai.model == "gpt-4o"

    def test_env_overrides_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        yaml_file = tmp_path / DEFAULT_CONFIG_FILENAME
        yaml_file.write_text(yaml.dump({"project_name": "yaml-project"}), encoding="utf-8")
        monkeypatch.setenv("AAT_PROJECT_NAME", "env-project")
        config = load_config(config_path=yaml_file)
        assert config.project_name == "env-project"


# ── CLI Override Merge ──


class TestCLIOverrides:
    def test_override_flat(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / DEFAULT_CONFIG_FILENAME
        yaml_file.write_text(yaml.dump({"project_name": "yaml-project"}), encoding="utf-8")
        config = load_config(
            config_path=yaml_file,
            overrides={"project_name": "cli-project"},
        )
        assert config.project_name == "cli-project"

    def test_override_nested(self) -> None:
        config = load_config(
            config_path=Path("/nonexistent/config.yaml"),
            overrides={"engine": {"headless": True}},
        )
        assert config.engine.headless is True
        assert config.engine.browser == "chromium"

    def test_override_does_not_destroy_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / DEFAULT_CONFIG_FILENAME
        yaml_file.write_text(
            yaml.dump(
                {
                    "project_name": "yaml-project",
                    "ai": {"provider": "claude", "model": "sonnet"},
                }
            ),
            encoding="utf-8",
        )
        config = load_config(
            config_path=yaml_file,
            overrides={"ai": {"model": "haiku"}},
        )
        assert config.ai.provider == "claude"  # from YAML
        assert config.ai.model == "haiku"  # from override

    def test_validation_error_raises_config_error(self) -> None:
        with pytest.raises(ConfigError, match="Config validation failed"):
            load_config(
                config_path=Path("/nonexistent/config.yaml"),
                overrides={"max_loops": 999},
            )


# ── Save Config ──


class TestSaveConfig:
    def test_save_and_reload(self, tmp_path: Path) -> None:
        config = Config(project_name="saved-project", url="https://test.com")
        out_path = tmp_path / DEFAULT_CONFIG_FILENAME
        save_config(config, out_path)

        assert out_path.exists()
        reloaded = load_config(config_path=out_path)
        assert reloaded.project_name == "saved-project"
        assert reloaded.url == "https://test.com"

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        config = Config()
        out_path = tmp_path / "nested" / "dir" / DEFAULT_CONFIG_FILENAME
        save_config(config, out_path)
        assert out_path.exists()

    def test_saved_yaml_is_readable(self, tmp_path: Path) -> None:
        config = Config(ai={"provider": "openai", "model": "gpt-4"})
        out_path = tmp_path / DEFAULT_CONFIG_FILENAME
        save_config(config, out_path)
        with open(out_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["ai"]["provider"] == "openai"
        assert data["ai"]["model"] == "gpt-4"


# ── Deep Merge ──


class TestDeepMerge:
    def test_flat_merge(self) -> None:
        result = _deep_merge({"a": 1, "b": 2}, {"b": 3, "c": 4})
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self) -> None:
        base = {"x": {"a": 1, "b": 2}, "y": 10}
        override = {"x": {"b": 3, "c": 4}}
        result = _deep_merge(base, override)
        assert result == {"x": {"a": 1, "b": 3, "c": 4}, "y": 10}

    def test_override_replaces_non_dict(self) -> None:
        result = _deep_merge({"x": "string"}, {"x": {"nested": True}})
        assert result == {"x": {"nested": True}}

    def test_empty_override(self) -> None:
        base = {"a": 1}
        result = _deep_merge(base, {})
        assert result == {"a": 1}

    def test_empty_base(self) -> None:
        result = _deep_merge({}, {"a": 1})
        assert result == {"a": 1}
