"""aat learned — learned element and pattern management."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from aat.core.config import load_config

learned_app = typer.Typer(
    name="learned",
    help="View and manage learned patterns.",
    no_args_is_help=True,
)


@learned_app.command(name="list")
def learned_list(
    config_path: str | None = typer.Option(None, "--config", "-c", help="Config file path."),
) -> None:
    """List learned elements and failure patterns."""
    try:
        cfg = load_config(config_path=Path(config_path) if config_path else None)
        data_dir = cfg.data_dir
    except Exception:
        data_dir = ".aat"

    db_path = Path(data_dir) / "learned.db"
    if not db_path.exists():
        typer.echo("No learned data yet. Run tests with --learn to start.")
        return

    from aat.learning.store import LearnedStore

    store = LearnedStore(db_path)

    # Elements
    rows: list[Any] = []
    try:
        cursor = store._conn.execute(
            "SELECT target_name, use_count, updated_at "
            "FROM learned_elements ORDER BY use_count DESC LIMIT 20"
        )
        rows = cursor.fetchall()
        if rows:
            typer.echo("\n  Learned Elements:")
            typer.echo(f"  {'Target':<30} {'Uses':>5} {'Last Used':<20}")
            typer.echo("  " + "-" * 57)
            for r in rows:
                typer.echo(
                    f"  {r['target_name']:<30} {r['use_count']:>5} {r['updated_at'][:19]:<20}"
                )
    except Exception:
        pass

    # Remembered coordinates — these are what a click falls back to when the
    # scenario gives no selector, so they have to be inspectable from the CLI.
    coords = store.list_state_coords()
    if coords:
        typer.echo("\n  Remembered Coordinates:")
        typer.echo(f"  {'Target':<30} {'State':<12} {'Position':<12} {'Conf':>5} {'Uses':>5}")
        typer.echo("  " + "-" * 68)
        for c in coords:
            pos = f"({c['correct_x']},{c['correct_y']})"
            typer.echo(
                f"  {c['target_name'][:30]:<30} {c['page_state'][:12]:<12} "
                f"{pos:<12} {c['confidence']:>5.2f} {c['use_count']:>5}"
            )
        typer.echo('  Remove one with: aat learn reset "<target>"')

    # Failure patterns
    stats = store.get_failure_stats()
    if stats:
        typer.echo("\n  Failure Patterns:")
        typer.echo(f"  {'Type':<25} {'Hits':>5} {'Fixed':>6} {'Fix Description':<40}")
        typer.echo("  " + "-" * 78)
        for s in stats:
            fixed = "Yes" if s["fix_applied"] else "No"
            desc = (s["fix_description"] or "")[:40]
            typer.echo(f"  {s['error_type']:<25} {s['hit_count']:>5} {fixed:>6} {desc:<40}")

    # Platform patterns
    platforms = store.list_platform_patterns()
    if platforms:
        typer.echo("\n  Platform Tips:")
        for p in platforms:
            src = f"({p['source']})" if p["source"] != "builtin" else ""
            typer.echo(f"  [{p['platform']}] {p['tip']} {src}")

    if not rows and not coords and not stats and not platforms:
        typer.echo("No learned data yet. Run tests with --learn to start.")

    typer.echo()


@learned_app.command(name="clear")
def learned_clear(
    config_path: str | None = typer.Option(None, "--config", "-c", help="Config file path."),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Clear all learned data (elements, coordinates, failures, platform tips)."""
    try:
        cfg = load_config(config_path=Path(config_path) if config_path else None)
        data_dir = cfg.data_dir
    except Exception:
        data_dir = ".aat"

    db_path = Path(data_dir) / "learned.db"
    if not db_path.exists():
        typer.echo("No learned data to clear.")
        return

    if not confirm:
        proceed = typer.confirm(
            "Delete all learned elements, remembered coordinates, "
            "failure patterns, and platform tips?"
        )
        if not proceed:
            typer.echo("Cancelled.")
            return

    from aat.learning.store import LearnedStore

    store = LearnedStore(db_path)
    store._conn.execute("DELETE FROM learned_elements")
    store._conn.execute("DELETE FROM state_coords")
    store._conn.execute("DELETE FROM failure_patterns")
    store._conn.execute("DELETE FROM platform_patterns")
    store._conn.commit()
    typer.echo(typer.style("  ✓ All learned data cleared.", fg=typer.colors.GREEN))
