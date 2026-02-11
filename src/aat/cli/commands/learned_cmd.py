"""aat learned — learned element management (stub)."""

from __future__ import annotations

import typer

learned_app = typer.Typer(
    name="learned",
    help="Learned element management commands.",
    no_args_is_help=True,
)


@learned_app.command(name="list")
def learned_list() -> None:
    """List learned elements."""
    typer.echo("Not yet implemented")


@learned_app.command(name="clear")
def learned_clear() -> None:
    """Clear all learned elements."""
    typer.echo("Not yet implemented")
