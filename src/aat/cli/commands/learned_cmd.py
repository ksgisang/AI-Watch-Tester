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

    # The database and the picture store are independent. A run that never
    # learned a coordinate writes no `learned.db`, so returning early when the
    # file is missing would hide every banked picture behind "no learned data"
    # -- a report that contradicts the disk.
    db_path = Path(data_dir) / "learned.db"
    rows: list[Any] = []
    coords: list[Any] = []
    stats: list[Any] = []
    platforms: list[Any] = []

    if db_path.exists():
        rows, coords, stats, platforms = _print_db_sections(db_path)

    # Banked element pictures — the other half of what AWT remembers, and the
    # one that decides whether a broken selector heals or fails.
    templates = _template_inventory()
    if templates:
        typer.echo("\n  Banked Element Pictures:")
        typer.echo(f"  {'Host':<24} {'Target':<24} {'Size':<11} {'Age':>7}")
        typer.echo("  " + "-" * 68)
        for t in templates[:20]:
            size = f"{t.width}x{t.height}"
            age = f"{t.age_days:.1f}d" if t.saved_at else "?"
            typer.echo(f"  {t.scope[:24]:<24} {t.target[:24]:<24} {size:<11} {age:>7}")
        if len(templates) > 20:
            typer.echo(f"  … and {len(templates) - 20} more")
        typer.echo("  Remove them with: aat learned clear --templates")

    if not rows and not coords and not stats and not platforms and not templates:
        typer.echo("No learned data yet. Run tests with --learn to start.")

    typer.echo()


def _print_db_sections(
    db_path: Path,
) -> tuple[list[Any], list[Any], list[Any], list[Any]]:
    """Print everything the learning database holds, and report what was there."""
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
        typer.echo(
            f"  {'Target':<26} {'State':<10} {'Host':<22} {'Position':<12} {'Conf':>5} {'Uses':>5}"
        )
        typer.echo("  " + "-" * 84)
        legacy = 0
        for c in coords:
            pos = f"({c['correct_x']},{c['correct_y']})"
            # A row with no host predates host scoping, so nothing will reuse it.
            # Saying "(not reused)" rather than printing an empty column keeps the
            # listing from implying the position is still live.
            host = c.get("host") or ""
            if not host:
                legacy += 1
                host_label = "(not reused)"
            else:
                host_label = host[:22]
            typer.echo(
                f"  {c['target_name'][:26]:<26} {c['page_state'][:10]:<10} {host_label:<22} "
                f"{pos:<12} {c['confidence']:>5.2f} {c['use_count']:>5}"
            )
        typer.echo('  Remove one with: aat learn reset "<target>"')
        if legacy:
            typer.echo(
                f"  {legacy} row(s) predate host scoping and are never reused "
                "— clear them with: aat learn reset --all"
            )

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

    return list(rows), list(coords), list(stats), list(platforms)


def _template_inventory() -> list[Any]:
    """Banked pictures, or an empty list if the store is unreadable.

    Listing learned data must not fail because of the template store: it is a
    cache of screenshots, and a report about what AWT remembers is more useful
    partially than not at all.
    """
    try:
        from aat.matchers import template_store

        return list(template_store.inventory())
    except Exception:
        return []


@learned_app.command(name="clear")
def learned_clear(
    config_path: str | None = typer.Option(None, "--config", "-c", help="Config file path."),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    templates: bool = typer.Option(
        False,
        "--templates",
        help="Clear banked element pictures instead of the learning database.",
    ),
    host: str | None = typer.Option(
        None,
        "--host",
        help="With --templates, clear only one host (e.g. localhost:3000).",
    ),
) -> None:
    """Clear all learned data (elements, coordinates, failures, platform tips)."""
    if templates:
        _clear_templates(host, confirm=confirm)
        return

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


def _clear_templates(host: str | None, *, confirm: bool) -> None:
    """Delete banked element pictures, optionally for one host only.

    Separate from the database clear because the two answer different
    questions. "AWT clicks the wrong place" is coordinates; "AWT heals to the
    wrong element" is a picture. Clearing both when the user asked about one
    throws away working knowledge.
    """
    from aat.matchers import template_store

    scope = template_store.scope_for_host(host) if host else None
    found = template_store.inventory(scope)
    if not found:
        where = f" for {host}" if host else ""
        typer.echo(f"No banked element pictures{where}.")
        return

    if not confirm:
        where = f" for {host}" if host else ""
        proceed = typer.confirm(f"Delete {len(found)} banked element picture(s){where}?")
        if not proceed:
            typer.echo("Cancelled.")
            return

    removed = template_store.clear(scope)
    typer.echo(
        typer.style(
            f"  ✓ {removed} banked element picture(s) cleared "
            f"from {template_store.templates_root()}",
            fg=typer.colors.GREEN,
        )
    )
