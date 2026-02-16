"""aat serve — Single-command launcher for dashboard + worker."""

from __future__ import annotations

import webbrowser
from pathlib import Path

import typer


def serve_command(
    config_path: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Config file path.",
    ),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Bind host."),
    port: int = typer.Option(8420, "--port", "-p", help="Bind port."),
    no_open: bool = typer.Option(
        False,
        "--no-open",
        help="Don't open browser automatically.",
    ),
) -> None:
    """Launch AAT dashboard (single process, no terminal needed).

    Alias for 'aat dashboard'. Starts the web UI on http://host:port.
    All test execution happens inside this process — no separate terminal required.
    """
    try:
        import uvicorn  # type: ignore[import-not-found]
    except ImportError:
        typer.echo(
            "Dashboard requires web extras: pip install aat-devqa[web]",
            err=True,
        )
        raise typer.Exit(code=1) from None

    from aat.dashboard.app import create_app

    cfg_path = Path(config_path) if config_path else None
    app = create_app(config_path=cfg_path)

    url = f"http://{host}:{port}"
    typer.echo(f"AAT Dashboard: {url}")
    typer.echo("All operations run inside this process. Open the URL in your browser.")

    if not no_open:
        webbrowser.open(url)

    uvicorn.run(app, host=host, port=port, log_level="info")
