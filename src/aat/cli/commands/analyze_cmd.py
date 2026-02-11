"""aat analyze — document AI analysis."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING

import typer

from aat.core.config import load_config
from aat.core.exceptions import AATError

if TYPE_CHECKING:
    from typing import Any


def analyze_command(
    file_path: str = typer.Argument(..., help="Document file to analyze (.md, .txt)"),
    config_path: str | None = typer.Option(None, "--config", "-c", help="Config file path."),
) -> None:
    """Analyze a spec document using AI."""
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
        asyncio.run(_analyze(source, config_path))
    except AATError as e:
        typer.echo(
            typer.style(f"Error: {e}", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(code=1) from None


async def _analyze(source: Path, config_path: str | None) -> None:
    """Run document analysis asynchronously."""
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

    # Create adapter and analyze
    adapter = _get_adapter(config)
    if adapter is None:
        typer.echo(
            typer.style("No AI adapter available.", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(code=1)

    result: dict[str, Any] = await adapter.analyze_document(text, images)

    # Print results
    screens = result.get("screens", [])
    elements = result.get("elements", [])
    flows = result.get("flows", [])

    typer.echo("\nAnalysis Results:")
    typer.echo(f"  Screens:  {len(screens)}")
    typer.echo(f"  Elements: {len(elements)}")
    typer.echo(f"  Flows:    {len(flows)}")

    # Save result to .aat/analysis/
    data_dir = Path(config.data_dir)
    analysis_dir = data_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    output_file = analysis_dir / f"{source.stem}_analysis.json"
    with open(output_file, "w", encoding="utf-8") as f:  # noqa: PTH123
        json.dump(result, f, indent=2, ensure_ascii=False)

    typer.echo(f"\nSaved analysis to: {output_file}")


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
