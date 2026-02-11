"""aat run — single test execution (no loop)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import typer

from aat.core.config import load_config
from aat.core.exceptions import AATError
from aat.core.models import StepStatus
from aat.core.scenario_loader import load_scenarios
from aat.engine.comparator import Comparator
from aat.engine.executor import StepExecutor
from aat.engine.humanizer import Humanizer
from aat.engine.waiter import Waiter
from aat.engine.web import WebEngine
from aat.matchers import MATCHER_REGISTRY
from aat.matchers.hybrid import HybridMatcher


def run_command(
    scenarios_path: str = typer.Argument(help="Scenario file or directory path."),
    config_path: str | None = typer.Option(
        None, "--config", "-c", help="Config file path."
    ),
) -> None:
    """Run test scenarios."""
    try:
        asyncio.run(_run(scenarios_path, config_path))
    except AATError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None


async def _run(scenarios_path: str, config_path: str | None) -> None:
    """Execute scenarios asynchronously."""
    # Load config
    cfg_path = Path(config_path) if config_path else None
    config = load_config(config_path=cfg_path)

    # Load scenarios
    path = Path(scenarios_path)
    scenarios = load_scenarios(path)

    # Assemble components
    engine = WebEngine(config.engine)
    matchers = [
        MATCHER_REGISTRY[m.value](config.matching)  # type: ignore[call-arg]
        for m in config.matching.chain_order
        if m.value in MATCHER_REGISTRY
    ]
    hybrid = HybridMatcher(matchers, config.matching)
    humanizer = Humanizer(config.humanizer)
    waiter = Waiter()
    comparator = Comparator()
    executor = StepExecutor(engine, hybrid, humanizer, waiter, comparator)

    total_passed = 0
    total_failed = 0
    total_steps = 0

    try:
        await engine.start()

        for scenario in scenarios:
            typer.echo(f"\nScenario: {scenario.id} — {scenario.name}")
            scenario_start = time.monotonic()

            for step in scenario.steps:
                result = await executor.execute_step(step)
                total_steps += 1

                if result.status == StepStatus.PASSED:
                    total_passed += 1
                    status_str = typer.style("PASSED", fg=typer.colors.GREEN)
                else:
                    total_failed += 1
                    status_str = typer.style(str(result.status.value).upper(), fg=typer.colors.RED)

                typer.echo(
                    f"  Step {result.step}: {status_str} "
                    f"({result.elapsed_ms:.0f}ms)"
                )

                if result.error_message:
                    typer.echo(f"    Error: {result.error_message}")

            scenario_elapsed = (time.monotonic() - scenario_start) * 1000
            typer.echo(f"  Scenario completed in {scenario_elapsed:.0f}ms")

    finally:
        await engine.stop()

    # Summary
    typer.echo(f"\nSummary: {total_passed} passed, {total_failed} failed, {total_steps} total")

    if total_failed > 0:
        raise typer.Exit(code=1)
