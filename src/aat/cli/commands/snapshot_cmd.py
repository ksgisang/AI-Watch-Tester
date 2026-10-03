"""aat snapshot — capture baseline screenshots for visual regression."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from aat.core.config import load_config
from aat.core.exceptions import AATError
from aat.core.scenario_loader import load_scenarios
from aat.visual.baseline_store import BaselineStore


def snapshot_command(
    scenarios_path: str = typer.Argument(help="Scenario file or directory path."),
    config_path: str | None = typer.Option(None, "--config", "-c", help="Config file path."),
    url: str | None = typer.Option(None, "--url", "-u", help="Override target URL."),
    responsive: bool = typer.Option(
        False,
        "--responsive",
        help="Capture 3 viewports: mobile (375x812), tablet (768x1024), desktop (1280x720).",
    ),
    viewport: str | None = typer.Option(
        None,
        "--viewport",
        help="Single viewport WxH (e.g. '375x812'). Overrides --responsive.",
    ),
    console: bool = typer.Option(
        False,
        "--console",
        help="Collect browser console errors during capture.",
    ),
    console_fail: bool = typer.Option(
        False,
        "--console-fail",
        help="Fail if console errors are detected. Implies --console.",
    ),
) -> None:
    """Capture baseline screenshots for visual regression testing.

    Runs the scenario(s) and saves the after-screenshots as baselines.
    Next time you run ``aat diff``, the current screenshots will be
    compared against these baselines.
    """
    try:
        asyncio.run(
            _snapshot(
                scenarios_path,
                config_path,
                url,
                responsive,
                viewport,
                console or console_fail,
                console_fail,
            )
        )
    except AATError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None


def _parse_viewport(viewport_str: str) -> tuple[int, int]:
    """Parse 'WxH' string into (width, height) tuple."""
    parts = viewport_str.lower().split("x")
    if len(parts) != 2:
        msg = f"Invalid viewport format: {viewport_str!r}. Expected WxH (e.g. '375x812')."
        raise AATError(msg)
    return int(parts[0]), int(parts[1])


def _resolve_viewports(
    responsive: bool,
    viewport_str: str | None,
) -> list[tuple[str, int, int]]:
    """Return list of (label, width, height) to capture.

    Default (no flags) returns a single entry with empty label (current config viewport).
    """
    from aat.visual import RESPONSIVE_VIEWPORTS

    if viewport_str:
        w, h = _parse_viewport(viewport_str)
        return [("", w, h)]

    if responsive:
        return [(name, w, h) for name, (w, h) in RESPONSIVE_VIEWPORTS.items()]

    return []  # empty = use config default


async def _snapshot(
    scenarios_path: str,
    config_path: str | None,
    url_override: str | None,
    responsive: bool = False,
    viewport_str: str | None = None,
    collect_console: bool = False,
    console_fail: bool = False,
) -> None:
    """Run scenarios and save screenshots as baselines."""
    cfg_path = Path(config_path) if config_path else None
    config = load_config(config_path=cfg_path)

    if url_override:
        config.url = url_override

    config.engine.screenshot_mode = "all"
    config.engine.headless = True

    path = Path(scenarios_path)
    base_vars: dict[str, str] = {}
    if config.url:
        base_vars["url"] = config.url.rstrip("/")
    scenarios = load_scenarios(path, variables=base_vars or None)

    if not scenarios:
        typer.echo("[AWT] No scenarios found.")
        raise typer.Exit(code=1)

    viewports = _resolve_viewports(responsive, viewport_str)
    if not viewports:
        # Use config default as single viewport with no label
        viewports = [("", config.engine.viewport_width, config.engine.viewport_height)]

    store = BaselineStore(Path(config.data_dir))
    has_console_errors = False

    for vp_label, vp_w, vp_h in viewports:
        config.engine.viewport_width = vp_w
        config.engine.viewport_height = vp_h

        vp_display = f" [{vp_label} {vp_w}x{vp_h}]" if vp_label else ""

        # Import engine components
        from aat.engine import ENGINE_REGISTRY
        from aat.engine.comparator import Comparator
        from aat.engine.executor import StepExecutor
        from aat.engine.humanizer import Humanizer
        from aat.engine.waiter import Waiter
        from aat.matchers import build_matchers
        from aat.matchers.hybrid import HybridMatcher

        engine_cls = ENGINE_REGISTRY.get(config.engine.type)
        if engine_cls is None:
            msg = f"Unknown engine type: {config.engine.type}"
            raise AATError(msg)
        engine = engine_cls(config.engine)

        # No Vision AI: capturing a baseline must not reach for a paid API.
        matchers = build_matchers(config.matching, include_vision=False)
        hybrid = HybridMatcher(matchers, config.matching)
        humanizer = Humanizer(config.humanizer)
        waiter = Waiter()
        comparator = Comparator(config.matching.ocr_languages)

        ss_dir = Path(config.data_dir) / "screenshots"
        ss_dir.mkdir(parents=True, exist_ok=True)

        executor = StepExecutor(
            engine,
            hybrid,
            humanizer,
            waiter,
            comparator,
            screenshot_dir=ss_dir,
        )

        # Console collector
        console_collector = None
        if collect_console:
            from aat.visual.console_collector import ConsoleCollector

            console_collector = ConsoleCollector()

        try:
            await engine.start()

            # Attach console collector after engine starts
            if console_collector and hasattr(engine, "page"):
                console_collector.attach(engine.page)

            for scenario in scenarios:
                typer.echo(
                    f"\n[AWT] Capturing baseline{vp_display}: {scenario.id} — {scenario.name}"
                )

                if console_collector:
                    console_collector.reset()

                # Resolve scenario vars
                import os
                import re

                executor._scenario_vars = {}
                if scenario.vars:
                    env_pat = re.compile(r"\{\{env\.(\w+)\}\}")
                    for k, v in scenario.vars.items():
                        if isinstance(v, str):
                            v = env_pat.sub(lambda m: os.environ.get(m.group(1), m.group(0)), v)
                        executor._scenario_vars[k] = str(v) if v is not None else ""

                step_screenshots: dict[int, Path] = {}

                for step in scenario.steps:
                    try:
                        result = await executor.execute_step(step)
                    except Exception:
                        typer.echo(f"  Step {step.step}: FAILED — skipping remaining steps")
                        break

                    if result.screenshot_after:
                        ss_path = Path(result.screenshot_after)
                        if ss_path.exists():
                            step_screenshots[step.step] = ss_path

                    status = "✅" if result.status.value == "passed" else "❌"
                    typer.echo(f"  Step {step.step}: {status} {step.description}")

                if step_screenshots:
                    meta = store.save(
                        scenario_id=scenario.id,
                        screenshot_paths=step_screenshots,
                        scenario_name=scenario.name,
                        url=config.url or "",
                        viewport=vp_label,
                    )
                    vp_suffix = f"-{vp_label}" if vp_label else ""
                    typer.echo(
                        f"  📸 Baseline saved: {meta.step_count} screenshots "
                        f"→ .aat/baselines/{scenario.id}/ ({vp_suffix or 'default'})"
                    )
                else:
                    typer.echo("  ⚠️  No screenshots captured — baseline not saved")

                # Console error reporting
                if console_collector:
                    errs = console_collector.error_count
                    if errs > 0:
                        has_console_errors = True
                        typer.echo(
                            typer.style(
                                f"  ⚠️  Console errors: {errs}",
                                fg=typer.colors.YELLOW,
                            )
                        )
                        for line in console_collector.format_details():
                            typer.echo(f"    {line}")
                    else:
                        typer.echo("  ✅ Console: 0 errors")

        finally:
            await engine.stop()

    typer.echo("\n[AWT] Baseline capture complete.")

    if console_fail and has_console_errors:
        typer.echo(
            typer.style(
                "❌ Console errors detected (--console-fail is set)",
                fg=typer.colors.RED,
                bold=True,
            )
        )
        raise typer.Exit(code=1)
