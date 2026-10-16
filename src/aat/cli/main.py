"""AAT CLI entry point."""

import json
import time
from pathlib import Path

import typer

app = typer.Typer(
    name="aat",
    help="AAT — AI-powered DevQA Loop Orchestrator",
    no_args_is_help=True,
)

_UPDATE_CHECK_INTERVAL = 86400  # 24 hours
_UPDATE_CACHE = Path.home() / ".aat" / "update_check.json"
_SKILL_RELEASES_URL = "https://api.github.com/repos/ksgisang/awt-skill/releases/latest"


def _check_skill_update() -> None:
    """Check for AWT skill updates (once per day, non-blocking)."""
    try:
        _UPDATE_CACHE.parent.mkdir(parents=True, exist_ok=True)

        # Read cache
        last_check = 0.0
        cached_version = ""
        if _UPDATE_CACHE.exists():
            data = json.loads(_UPDATE_CACHE.read_text(encoding="utf-8"))
            last_check = data.get("last_check", 0.0)
            cached_version = data.get("latest", "")

        now = time.time()
        if now - last_check < _UPDATE_CHECK_INTERVAL:
            # Use cached result
            if cached_version:
                _show_update_hint(cached_version)
            return

        # Fetch latest release (timeout 3s — don't slow down CLI)
        import urllib.request

        req = urllib.request.Request(
            _SKILL_RELEASES_URL,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310
            release = json.loads(resp.read().decode())
        latest = release.get("tag_name", "").lstrip("v")

        # Cache result
        _UPDATE_CACHE.write_text(
            json.dumps({"last_check": now, "latest": latest}),
            encoding="utf-8",
        )

        if latest:
            _show_update_hint(latest)
    except Exception:
        pass  # Never fail the CLI due to update check


def _show_update_hint(latest: str) -> None:
    """Show update hint if a newer version is available."""
    from aat import __version__

    if latest and latest != __version__ and latest > __version__:
        typer.echo(
            typer.style(
                f"  💡 AWT update available: v{__version__} → v{latest}. "
                "Update the CLI: pip install -U aat-devqa",
                fg=typer.colors.YELLOW,
            )
        )


def version_callback(value: bool) -> None:
    if value:
        from aat import __version__

        typer.echo(f"aat {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """AAT — AI-powered DevQA Loop Orchestrator."""
    _check_skill_update()


# -- Register commands --------------------------------------------------------

from aat.cli.commands.analyze_cmd import analyze_command  # noqa: E402

# Visual regression commands
from aat.cli.commands.baseline_cmd import baseline_app  # noqa: E402
from aat.cli.commands.config_cmd import config_app  # noqa: E402
from aat.cli.commands.cost_cmd import cost_app  # noqa: E402
from aat.cli.commands.dashboard_cmd import dashboard_command  # noqa: E402
from aat.cli.commands.devqa_cmd import devqa_command  # noqa: E402
from aat.cli.commands.diff_cmd import diff_command  # noqa: E402
from aat.cli.commands.doctor_cmd import doctor_command  # noqa: E402
from aat.cli.commands.generate_cmd import generate_command  # noqa: E402
from aat.cli.commands.hook_cmd import hook_app  # noqa: E402
from aat.cli.commands.init_cmd import init_command  # noqa: E402
from aat.cli.commands.learn_cmd import learn_app  # noqa: E402
from aat.cli.commands.learned_cmd import learned_app  # noqa: E402
from aat.cli.commands.loop_cmd import loop_command  # noqa: E402
from aat.cli.commands.report_cmd import report_app  # noqa: E402
from aat.cli.commands.run_cmd import run_command  # noqa: E402
from aat.cli.commands.scan_cmd import scan_command  # noqa: E402
from aat.cli.commands.serve_cmd import serve_command  # noqa: E402
from aat.cli.commands.setup_cmd import setup_command  # noqa: E402
from aat.cli.commands.snapshot_cmd import snapshot_command  # noqa: E402
from aat.cli.commands.start_cmd import start_command  # noqa: E402
from aat.cli.commands.validate_cmd import validate_command  # noqa: E402
from aat.cli.commands.watch_cmd import watch_command  # noqa: E402

app.command(name="setup")(setup_command)
app.command(name="doctor")(doctor_command)
app.command(name="start")(start_command)
app.command(name="serve")(serve_command)
app.command(name="dashboard")(dashboard_command)
app.command(name="init")(init_command)
app.add_typer(config_app, name="config")
app.add_typer(cost_app, name="cost")
app.command(name="validate")(validate_command)
app.command(name="run")(run_command)
app.command(name="analyze")(analyze_command)
app.command(name="generate")(generate_command)
app.command(name="loop")(loop_command)
app.add_typer(report_app, name="report")
app.add_typer(learn_app, name="learn")
app.add_typer(learned_app, name="learned")
app.command(name="scan")(scan_command)
app.command(name="devqa")(devqa_command)
app.add_typer(hook_app, name="hook")

# Visual regression
app.command(name="snapshot")(snapshot_command)
app.command(name="diff")(diff_command)
app.add_typer(baseline_app, name="baseline")
app.command(name="watch")(watch_command)
