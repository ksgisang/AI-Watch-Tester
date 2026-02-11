"""aat generate — AI scenario generation."""

from __future__ import annotations

import asyncio
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

import typer
import yaml

from aat.core.config import load_config
from aat.core.exceptions import AATError

if TYPE_CHECKING:
    from typing import Any


def generate_command(
    file_path: str | None = typer.Option(
        None, "--from", "-f", help="Source document file."
    ),
    config_path: str | None = typer.Option(
        None, "--config", "-c", help="Config file path."
    ),
    output_dir: str | None = typer.Option(
        None, "--output", "-o", help="Output directory for scenarios."
    ),
) -> None:
    """Generate test scenarios from spec document using AI."""
    if file_path is None:
        typer.echo(
            typer.style(
                "Error: --from / -f is required. Provide a source document.",
                fg=typer.colors.RED,
            ),
            err=True,
        )
        raise typer.Exit(code=1)

    source = Path(file_path)
    if not source.exists():
        typer.echo(
            typer.style(f"File does not exist: {file_path}", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(code=1)

    if not source.is_file():
        typer.echo(
            typer.style(f"Path is not a file: {file_path}", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        asyncio.run(_generate(source, config_path, output_dir))
    except AATError as e:
        typer.echo(
            typer.style(f"Error: {e}", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(code=1) from None


async def _generate(
    source: Path,
    config_path: str | None,
    output_dir: str | None,
) -> None:
    """Run scenario generation asynchronously."""
    cfg_path = Path(config_path) if config_path else None
    config = load_config(config_path=cfg_path)

    # Get parser based on file extension
    parser = _get_parser(source.suffix.lower())
    if parser is None:
        typer.echo(
            typer.style(
                f"No parser available for extension: {source.suffix}",
                fg=typer.colors.RED,
            ),
            err=True,
        )
        raise typer.Exit(code=1)

    # Parse document
    text, images = await parser.parse(source)
    typer.echo(f"Parsed document: {source.name} ({len(text)} chars, {len(images)} images)")

    # Create adapter and generate scenarios
    adapter = _get_adapter(config)
    if adapter is None:
        typer.echo(
            typer.style("No AI adapter available.", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(code=1)

    from aat.core.models import Scenario  # noqa: TC001

    scenarios: list[Scenario] = await adapter.generate_scenarios(text, images)

    if not scenarios:
        typer.echo(
            typer.style("No scenarios generated.", fg=typer.colors.YELLOW),
        )
        return

    # Determine output directory
    dest_dir = Path(output_dir) if output_dir else Path(config.scenarios_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Save each scenario as YAML
    for scenario in scenarios:
        safe_name = scenario.name.replace(" ", "_").lower()
        filename = f"{scenario.id}_{safe_name}.yaml"
        out_path = dest_dir / filename

        data = scenario.model_dump(mode="json")
        with open(out_path, "w", encoding="utf-8") as f:  # noqa: PTH123
            yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        typer.echo(f"  Saved: {out_path}")

    count = typer.style(str(len(scenarios)), fg=typer.colors.GREEN)
    typer.echo(f"\nGenerated {count} scenario(s) to {dest_dir}")


def _get_parser(extension: str) -> Any:
    """Get a parser instance for the given file extension.

    Returns None if no parser is available.
    """
    try:
        from aat.parsers.markdown_parser import MarkdownParser

        parser = MarkdownParser()
        if extension in parser.supported_extensions:
            return parser
    except (ImportError, AttributeError):
        pass
    return None


def _get_adapter(config: Any) -> Any:
    """Get an AI adapter instance.

    Returns None if no adapter is available.
    """
    try:
        from aat.adapters.claude import ClaudeAdapter

        return ClaudeAdapter(config.ai)
    except (ImportError, AttributeError):
        return None
