"""Tests for aat run command."""

from __future__ import annotations

from typing import cast

import click
import typer.main
from typer.testing import CliRunner

from aat.cli.commands.run_cmd import _exit_code
from aat.cli.main import app

runner = CliRunner()


def test_run_nonexistent_path() -> None:
    """aat run fails with a nonexistent scenario path."""
    result = runner.invoke(app, ["run", "/nonexistent/scenarios"])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_run_command_exists() -> None:
    """aat run is registered and shows help."""
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "scenarios" in result.output.lower() or "SCENARIOS_PATH" in result.output


def test_run_offers_no_learn() -> None:
    """The switch that turns remembered coordinates off is on the command.

    Read off the command rather than out of --help: the rendered help box is
    laid out for whatever terminal width the suite happens to run at, so a
    narrow one wraps or clips the option column and the switch vanishes from
    the text while still being perfectly usable.
    """
    group = cast(click.Group, typer.main.get_command(app))
    run_cmd = group.commands["run"]
    flags = {name for param in run_cmd.params for name in param.opts}
    assert "--no-learn" in flags


class TestExitCode:
    """What the process tells the pipeline that called it."""

    def test_clean_run_is_zero(self) -> None:
        assert (
            _exit_code(
                had_critical=False,
                total_failed=0,
                total_skipped=0,
                total_warned=0,
                strict_mode=False,
            )
            == 0
        )

    def test_a_step_that_changed_nothing_is_not_a_clean_exit(self) -> None:
        """The whole point: a warning must not leave the pipeline green."""
        assert (
            _exit_code(
                had_critical=False,
                total_failed=0,
                total_skipped=0,
                total_warned=1,
                strict_mode=False,
            )
            == 3
        )

    def test_a_real_failure_outranks_a_warning(self) -> None:
        assert (
            _exit_code(
                had_critical=False,
                total_failed=1,
                total_skipped=0,
                total_warned=2,
                strict_mode=False,
            )
            == 1
        )

    def test_critical_outranks_everything(self) -> None:
        assert (
            _exit_code(
                had_critical=True,
                total_failed=1,
                total_skipped=1,
                total_warned=1,
                strict_mode=True,
            )
            == 2
        )

    def test_skips_only_fail_under_strict(self) -> None:
        kwargs = {"had_critical": False, "total_failed": 0, "total_skipped": 2, "total_warned": 0}
        assert _exit_code(**kwargs, strict_mode=False) == 0
        assert _exit_code(**kwargs, strict_mode=True) == 1
