"""aat start — Interactive guided mode.

Walks the user through the entire AAT workflow:
  Setup → Document Analysis → Scenario Generation → Test → Loop → Report
"""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path
from typing import Any

import typer
import yaml

from aat.adapters import ADAPTER_REGISTRY
from aat.core.config import load_config, save_config
from aat.core.connection import test_ai_connection, test_url
from aat.core.events import CLIEventHandler
from aat.core.exceptions import AATError
from aat.core.loop import DevQALoop
from aat.core.models import Config
from aat.core.scenario_loader import load_scenarios
from aat.engine import ENGINE_REGISTRY
from aat.engine.comparator import Comparator
from aat.engine.executor import StepExecutor
from aat.engine.humanizer import Humanizer
from aat.engine.waiter import Waiter
from aat.matchers import MATCHER_REGISTRY
from aat.matchers.hybrid import HybridMatcher
from aat.reporters import REPORTER_REGISTRY

# -- Cancellation flag -------------------------------------------------------

_cancelled = False


def _on_cancel(signum: int, frame: Any) -> None:
    """Handle Ctrl+C for graceful cancellation."""
    global _cancelled  # noqa: PLW0603
    _cancelled = True
    typer.echo(
        typer.style(
            "\n\n  Test cancelled by user. Saving partial results...", fg=typer.colors.YELLOW
        ),
    )


# -- Main command -------------------------------------------------------------


