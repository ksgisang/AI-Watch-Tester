"""aat loop — DevQA Loop execution."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from aat.adapters import ADAPTER_REGISTRY
from aat.core.config import load_config
from aat.core.exceptions import AATError
from aat.core.loop import DevQALoop
from aat.core.scenario_loader import load_scenarios
from aat.engine.comparator import Comparator
from aat.engine.executor import StepExecutor
from aat.engine.humanizer import Humanizer
from aat.engine.waiter import Waiter
from aat.engine.web import WebEngine
from aat.matchers import MATCHER_REGISTRY
from aat.matchers.hybrid import HybridMatcher
from aat.reporters import REPORTER_REGISTRY


def loop_command(
    scenarios_path: str = typer.Argument(help="Scenario file or directory path."),
    config_path: str | None = typer.Option(
        None, "--config", "-c", help="Config file path."
    ),
    max_loops: int | None = typer.Option(
        None, "--max-loops", "-m", help="Maximum loop iterations."
    ),
) -> None:
    """Run the DevQA Loop: test -> analyze -> fix -> re-test."""
    try:
        asyncio.run(_loop(scenarios_path, config_path, max_loops))
    except AATError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None


async def _loop(
    scenarios_path: str,
    config_path: str | None,
    max_loops: int | None,
) -> None:
    """Execute the DevQA Loop asynchronously."""
    # Load config
    cfg_path = Path(config_path) if config_path else None
    overrides: dict[str, object] = {}
    if max_loops is not None:
        overrides["max_loops"] = max_loops
    config = load_config(config_path=cfg_path, overrides=overrides)

    # Load scenarios
    path = Path(scenarios_path)
    scenarios = load_scenarios(path)

    # Assemble engine
    engine = WebEngine(config.engine)

    # Assemble matchers
    matchers = [
        MATCHER_REGISTRY[m.value](config.matching)  # type: ignore[call-arg]
        for m in config.matching.chain_order
        if m.value in MATCHER_REGISTRY
    ]
    hybrid = HybridMatcher(matchers, config.matching)

    # Assemble executor
    humanizer = Humanizer(config.humanizer)
    waiter = Waiter()
    comparator = Comparator()
    executor = StepExecutor(engine, hybrid, humanizer, waiter, comparator)

    # Assemble AI adapter
    adapter_cls = ADAPTER_REGISTRY.get(config.ai.provider)
    if adapter_cls is None:
        msg = f"Unknown AI adapter: {config.ai.provider}"
        raise AATError(msg)
    adapter = adapter_cls(config.ai)

    # Assemble reporter
    reporter_cls = REPORTER_REGISTRY.get("markdown")
    if reporter_cls is None:
        msg = "Markdown reporter not found"
        raise AATError(msg)
    reporter = reporter_cls()

    # Create and run loop
    loop = DevQALoop(
        config=config,
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
    )

    result = await loop.run(scenarios)

    # Print summary
    status = "SUCCESS" if result.success else "FAILURE"
    typer.echo(f"\nLoop {status} after {result.total_iterations} iteration(s)")
    typer.echo(f"Duration: {result.duration_ms:.0f}ms")

    if result.reason:
        typer.echo(f"Reason: {result.reason}")

    if not result.success:
        raise typer.Exit(code=1)
