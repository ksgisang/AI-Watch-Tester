"""aat loop — DevQA Loop execution with rich UX."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from aat.adapters import ADAPTER_REGISTRY
from aat.core.config import load_config
from aat.core.cost import load_cost_log
from aat.core.exceptions import AATError, ReporterError
from aat.core.git_ops import GitOps
from aat.core.loop import DevQALoop
from aat.core.models import ApprovalMode, StepStatus
from aat.core.scenario_loader import load_scenarios
from aat.engine import ENGINE_REGISTRY
from aat.engine.comparator import Comparator
from aat.engine.executor import StepExecutor
from aat.engine.humanizer import Humanizer
from aat.engine.waiter import Waiter
from aat.matchers import MATCHER_REGISTRY
from aat.matchers.hybrid import HybridMatcher
from aat.reporters import build_reporter

if TYPE_CHECKING:
    from aat.core.models import (
        AnalysisResult,
        FixResult,
        TestResult,
    )

# -- Auto-apply tracking (session-level) -----------------------------------

_auto_apply_types: set[str] = set()


# -- Rich output helpers ---------------------------------------------------


def _print_failure_report(test_result: TestResult) -> None:
    """Print detailed failure report with step-by-step results."""
    typer.echo()
    typer.echo("  " + "=" * 55)
    typer.echo(
        typer.style(
            "  ❌ TEST FAILED",
            fg=typer.colors.RED,
            bold=True,
        )
    )
    typer.echo("  " + "=" * 55)

    for sr in test_result.steps:
        if sr.status == StepStatus.PASSED:
            mark = typer.style("✓", fg=typer.colors.GREEN)
            typer.echo(f"  {mark} Step {sr.step}: {sr.description}")
        elif sr.status == StepStatus.FAILED:
            mark = typer.style("✗", fg=typer.colors.RED)
            typer.echo(
                typer.style(
                    f"  {mark} Step {sr.step}: {sr.description} — FAILED",
                    fg=typer.colors.RED,
                    bold=True,
                )
            )
            if sr.error_message:
                typer.echo(f"    Error: {sr.error_message}")
        else:
            typer.echo(f"  - Step {sr.step}: {sr.description} ({sr.status.value})")


def _print_analysis(analysis: AnalysisResult) -> None:
    """Print AI failure analysis."""
    typer.echo()
    typer.echo(
        typer.style(
            "  📍 Cause Analysis",
            fg=typer.colors.YELLOW,
            bold=True,
        )
    )
    typer.echo(f"    Cause: {analysis.cause}")
    if analysis.related_files:
        typer.echo(f"    Files: {', '.join(analysis.related_files)}")
    typer.echo()
    typer.echo(
        typer.style(
            "  💡 Suggested Fix",
            fg=typer.colors.CYAN,
            bold=True,
        )
    )
    typer.echo(f"    {analysis.suggestion}")
    typer.echo(f"    Severity: {analysis.severity.value}")


def _print_fix_diff(fix: FixResult) -> None:
    """Print fix changes in diff format."""
    typer.echo()
    for change in fix.files_changed:
        typer.echo(typer.style(f"  📄 {change.path}", bold=True))
        if change.description:
            typer.echo(f"    {change.description}")
        typer.echo()
        # Show diff
        original_lines = change.original.splitlines()
        modified_lines = change.modified.splitlines()
        for line in original_lines:
            typer.echo(typer.style(f"  - {line}", fg=typer.colors.RED))
        for line in modified_lines:
            typer.echo(typer.style(f"  + {line}", fg=typer.colors.GREEN))
        typer.echo()


def _print_retest_result(test_result: TestResult) -> None:
    """Print retest result summary."""
    typer.echo()
    if test_result.passed:
        typer.echo("  " + "=" * 55)
        typer.echo(
            typer.style(
                "  ✅ RETEST PASSED — All steps green!",
                fg=typer.colors.GREEN,
                bold=True,
            )
        )
        typer.echo("  " + "=" * 55)
    else:
        typer.echo(
            typer.style(
                "  ⚠️  RETEST — Some steps still failing",
                fg=typer.colors.YELLOW,
                bold=True,
            )
        )
        for sr in test_result.steps:
            if sr.status == StepStatus.FAILED:
                typer.echo(
                    typer.style(
                        f"    ✗ Step {sr.step}: {sr.description}",
                        fg=typer.colors.RED,
                    )
                )
            elif sr.status == StepStatus.PASSED:
                typer.echo(
                    typer.style(
                        f"    ✓ Step {sr.step}: {sr.description}",
                        fg=typer.colors.GREEN,
                    )
                )


# -- Rich approval callback -----------------------------------------------


def _rich_approval_callback(prompt_text: str) -> bool:
    """Rich approval menu with 5 options.

    Called by DevQALoop._handle_manual when a fix is proposed.
    The prompt_text contains "cause — suggestion" from the analysis.
    """
    typer.echo()
    typer.echo("  " + "-" * 55)
    typer.echo(
        typer.style(
            "  Apply this fix?",
            bold=True,
        )
    )
    typer.echo("    1. Yes")
    typer.echo("    2. Yes, and auto-apply similar fixes")
    typer.echo("    3. No")
    typer.echo("    4. Show diff")
    typer.echo("    5. Explain")
    typer.echo()

    while True:
        choice = typer.prompt("  >", default="1")

        if choice == "1":
            return True
        elif choice == "2":  # noqa: RET505
            # Mark this failure type for auto-apply
            # Extract failure type from prompt text (before " — ")
            parts = prompt_text.split(" — ", 1)
            if parts:
                _auto_apply_types.add(parts[0].strip().lower()[:50])
            typer.echo(
                typer.style(
                    "    ✓ Similar fixes will be auto-applied",
                    fg=typer.colors.GREEN,
                )
            )
            return True
        elif choice == "3":
            return False
        elif choice == "4":
            # Show diff — parse embedded diff from prompt_text
            typer.echo()
            if "__FIX_DIFF__" in prompt_text:
                typer.echo(typer.style("  📋 Code Changes:", bold=True))
                diff_part = prompt_text.split("__FIX_DIFF__", 1)[1]
                for line in diff_part.splitlines():
                    line = line.rstrip()
                    if line.startswith("FILE: "):
                        typer.echo(typer.style(f"\n  📄 {line[6:]}", bold=True))
                    elif line.startswith("DESC: "):
                        typer.echo(f"    {line[6:]}")
                    elif line.startswith("- "):
                        typer.echo(typer.style(f"  {line}", fg=typer.colors.RED))
                    elif line.startswith("+ "):
                        typer.echo(typer.style(f"  {line}", fg=typer.colors.GREEN))
                    elif line == "---":
                        typer.echo()
            else:
                typer.echo(typer.style("  📋 Fix Details:", bold=True))
                desc = prompt_text.split(" — ", 1)
                typer.echo(f"    Cause: {desc[0]}")
                if len(desc) > 1:
                    typer.echo(f"    Fix: {desc[1]}")
                typer.echo("    (No source code changes — text fix only)")
            typer.echo()
            continue
        elif choice == "5":
            # Explain — reformat the analysis for non-developers
            typer.echo()
            typer.echo(
                typer.style(
                    "  📖 Explanation (plain language):",
                    fg=typer.colors.CYAN,
                    bold=True,
                )
            )
            parts = prompt_text.split(" — ", 1)
            cause = parts[0] if parts else prompt_text
            suggestion = parts[1] if len(parts) > 1 else ""
            typer.echo(f"    Why it failed: {cause}")
            if suggestion:
                typer.echo(f"    What to do: {suggestion}")
            typer.echo(
                "    This means the test couldn't complete"
                " because something on the page changed"
                " or isn't working as expected."
            )
            typer.echo()
            continue
        else:
            typer.echo("    Invalid choice. Enter 1-5.")
            continue


# -- CLI command -----------------------------------------------------------


def loop_command(
    scenarios_path: str = typer.Argument(help="Scenario file or directory path."),
    config_path: str | None = typer.Option(None, "--config", "-c", help="Config file path."),
    max_loops: int | None = typer.Option(
        None, "--max-loops", "-m", help="Maximum loop iterations."
    ),
    approval_mode: str = typer.Option(
        "manual",
        "--approval-mode",
        "-a",
        help="Approval mode: manual | branch | auto.",
    ),
    report_format: str = typer.Option(
        "markdown",
        "--report-format",
        help="Report format: markdown | pdf (printable, screenshots embedded).",
    ),
    report_screenshots: str = typer.Option(
        "failures",
        "--report-screenshots",
        help=(
            "Which steps the PDF report illustrates: 'failures' (failed and "
            "warned steps), 'all' (every step that has a screenshot — use this "
            "to show what worked), or 'none'."
        ),
    ),
) -> None:
    """Run the DevQA Loop: test -> analyze -> fix -> re-test."""
    try:
        asyncio.run(
            _loop(
                scenarios_path,
                config_path,
                max_loops,
                approval_mode,
                report_format,
                report_screenshots,
            )
        )
    except AATError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None


async def _loop(
    scenarios_path: str,
    config_path: str | None,
    max_loops: int | None,
    approval_mode_str: str,
    report_format: str = "markdown",
    report_screenshots: str = "failures",
) -> None:
    """Execute the DevQA Loop asynchronously."""
    # Validate approval mode
    try:
        mode = ApprovalMode(approval_mode_str)
    except ValueError:
        msg = f"Invalid approval mode: {approval_mode_str}. Use: manual, branch, auto"
        raise AATError(msg) from None

    # Load config
    cfg_path = Path(config_path) if config_path else None
    overrides: dict[str, object] = {"approval_mode": mode}
    if max_loops is not None:
        overrides["max_loops"] = max_loops
    config = load_config(config_path=cfg_path, overrides=overrides)

    # Load scenarios
    path = Path(scenarios_path)
    scenarios = load_scenarios(path)

    # Assemble engine
    engine_cls = ENGINE_REGISTRY.get(config.engine.type)
    if engine_cls is None:
        msg = f"Unknown engine type: {config.engine.type}"
        raise AATError(msg)
    engine = engine_cls(config.engine)

    # Assemble matchers (3-tier hybrid with Vision AI)
    matchers = []
    for m in config.matching.chain_order:
        if m.value not in MATCHER_REGISTRY:
            continue
        if m.value == "vision_ai":
            vis = MATCHER_REGISTRY[m.value](  # type: ignore[call-arg]
                vision_config=config.vision,
                matching_config=config.matching,
                ai_config=config.ai,
            )
            matchers.append(vis)
        else:
            matchers.append(MATCHER_REGISTRY[m.value](config.matching))  # type: ignore[call-arg]
    if not any(m.name == "vision_ai" for m in matchers):
        from aat.matchers.vision_ai import VisionAIMatcher

        matchers.append(
            VisionAIMatcher(
                vision_config=config.vision,
                matching_config=config.matching,
                ai_config=config.ai,
            )
        )
    learned_store = None
    try:
        from aat.learning.store import LearnedStore

        learned_store = LearnedStore(Path(config.data_dir) / "learned.db")
    except Exception:
        pass
    hybrid = HybridMatcher(matchers, config.matching, learned_store=learned_store)

    # Assemble executor
    humanizer = Humanizer(config.humanizer)
    waiter = Waiter()
    comparator = Comparator()
    executor = StepExecutor(
        engine,
        hybrid,
        humanizer,
        waiter,
        comparator,
        learned_store=learned_store,
    )

    # Assemble AI adapter
    adapter_cls = ADAPTER_REGISTRY.get(config.ai.provider)
    if adapter_cls is None:
        msg = f"Unknown AI adapter: {config.ai.provider}"
        raise AATError(msg)
    adapter = adapter_cls(config.ai)

    # Assemble reporter
    try:
        reporter = build_reporter(report_format, report_screenshots)
    except ReporterError as exc:
        raise AATError(str(exc)) from exc

    # GitOps for branch mode
    git_ops: GitOps | None = None
    if mode == ApprovalMode.BRANCH:
        git_ops = GitOps(Path(config.source_path))

    # Header
    typer.echo()
    typer.echo("  " + "=" * 55)
    typer.echo(
        typer.style(
            "  🔄 DevQA Loop",
            fg=typer.colors.CYAN,
            bold=True,
        )
    )
    typer.echo(f"    Mode: {mode.value}")
    typer.echo(f"    Max iterations: {config.max_loops}")
    typer.echo(f"    Scenarios: {len(scenarios)}")
    typer.echo(f"    Provider: {config.ai.provider} ({config.ai.model})")
    typer.echo("  " + "=" * 55)

    # Create and run loop with rich callback
    loop = DevQALoop(
        config=config,
        executor=executor,
        adapter=adapter,
        reporter=reporter,
        engine=engine,
        approval_callback=_rich_approval_callback,
        git_ops=git_ops,
    )

    cost_log_before = len(load_cost_log(config.data_dir))

    result = await loop.run(scenarios)

    # Print iteration details
    for it in result.iterations:
        typer.echo(f"\n  --- Iteration {it.iteration} ---")
        if it.test_result.passed:
            _print_retest_result(it.test_result)
        else:
            _print_failure_report(it.test_result)
            if it.analysis:
                _print_analysis(it.analysis)
            if it.fix:
                _print_fix_diff(it.fix)

    # Final summary
    typer.echo()
    typer.echo("  " + "=" * 55)
    status_text = typer.style(
        "SUCCESS" if result.success else "FAILURE",
        fg=typer.colors.GREEN if result.success else typer.colors.RED,
        bold=True,
    )
    typer.echo(f"  Loop {status_text} after {result.total_iterations} iteration(s)")
    typer.echo(f"  Duration: {result.duration_ms:.0f}ms")

    # Cost
    cost_entries = load_cost_log(config.data_dir)
    new_entries = cost_entries[cost_log_before:]
    session_cost = sum(e.get("cost_usd", 0) for e in new_entries)
    if session_cost > 0:
        typer.echo(f"  AI cost: ${session_cost:.4f}")
    elif new_entries:
        typer.echo("  AI cost: Free")

    if result.reason:
        typer.echo(f"  Reason: {result.reason}")
    typer.echo("  " + "=" * 55)

    if not result.success:
        raise typer.Exit(code=1)
