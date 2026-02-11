"""aat init — project initialization."""

from __future__ import annotations

from pathlib import Path

import typer

from aat.core.config import save_config
from aat.core.models import Config

_GITIGNORE_ENTRIES = """\

# AAT data
.aat/config.yaml
.aat/learned.db
.aat/screenshots/
reports/
"""


def init_command(
    name: str = typer.Option("aat-project", "--name", "-n", help="Project name."),
    source: str = typer.Option(".", "--source", "-s", help="Source path."),
    url: str = typer.Option("", "--url", "-u", help="Application URL."),
) -> None:
    """Initialize a new AAT project in the current directory."""
    root = Path.cwd()

    # Create .aat/ directory
    aat_dir = root / ".aat"
    aat_dir.mkdir(parents=True, exist_ok=True)

    # Create scenarios/ directory
    scenarios_dir = root / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)

    # Build config and save
    config = Config(
        project_name=name,
        source_path=source,
        url=url,
    )
    config_path = root / "aat.config.yaml"
    save_config(config, config_path)

    # Append to .gitignore if it exists
    gitignore_path = root / ".gitignore"
    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8")
        if ".aat/config.yaml" not in existing:
            with open(gitignore_path, "a", encoding="utf-8") as f:  # noqa: PTH123
                f.write(_GITIGNORE_ENTRIES)

    typer.echo(f"AAT project '{name}' initialized successfully.")
    typer.echo(f"  Config: {config_path}")
    typer.echo(f"  Scenarios: {scenarios_dir}")
