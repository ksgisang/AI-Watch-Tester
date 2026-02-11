"""aat report — test report management (stub)."""

from __future__ import annotations

import typer

report_app = typer.Typer(
    name="report",
    help="Test report management commands.",
    no_args_is_help=True,
)


@report_app.command(name="list")
def report_list() -> None:
    """List available test reports."""
    typer.echo("Not yet implemented")


@report_app.command(name="show")
def report_show(
    path: str = typer.Argument(help="Report file path."),
) -> None:
    """Show a specific test report."""
    typer.echo(f"Not yet implemented: {path}")