def start_command(
    config_path: str | None = typer.Option(None, "--config", "-c", help="Config file path."),
) -> None:
    """Interactive guided mode: setup -> analyze -> test -> loop -> report."""
    try:
        asyncio.run(_start_guided(config_path))
    except KeyboardInterrupt:
        typer.echo("\nAborted.")
        raise typer.Exit(code=130) from None
    except AATError as e:
        typer.echo(
            typer.style(f"\nError: {e}", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(code=1) from None


async def _start_guided(config_path: str | None) -> None:
    """Run the full guided workflow."""
    global _cancelled  # noqa: PLW0603
    ev = CLIEventHandler()

    ev.section("AAT — AI Auto Tester")
    ev.info("Interactive guided mode. Press Ctrl+C at any time to cancel.\n")

    # ----------------------------------------------------------------
    # Step 1: AI Provider Setup
    # ----------------------------------------------------------------
    ev.section("Step 1/5: AI Provider Setup")

    provider = (
        ev.prompt(
            "Select AI provider",
            options=["claude", "openai", "ollama"],
        )
        .strip()
        .lower()
    )

    if provider not in ("claude", "openai", "ollama"):
        # Try to match by number
        provider = {"1": "claude", "2": "openai", "3": "ollama"}.get(provider, provider)

    if provider not in ADAPTER_REGISTRY:
        ev.error(f"Unknown provider: {provider}")
        raise typer.Exit(code=1)

    ev.info(f"  Provider: {provider}")

    # Model
    default_models = {
        "claude": "claude-sonnet-4-20250514",
        "openai": "gpt-4o",
        "ollama": "codellama:7b",
    }
    default_model = default_models.get(provider, "")
    model_input = ev.prompt(f"Model name (default: {default_model})").strip()
    model = model_input if model_input else default_model
    ev.info(f"  Model: {model}")

    # API key (skip for ollama)
    api_key = ""
    if provider != "ollama":
        api_key = ev.prompt(f"API key for {provider}").strip()
        if not api_key:
            ev.error("API key is required.")
            raise typer.Exit(code=1)

    # Build config
    cfg_path = Path(config_path) if config_path else None
    try:
        config = load_config(config_path=cfg_path)
    except Exception:
        config = Config()

    config.ai.provider = provider
    config.ai.model = model
    config.ai.api_key = api_key

    # Connection test
    ev.info("\n  Testing connection...")
    ok, msg = await test_ai_connection(config.ai)
    if ok:
        ev.success(msg)
    else:
        ev.error(msg)
        ev.error("Please check your settings and try again.")
        raise typer.Exit(code=1)

    # Save config
    save_path = cfg_path or Path(".aat/config.yaml")
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_config(config, save_path)
    ev.info(f"  Config saved: {save_path}")

    # ----------------------------------------------------------------
    # Step 2: Document Analysis
    # ----------------------------------------------------------------
    ev.section("Step 2/5: Document Analysis")

    doc_path_str = ev.prompt("Path to spec documents (file or folder, or 'skip' to skip)").strip()

    scenarios_from_docs: list[Any] = []

    if doc_path_str.lower() != "skip":
        doc_path = Path(doc_path_str)
        if not doc_path.exists():
            ev.error(f"Path does not exist: {doc_path}")
            raise typer.Exit(code=1)

        # Collect files
        files: list[Path] = []
        if doc_path.is_file():
            files = [doc_path]
        else:
            for ext in (".md", ".txt", ".markdown"):
                files.extend(doc_path.glob(f"*{ext}"))
            files.sort()

        if not files:
            ev.warning(f"No supported documents found in {doc_path}")
        else:
            ev.info(f"  Found {len(files)} document(s)")

            # Analyze each file
            adapter_cls = ADAPTER_REGISTRY[provider]
            adapter = adapter_cls(config.ai)

            from aat.parsers.markdown_parser import MarkdownParser

            parser = MarkdownParser()

            all_analysis: list[dict[str, Any]] = []

            for i, f in enumerate(files, 1):
                ev.progress(f"Analyzing {f.name}...", i, len(files))
                try:
                    text, images = await parser.parse(f)
                    result = await adapter.analyze_document(text, images)
                    all_analysis.append(result)
                    screens = len(result.get("screens", []))
                    elements = len(result.get("elements", []))
                    flows = len(result.get("flows", []))
                    ev.success(f"{f.name}: {screens} screens, {elements} elements, {flows} flows")
                except Exception as exc:
                    ev.warning(f"{f.name}: analysis failed — {exc}")

            total_screens = sum(len(a.get("screens", [])) for a in all_analysis)
            total_elements = sum(len(a.get("elements", [])) for a in all_analysis)
            total_flows = sum(len(a.get("flows", [])) for a in all_analysis)
            ev.info(
                f"\n  Analysis complete: "
                f"{total_screens} screens, {total_elements} elements, {total_flows} flows"
            )

            # Generate scenarios from documents
            gen_answer = ev.prompt("Generate test scenarios from these documents? [Y/n]").strip()
            if gen_answer.lower() != "n":
                ev.info("  Generating scenarios...")
                for f in files:
                    try:
                        text, images = await parser.parse(f)
                        from aat.core.models import Scenario

                        new_scenarios: list[Scenario] = await adapter.generate_scenarios(
                            text,
                            images,
                        )
                        scenarios_from_docs.extend(new_scenarios)
                    except Exception as exc:
                        ev.warning(f"  Scenario generation from {f.name} failed: {exc}")

                if scenarios_from_docs:
                    # Save scenarios
                    scenario_dir = Path(config.scenarios_dir)
                    scenario_dir.mkdir(parents=True, exist_ok=True)
                    for sc in scenarios_from_docs:
                        safe_name = sc.name.replace(" ", "_").lower()
                        filename = f"{sc.id}_{safe_name}.yaml"
                        out_path = scenario_dir / filename
                        data = sc.model_dump(mode="json")
                        with open(out_path, "w", encoding="utf-8") as fh:
                            yaml.safe_dump(
                                data,
                                fh,
                                default_flow_style=False,
                                allow_unicode=True,
                                sort_keys=False,
                            )
                    count = len(scenarios_from_docs)
                    ev.success(f"Generated {count} scenario(s) to {scenario_dir}")
                else:
                    ev.warning("No scenarios generated.")

    # ----------------------------------------------------------------
    # Step 3: Load Scenarios
    # ----------------------------------------------------------------
    ev.section("Step 3/5: Scenario Selection")

    scenario_path_str = ev.prompt(f"Scenario path (default: {config.scenarios_dir})").strip()
    scenario_path = Path(scenario_path_str) if scenario_path_str else Path(config.scenarios_dir)

    if not scenario_path.exists():
        ev.error(f"Scenario path does not exist: {scenario_path}")
        raise typer.Exit(code=1)

    scenarios = load_scenarios(scenario_path)
    ev.info(f"  Loaded {len(scenarios)} scenario(s):")
    for sc in scenarios:
        ev.info(f"    {sc.id} — {sc.name} ({len(sc.steps)} steps)")

    # ----------------------------------------------------------------
    # Step 4: Target URL
    # ----------------------------------------------------------------
    ev.section("Step 4/5: Test Target")

    target_url = ev.prompt("Target URL (e.g. http://localhost:3000)").strip()

    if target_url:
        ev.info("  Checking URL...")
        url_ok, url_msg = await test_url(target_url)
        if url_ok:
            ev.success(url_msg)
        else:
            ev.warning(url_msg)
            cont = ev.prompt("Continue anyway? [y/N]").strip()
            if cont.lower() != "y":
                raise typer.Exit(code=1)

    # ----------------------------------------------------------------
    # Step 5: Test Execution
    # ----------------------------------------------------------------
    ev.section("Step 5/5: Test Execution")

    # Install cancel handler
    original_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _on_cancel)
    _cancelled = False

    engine_cls = ENGINE_REGISTRY.get(config.engine.type)
    if engine_cls is None:
        ev.error(f"Unknown engine type: {config.engine.type}")
        raise typer.Exit(code=1)
    engine = engine_cls(config.engine)

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

    adapter_cls = ADAPTER_REGISTRY[provider]
    adapter = adapter_cls(config.ai)

    reporter_cls = REPORTER_REGISTRY.get("markdown")
    reporter = reporter_cls() if reporter_cls else None

    # -- Run test with event feedback --
    ev.info("\n  Starting test execution...\n")

    try:
        await engine.start()

        from aat.core.models import StepStatus, TestResult

        all_step_results: list[Any] = []
        total_steps = sum(len(sc.steps) for sc in scenarios)
        step_counter = 0

        for sc in scenarios:
            ev.info(f"\n  Scenario: {sc.id} — {sc.name}")

            for step_config in sc.steps:
                if _cancelled:
                    break

                step_counter += 1
                ev.step_start(step_counter, total_steps, step_config.description)

                step_result = await executor.execute_step(step_config)
                all_step_results.append(step_result)

                passed = step_result.status == StepStatus.PASSED
                ev.step_result(
                    step_counter,
                    passed,
                    step_config.description,
                    error=step_result.error_message,
                )

            if _cancelled:
                break

        # Build test result
        passed_count = sum(1 for s in all_step_results if s.status == StepStatus.PASSED)
        failed_count = sum(
            1 for s in all_step_results if s.status in (StepStatus.FAILED, StepStatus.ERROR)
        )

        test_result = TestResult(
            scenario_id=scenarios[0].id if scenarios else "SC-000",
            scenario_name=scenarios[0].name if scenarios else "Unknown",
            passed=failed_count == 0 and not _cancelled,
            steps=all_step_results,
            total_steps=len(all_step_results),
            passed_steps=passed_count,
            failed_steps=failed_count,
            duration_ms=sum(s.elapsed_ms for s in all_step_results),
        )

        # -- Results Summary --
        ev.section("Test Results")
        ev.info(f"  Total: {test_result.total_steps} steps")
        ev.info(f"  Passed: {test_result.passed_steps}")
        ev.info(f"  Failed: {test_result.failed_steps}")

        if _cancelled:
            ev.warning("Test was cancelled by user.")
            # Generate partial report
            if reporter:
                output_dir = Path(config.reports_dir)
                await reporter.generate(test_result, output_dir)
                ev.info(f"  Partial report saved to: {output_dir}")
        elif test_result.passed:
            ev.success("All tests passed!")
            if reporter:
                output_dir = Path(config.reports_dir)
                await reporter.generate(test_result, output_dir)
                ev.info(f"  Report saved to: {output_dir}")
        else:
            ev.warning(f"{test_result.failed_steps} step(s) failed.")

            # -- DevQA Loop --
            loop_answer = ev.prompt(
                "Start DevQA Loop? AI will analyze failures and suggest fixes. [Y/n]"
            ).strip()

            if loop_answer.lower() != "n" and reporter:
                max_loops_str = ev.prompt(
                    f"Max loop iterations (default: {config.max_loops})"
                ).strip()
                if max_loops_str.isdigit():
                    config.max_loops = int(max_loops_str)

                def _approval_callback(analysis_text: str) -> bool:
                    if _cancelled:
                        return False
                    ev.info(f"\n  AI Analysis: {analysis_text}")
                    answer = ev.prompt("Approve this fix? [Y/n]").strip()
                    return answer.lower() != "n"

                loop = DevQALoop(
                    config=config,
                    executor=executor,
                    adapter=adapter,
                    reporter=reporter,
                    engine=engine,
                    approval_callback=_approval_callback,
                )

                # Engine already started — use skip_engine_lifecycle
                loop_result = await loop.run(
                    scenarios,
                    skip_engine_lifecycle=True,
                )

                ev.section("DevQA Loop Results")
                if loop_result.success:
                    ev.success(
                        f"All tests passed after {loop_result.total_iterations} iteration(s)!"
                    )
                else:
                    ev.warning(
                        f"Loop ended after {loop_result.total_iterations} iteration(s). "
                        f"Reason: {loop_result.reason}"
                    )
                ev.info(f"  Duration: {loop_result.duration_ms:.0f}ms")

    finally:
        await engine.stop()
        signal.signal(signal.SIGINT, original_handler)

    ev.section("Done!")
    ev.info("  Test session complete. Thank you for using AAT!")
