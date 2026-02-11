"""aat validate — scenario YAML validation."""

from __future__ import annotations

from pathlib import Path

import typer

from aat.core.exceptions import ScenarioError
from aat.core.scenario_loader import load_scenario


def validate_command(
    path: str = typer.Argument(help="Scenario file or directory path."),
) -> None:
    """Validate scenario YAML files."""
    scenario_path = Path(path)

    if not scenario_path.exists():
        typer.echo(
            typer.style(f"Path does not exist: {path}", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(code=1)

    # Collect files
    if scenario_path.is_file():
        files = [scenario_path]
    else:
        files = sorted(
            f
            for f in scenario_path.rglob("*")
            if f.suffix in (".yaml", ".yml") and f.is_file()
        )

    if not files:
        typer.echo(
            typer.style(f"No YAML files found in: {path}", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(code=1)

    errors: list[str] = []
    for file in files:
        try:
            load_scenario(file)
            status = typer.style("OK", fg=typer.colors.GREEN)
            typer.echo(f"  {file.name}: {status}")
        except ScenarioError as e:
            status = typer.style("ERROR", fg=typer.colors.RED)
            typer.echo(f"  {file.name}: {status} - {e}")
            errors.append(file.name)

    typer.echo("")
    total = len(files)
    passed = total - len(errors)
    typer.echo(f"Validated {total} file(s): {passed} OK, {len(errors)} ERROR")

    if errors:
        raise typer.Exit(code=1)
