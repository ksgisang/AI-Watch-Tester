"""AAT project configuration — load / save / merge.

Merge order (later wins):
    1. Model defaults
    2. YAML file values
    3. Environment variables (AAT_ prefix, __ nested delimiter)
    4. CLI overrides dict
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from aat.core.exceptions import ConfigError
from aat.core.models import Config

DEFAULT_CONFIG_FILENAME = "aat.config.yaml"


def load_config(
    config_path: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> Config:
    """Load Config from YAML + env vars + CLI overrides.

    Args:
        config_path: Explicit path to YAML config. If None, searches cwd and parents.
        overrides: CLI flag overrides to merge on top.

    Returns:
        Validated Config instance.

    Raises:
        ConfigError: If YAML parsing or validation fails.
    """
    yaml_data: dict[str, Any] = {}

    # 1. Resolve config file path
    if config_path is None:
        config_path = _find_config_file()

    # 2. Load YAML
    if config_path is not None and config_path.exists():
        yaml_data = _load_yaml(config_path)

    # 3. Merge layers: defaults < YAML < env < CLI
    #    We collect env vars manually so they override YAML,
    #    then pass everything as init kwargs (highest priority in BaseSettings).
    env_data = _collect_env_vars()
    merged = _deep_merge(yaml_data, env_data)
    if overrides:
        merged = _deep_merge(merged, overrides)

    # 4. Construct Config
    try:
        return Config(**merged)
    except Exception as e:
        msg = f"Config validation failed: {e}"
        raise ConfigError(msg) from e


def save_config(config: Config, path: Path) -> None:
    """Save Config to YAML file.

    Args:
        config: Config instance to save.
        path: Target YAML file path.
    """
    data = config.model_dump(mode="json")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:  # noqa: PTH123
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _find_config_file() -> Path | None:
    """Search for config file in cwd, then parent directories."""
    current = Path.cwd()
    for directory in [current, *current.parents]:
        candidate = directory / DEFAULT_CONFIG_FILENAME
        if candidate.exists():
            return candidate
        # Also check .aat/ subdirectory
        candidate = directory / ".aat" / DEFAULT_CONFIG_FILENAME
        if candidate.exists():
            return candidate
    return None


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load and parse a YAML file."""
    try:
        with open(path, encoding="utf-8") as f:  # noqa: PTH123
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        msg = f"Failed to parse YAML: {path}: {e}"
        raise ConfigError(msg) from e
    except OSError as e:
        msg = f"Failed to read config: {path}: {e}"
        raise ConfigError(msg) from e

    if data is None:
        return {}
    if not isinstance(data, dict):
        msg = f"Config file must be a YAML mapping, got {type(data).__name__}: {path}"
        raise ConfigError(msg)
    return data


def _collect_env_vars() -> dict[str, Any]:
    """Collect AAT_ prefixed env vars into a nested dict."""
    prefix = "AAT_"
    delimiter = "__"
    result: dict[str, Any] = {}

    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        # Remove prefix, split by delimiter, lowercase
        parts = key[len(prefix) :].lower().split(delimiter)
        # Build nested dict
        current = result
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    return result


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base. Override wins on conflicts."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
