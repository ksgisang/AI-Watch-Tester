"""aat config — configuration management."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml

from aat.core.config import DEFAULT_CONFIG_FILENAME, load_config, save_config
from aat.core.exceptions import ConfigError

config_app = typer.Typer(
    name="config",
    help="Configuration management commands.",
    no_args_is_help=True,
)


@config_app.command(name="show")
def config_show(
    config_path: str | None = typer.Option(None, "--config", "-c", help="Config file path."),
) -> None:
    """Show current configuration."""
    try:
        path = Path(config_path) if config_path else None
        config = load_config(config_path=path)
        data = config.model_dump(mode="json")
        output = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        typer.echo(output)
    except ConfigError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None


@config_app.command(name="set")
def config_set(
    key: str = typer.Argument(help="Dotted config key (e.g. ai.provider)."),
    value: str = typer.Argument(help="Value to set."),
    config_path: str | None = typer.Option(None, "--config", "-c", help="Config file path."),
) -> None:
    """Set a configuration value by dotted key."""
    try:
        path = Path(config_path) if config_path else _find_config_path()
        overrides = _dotted_key_to_dict(key, value)
        config = load_config(config_path=path, overrides=overrides)
        save_config(config, path)
        typer.echo(f"Set {key} = {value}")
    except ConfigError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None


def _find_config_path() -> Path:
    """Find the config file path, defaulting to aat.config.yaml in cwd."""
    cwd = Path.cwd()
    candidate = cwd / DEFAULT_CONFIG_FILENAME
    if candidate.exists():
        return candidate
    candidate = cwd / ".aat" / DEFAULT_CONFIG_FILENAME
    if candidate.exists():
        return candidate
    return cwd / DEFAULT_CONFIG_FILENAME


def _dotted_key_to_dict(key: str, value: str) -> dict[str, Any]:
    """Convert a dotted key like 'ai.provider' to nested dict {'ai': {'provider': value}}."""
    parts = key.split(".")
    result: dict[str, Any] = {}
    current = result
    for part in parts[:-1]:
        current[part] = {}
        current = current[part]
    current[parts[-1]] = value
    return result
