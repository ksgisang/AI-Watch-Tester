"""AAT CLI entry point."""

import typer

app = typer.Typer(
    name="aat",
    help="AAT — AI-powered DevQA Loop Orchestrator",
    no_args_is_help=True,
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


# -- Register commands --------------------------------------------------------

from aat.cli.commands.analyze_cmd import analyze_command  # noqa: E402
from aat.cli.commands.config_cmd import config_app  # noqa: E402
from aat.cli.commands.dashboard_cmd import dashboard_command  # noqa: E402
from aat.cli.commands.generate_cmd import generate_command  # noqa: E402
from aat.cli.commands.init_cmd import init_command  # noqa: E402
from aat.cli.commands.learn_cmd import learn_app  # noqa: E402
from aat.cli.commands.learned_cmd import learned_app  # noqa: E402
from aat.cli.commands.loop_cmd import loop_command  # noqa: E402
from aat.cli.commands.report_cmd import report_app  # noqa: E402
from aat.cli.commands.run_cmd import run_command  # noqa: E402
from aat.cli.commands.start_cmd import start_command  # noqa: E402
from aat.cli.commands.validate_cmd import validate_command  # noqa: E402

app.command(name="start")(start_command)
app.command(name="dashboard")(dashboard_command)
app.command(name="init")(init_command)
app.add_typer(config_app, name="config")
app.command(name="validate")(validate_command)
app.command(name="run")(run_command)
app.command(name="analyze")(analyze_command)
app.command(name="generate")(generate_command)
app.command(name="loop")(loop_command)
app.add_typer(report_app, name="report")
app.add_typer(learn_app, name="learn")
app.add_typer(learned_app, name="learned")
