"""aat run — single test execution (no loop)."""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from pathlib import Path

import typer

from aat.core.config import load_config
from aat.core.diagnosis import (
    check_learned_hint,
    collect_failure_context,
    format_diagnosis,
    format_skill_diagnosis,
)
from aat.core.exceptions import AATError
from aat.core.models import FIND_ACTIONS, Scenario, StepResult, StepStatus
from aat.core.platform_detect import detect_platform, format_platform_info
from aat.core.scenario_loader import load_scenarios
from aat.engine import ENGINE_REGISTRY
from aat.engine.comparator import Comparator
from aat.engine.executor import StepExecutor
from aat.engine.humanizer import Humanizer
from aat.engine.waiter import Waiter
from aat.matchers import MATCHER_REGISTRY
from aat.matchers.hybrid import HybridMatcher

# -- Browser overlay JS ---------------------------------------------------

_OVERLAY_INIT_JS = """
(() => {
  if (document.getElementById('awt-overlay')) return;
  const bar = document.createElement('div');
  bar.id = 'awt-overlay';
  bar.style.cssText = `
    position: fixed; bottom: 0; left: 0; right: 0; z-index: 2147483647;
    background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
    color: #e2e8f0; font-family: -apple-system, 'Segoe UI', sans-serif;
    font-size: 13px; padding: 8px 16px;
    display: flex; align-items: center; justify-content: space-between;
    box-shadow: 0 -2px 12px rgba(0,0,0,0.3);
    border-top: 2px solid #22d3ee;
    transition: all 0.3s ease;
    pointer-events: none;
  `;
  // Left: logo + status
  const left = document.createElement('div');
  left.style.cssText = 'display:flex;align-items:center;gap:10px;';
  left.innerHTML = `
    <span style="background:#22d3ee;color:#0f172a;font-weight:800;font-size:11px;
      padding:2px 8px;border-radius:4px;letter-spacing:0.5px;">AWT</span>
    <span id="awt-status" style="font-weight:600;">Initializing...</span>
  `;
  // Right: step counter
  const right = document.createElement('div');
  right.id = 'awt-counter';
  right.style.cssText = 'font-size:12px;color:#94a3b8;';
  right.textContent = '';
  bar.appendChild(left);
  bar.appendChild(right);
  document.body.appendChild(bar);
})();
"""

_OVERLAY_UPDATE_JS = """
((status, detail, color) => {
  const el = document.getElementById('awt-status');
  const counter = document.getElementById('awt-counter');
  if (el) {
    el.textContent = status;
    el.style.color = color || '#e2e8f0';
  }
  if (counter && detail) counter.textContent = detail;
})(%s, %s, %s);
"""

_OVERLAY_REMOVE_JS = """
(() => {
  const el = document.getElementById('awt-overlay');
  if (el) {
    el.style.borderBottomColor = %s;
    const status = document.getElementById('awt-status');
    if (status) { status.textContent = %s; status.style.color = %s; }
    setTimeout(() => {
      if (el) el.style.opacity = '0';
      setTimeout(() => { if (el) el.remove(); }, 500);
    }, %d);
  }
})();
"""


def _scenario_to_yaml(scenario: Scenario) -> str:
    """Convert a Scenario model back to YAML text for display."""
    import yaml as _yaml

    steps_list: list[dict[str, object]] = []
    data: dict[str, object] = {"id": scenario.id, "name": scenario.name, "steps": steps_list}
    for step in scenario.steps:
        s: dict[str, object] = {"step": step.step, "action": step.action.value}
        if step.description:
            s["description"] = step.description
        if step.value is not None:
            s["value"] = step.value
        if step.target:
            s["target"] = (
                step.target
                if isinstance(step.target, dict)
                else step.target.model_dump(exclude_none=True)
            )
        if step.critical:
            s["critical"] = True
        if step.on_fail:
            s["on_fail"] = step.on_fail
        if step.change_threshold is not None:
            s["change_threshold"] = step.change_threshold
        steps_list.append(s)
    return _yaml.dump(data, allow_unicode=True, sort_keys=False)


def _js_str(s: str) -> str:
    """Escape string for JS injection."""
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


async def _overlay_init(page: object) -> None:
    with contextlib.suppress(Exception):
        await page.evaluate(_OVERLAY_INIT_JS)  # type: ignore[attr-defined]


async def _overlay_update(
    page: object, status: str, detail: str = "", color: str = "#e2e8f0"
) -> None:
    try:
        js = _OVERLAY_UPDATE_JS % (_js_str(status), _js_str(detail), _js_str(color))
        await page.evaluate(js)  # type: ignore[attr-defined]
    except Exception:
        pass


async def _overlay_finish(
    page: object, passed: int, failed: int, total: int, wait_ms: int = 3000
) -> None:
    try:
        if failed > 0:
            msg = f"TEST FAILED — {passed}/{total} passed"
            color = "'#f87171'"
            border = "'#ef4444'"
        else:
            msg = f"ALL PASSED — {passed}/{total}"
            color = "'#4ade80'"
            border = "'#22c55e'"
        js = _OVERLAY_REMOVE_JS % (border, _js_str(msg), color, wait_ms)
        await page.evaluate(js)  # type: ignore[attr-defined]
        await asyncio.sleep(wait_ms / 1000 + 0.5)
    except Exception:
        pass


# -- Topological sort by depends_on ----------------------------------------


def _topo_sort(scenarios: list[Scenario]) -> list[Scenario]:
    """Sort scenarios respecting depends_on order.

    If A depends_on B, B runs first. Scenarios without dependencies
    keep their original order. Circular dependencies raise AATError.
    """
    by_id = {s.id: s for s in scenarios}
    visited: set[str] = set()
    result: list[Scenario] = []
    visiting: set[str] = set()  # cycle detection

    def visit(sid: str) -> None:
        if sid in visited:
            return
        if sid in visiting:
            msg = f"Circular dependency detected: {sid}"
            raise AATError(msg)
        if sid not in by_id:
            return  # dependency not in current set — skip silently
        visiting.add(sid)
        for dep in by_id[sid].depends_on:
            visit(dep)
        visiting.remove(sid)
        visited.add(sid)
        result.append(by_id[sid])

    for s in scenarios:
        visit(s.id)

    return result


# -- CLI command -----------------------------------------------------------


def run_command(
    scenarios_path: str = typer.Argument(help="Scenario file or directory path."),
    config_path: str | None = typer.Option(None, "--config", "-c", help="Config file path."),
    slow_mo: int | None = typer.Option(
        None,
        "--slow-mo",
        help="Slow down each action by N ms (default: 100 in headed, 0 in headless).",
    ),
    speed: str | None = typer.Option(
        None,
        "--speed",
        help=(
            "Execution speed preset: fast (Next.js/React/Vue), "
            "normal (default), slow (Flutter/canvas). "
            "Overrides config file setting."
        ),
    ),
    learn: bool = typer.Option(
        False,
        "--learn",
        help="Learn from fixes: record previously failed steps that now pass.",
    ),
    no_learn: bool = typer.Option(
        False,
        "--no-learn",
        help=(
            "Do not read or write remembered coordinates for this run "
            "(every target is found from scratch)."
        ),
    ),
    skill_mode: bool = typer.Option(
        False,
        "--skill-mode",
        help="Output structured diagnosis for AI coding assistants (Claude Code, Copilot, etc.).",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debug logging (OCR candidates, matcher details).",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Treat skipped steps as failures (exit code 1).",
    ),
    skip_teardown: bool = typer.Option(
        False,
        "--skip-teardown",
        help="Skip teardown steps (useful for debugging or when cleanup is handled externally).",
    ),
    fast: bool = typer.Option(
        False,
        "--fast",
        help="Enable fast mode: strictly use DOM matching, skip Vision/OCR fallbacks.",
    ),
    verbosity: str | None = typer.Option(
        None,
        "--verbosity",
        "-V",
        help=(
            "Execution verbosity: 'detailed' (default, run all steps) or "
            "'concise' (skip wait/screenshot/assert_screen_changed steps for speed)."
        ),
    ),
    screenshots: str | None = typer.Option(
        None,
        "--screenshots",
        help=(
            "Screenshot strategy: 'all' (every step, default), "
            "'before-after' (action boundaries only, ~70% fewer files), "
            "'on-failure' (failure steps only, CI/CD optimized)."
        ),
    ),
) -> None:
    """Run test scenarios."""
    try:
        asyncio.run(
            _run(
                scenarios_path,
                config_path,
                slow_mo,
                learn,
                skill_mode,
                debug,
                strict,
                skip_teardown,
                fast,
                speed,
                verbosity,
                screenshots,
                not no_learn,
            )
        )
    except AATError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None


def _exit_code(
    *,
    had_critical: bool,
    total_failed: int,
    total_skipped: int,
    total_warned: int,
    strict_mode: bool,
) -> int:
    """Decide what the process tells the pipeline that called it.

    2 critical, 1 failed, 3 warnings, 0 clean. A warning outranks a clean exit
    on purpose: a step that changed nothing on screen is the one case that used
    to be reported as passed, which is how a real failure reached a person as
    "the product is broken" instead of "the click missed".

    Skips only count as a failure under --strict.
    """
    if had_critical:
        return 2
    if total_failed > 0 or (total_skipped > 0 and strict_mode):
        return 1
    if total_warned > 0:
        return 3
    return 0


async def _run(
    scenarios_path: str,
    config_path: str | None,
    slow_mo_override: int | None,
    learn_mode: bool = False,
    skill_mode: bool = False,
    debug_mode: bool = False,
    strict_mode: bool = False,
    skip_teardown: bool = False,
    fast_mode: bool = False,
    speed_override: str | None = None,
    verbosity_override: str | None = None,
    screenshots_override: str | None = None,
    learn_coords: bool = True,
) -> None:
    # Internal approval bypass: validated via one-time token from parent process.
    # Parent (devqa/watch) generates a token, stores it on disk, passes via env var.
    # An attacker setting the env var without a matching disk file will fail.
    from aat.core.approval_token import ENV_VAR as _TOKEN_ENV
    from aat.core.approval_token import validate_and_consume

    _token = os.environ.get(_TOKEN_ENV, "")
    auto_approve: bool = (
        skill_mode  # MCP/skill: human approved at Claude Code tool-call level
        or (validate_and_consume(_token) if _token else False)
    )
    """Execute scenarios asynchronously."""
    # Debug logging
    if debug_mode:
        import logging as _logging

        _logging.basicConfig(level=_logging.DEBUG, format="[AWT DEBUG] %(message)s")

    # Load config
    cfg_path = Path(config_path) if config_path else None
    config = load_config(config_path=cfg_path)

    if fast_mode:
        config.engine.fast_mode = True
        # Snappy humanizer for fast mode visual feedback
        config.humanizer.mouse_speed_min = 0.05
        config.humanizer.mouse_speed_max = 0.1
        config.humanizer.typing_delay_min = 0.01
        config.humanizer.typing_delay_max = 0.03

    # Apply speed preset: CLI override > config file value
    _valid_speeds = {"fast", "normal", "slow"}
    if speed_override is not None:
        if speed_override not in _valid_speeds:
            typer.echo(f"[AWT] Warning: unknown speed '{speed_override}'. Using 'normal'.")
        else:
            config.engine.speed = speed_override

    # Apply verbosity: CLI override > config file value
    _valid_verbosities = {"concise", "detailed"}
    if verbosity_override is not None:
        if verbosity_override not in _valid_verbosities:
            typer.echo(
                f"[AWT] Warning: unknown verbosity '{verbosity_override}'. Using 'detailed'."
            )
        else:
            config.engine.verbosity = verbosity_override

    # Apply screenshot mode: CLI override > config file value
    _valid_screenshot_modes = {"all", "before-after", "on-failure"}
    if screenshots_override is not None:
        if screenshots_override not in _valid_screenshot_modes:
            typer.echo(
                f"[AWT] Warning: unknown screenshots mode '{screenshots_override}'. Using 'all'."
            )
        else:
            config.engine.screenshot_mode = screenshots_override

    # Apply slow_mo: CLI override > config > auto (100 for headed, 0 for headless)
    # None means "not set" — auto-apply 100 for headed mode.
    # Explicit 0 (CLI or config) is always respected.
    headed = not config.engine.headless
    if slow_mo_override is not None:
        config.engine.slow_mo = slow_mo_override
    elif config.engine.slow_mo is None and headed:
        config.engine.slow_mo = 100
    elif config.engine.slow_mo is None:
        config.engine.slow_mo = 0

    # Load scenarios and sort by depends_on (topological sort)
    # Inject config.url as {{url}} so scenarios don't need to hardcode the base URL
    path = Path(scenarios_path)
    _base_vars: dict[str, str] = {}
    if config.url:
        _base_vars["url"] = config.url.rstrip("/")
    scenarios = _topo_sort(load_scenarios(path, variables=_base_vars or None))
    total_scenario_steps = sum(len(s.steps) for s in scenarios)

    # ------------------------------------------------------------------ #
    # Audit logging — record every execution attempt (Layer 3)            #
    # ------------------------------------------------------------------ #
    from aat.core.audit import AuditEntry, log_audit

    _approval_method = "skill" if skill_mode else ("token" if _token else "interactive")
    _scenario_ids = [s.id for s in scenarios]

    # ------------------------------------------------------------------ #
    # Human approval gate — runs BEFORE the browser opens.                #
    # No --auto-approve flag = no execution. Period.                       #
    # AI agents cannot pass this: stdin is the human's terminal.          #
    # ------------------------------------------------------------------ #
    if not auto_approve:
        from aat.core.scenario_reviewer import ScenarioReviewer

        reviewer = ScenarioReviewer()
        for i, scenario in enumerate(scenarios):
            scenario_yaml = _scenario_to_yaml(scenario)
            approved = reviewer.show_and_approve(
                scenario_yaml,
                scenario_path=path if path.is_file() else None,
                attempt=1,
                auto_approve=False,
            )
            if not approved:
                log_audit(
                    AuditEntry(
                        action="run",
                        approval_method="interactive",
                        approved=False,
                        scenarios=_scenario_ids,
                    )
                )
                typer.echo("[AWT] Execution cancelled by user.")
                raise typer.Exit(code=0)
            if len(scenarios) > 1 and i < len(scenarios) - 1:
                typer.echo(f"  ({i + 1}/{len(scenarios)} approved — next: {scenarios[i + 1].id})")

    # Audit: approved (either via token or interactive)
    log_audit(
        AuditEntry(
            action="run",
            approval_method=_approval_method,
            approved=True,
            scenarios=_scenario_ids,
            token_prefix=_token[:8] if _token else None,
        )
    )

    # Assemble engine
    engine_cls = ENGINE_REGISTRY.get(config.engine.type)
    if engine_cls is None:
        msg = f"Unknown engine type: {config.engine.type}"
        raise AATError(msg)
    engine = engine_cls(config.engine)
    matchers = []
    for m in config.matching.chain_order:
        if m.value not in MATCHER_REGISTRY:
            continue
        if m.value == "vision_ai":
            vis = MATCHER_REGISTRY[m.value](  # type: ignore[call-arg]
                vision_config=config.vision,
                matching_config=config.matching,
                ai_config=config.ai,  # legacy fallback
            )
            matchers.append(vis)
        else:
            matchers.append(MATCHER_REGISTRY[m.value](config.matching))  # type: ignore[call-arg]
    # Always add VisionAIMatcher if not in chain_order (Tier 3 fallback)
    if not any(m.name == "vision_ai" for m in matchers):
        from aat.matchers.vision_ai import VisionAIMatcher

        matchers.append(
            VisionAIMatcher(
                vision_config=config.vision,
                matching_config=config.matching,
                ai_config=config.ai,
            )
        )
    # Set up LearnedStore for match history tracking
    learned_store = None
    try:
        from aat.learning.store import LearnedStore

        learned_store = LearnedStore(Path(config.data_dir) / "learned.db")
    except Exception:
        pass
    hybrid = HybridMatcher(matchers, config.matching, learned_store=learned_store)
    humanizer = Humanizer(config.humanizer)
    waiter = Waiter()
    comparator = Comparator()

    # Initialize AI adapter for step verification (if enabled)
    ai_adapter = None
    if config.ai.step_verify and config.ai.api_key:
        try:
            from aat.adapters import ADAPTER_REGISTRY

            adapter_cls = ADAPTER_REGISTRY.get(config.ai.provider)
            if adapter_cls:
                ai_adapter = adapter_cls(config.ai)
        except Exception:
            pass

    executor = StepExecutor(
        engine,
        hybrid,
        humanizer,
        waiter,
        comparator,
        learned_store=learned_store,
        ai_adapter=ai_adapter,
        ai_verify_steps=config.ai.step_verify,
        ai_verify_critical_only=config.ai.step_verify_critical_only,
        learn_coords=learn_coords,
    )
    if not learn_coords:
        typer.echo("  (--no-learn: remembered coordinates are neither used nor updated)")

    # Skill-mode attempt tracking
    skill_attempt = 1
    skill_max_attempts = 5
    if skill_mode:
        skill_state_path = Path(config.data_dir) / "skill_attempts.json"
        try:
            if skill_state_path.exists():
                import json as _sjson

                state = _sjson.loads(skill_state_path.read_text("utf-8"))
                if state.get("scenario") == scenarios_path:
                    skill_attempt = state.get("attempt", 0) + 1
                else:
                    skill_attempt = 1  # Different scenario, reset
        except Exception:
            pass

    total_passed = 0
    total_failed = 0
    total_steps = 0
    total_skipped = 0
    total_warned = 0
    warnings: list[str] = []  # steps that ran but changed nothing
    had_critical = False
    passed_scenarios: set[str] = set()
    failed_scenarios: set[str] = set()
    all_results: list[dict[str, str]] = []  # step-level results for learning
    nav_warnings: list[str] = []  # nav-zone click warnings for skill-mode
    platform_detected = False
    try:
        await engine.start()

        def _get_active_page() -> object | None:
            """Get the current active page — handles new tabs and navigations."""
            if not hasattr(engine, "_context") or engine._context is None:
                return None
            try:
                pages = engine._context.pages
                if pages:
                    return pages[-1]  # type: ignore[no-any-return]  # Latest (most recently opened) tab
            except Exception:
                pass
            try:
                return engine.page  # type: ignore[no-any-return]
            except Exception:
                return None

        # CLI: test started
        if headed:
            typer.echo()
            typer.echo("  " + "=" * 50)
            typer.echo(
                typer.style("  ▶ TEST STARTED — browser opened", fg=typer.colors.CYAN, bold=True)
            )
            if config.engine.slow_mo > 0:
                typer.echo(f"    slowMo: {config.engine.slow_mo}ms per action")
            typer.echo("  " + "=" * 50)

        # Skill-mode start banner
        if skill_mode:
            sc_names = [f"{s.id}" for s in scenarios]
            typer.echo(f"[AWT] Test started: {', '.join(sc_names)} ({total_scenario_steps} steps)")

        for scenario in scenarios:
            # Check depends_on: skip if any dependency failed or was skipped
            unmet = [d for d in scenario.depends_on if d not in passed_scenarios]
            if unmet:
                skip_reason = ", ".join(unmet)
                typer.echo(f"\nScenario: {scenario.id} — {scenario.name}")
                typer.echo(
                    typer.style(f"  SKIPPED — depends on: {skip_reason}", fg=typer.colors.YELLOW)
                )
                failed_scenarios.add(scenario.id)
                total_skipped += 1
                continue

            typer.echo(f"\nScenario: {scenario.id} — {scenario.name}")
            if scenario.depends_on:
                typer.echo(f"  (depends on: {', '.join(scenario.depends_on)})")

            # Auto-reset between scenarios (multi-case)
            if len(scenarios) > 1 and scenario != scenarios[0]:
                try:
                    # 1. Navigate to base URL (reset page state)
                    if config.url:
                        await engine.navigate(config.url)
                    else:
                        await engine.refresh()
                    await asyncio.sleep(1.0)

                    # 2. Reset executor page state
                    executor._current_page_state = "normal"
                    executor._last_screenshot = None

                    if skill_mode:
                        typer.echo("[AWT] State reset for new scenario")
                except Exception:
                    pass

            scenario_start = time.monotonic()
            scenario_failed = False
            critical_failure = False

            # Resolve scenario-level vars at execution time (handles env refs set after load)
            if scenario.vars:
                import re as _re

                _env_pat = _re.compile(r"\{\{env\.(\w+)\}\}")
                _resolved: dict[str, str] = {}
                for _k, _v in scenario.vars.items():
                    if isinstance(_v, str):
                        _v = _env_pat.sub(
                            lambda m: os.environ.get(m.group(1), m.group(0)),
                            _v,
                        )
                    _resolved[_k] = str(_v) if _v is not None else ""
                executor._scenario_vars = _resolved
            else:
                executor._scenario_vars = {}

            for step in scenario.steps:
                # Browser overlay: show current step BEFORE execution
                if headed:
                    page = _get_active_page()
                    if page:
                        step_label = f"Step {step.step}: {step.description}"
                        counter = f"{total_steps + 1} / {total_scenario_steps}"
                        await _overlay_init(page)
                        await _overlay_update(page, step_label, counter, "#22d3ee")
                        await asyncio.sleep(0.8)  # Let user read the step name

                try:
                    result = await executor.execute_step(step)
                except Exception as _crit_err:
                    # CriticalStepError — stop scenario immediately
                    from aat.core.exceptions import CriticalStepError

                    if isinstance(_crit_err, CriticalStepError):
                        total_steps += 1
                        total_failed += 1
                        scenario_failed = True
                        critical_failure = True
                        remaining = len(scenario.steps) - scenario.steps.index(step) - 1
                        total_skipped += remaining

                        # .detail = author's message + the real cause underneath
                        _crit_detail = getattr(_crit_err, "detail", "") or str(_crit_err)

                        if skill_mode:
                            typer.echo(
                                f"[AWT] ❌ {step.step}/{total_scenario_steps} "
                                f"{step.description} (critical)"
                            )
                            typer.echo(f"[AWT] 🛑 Test stopped — {_crit_detail}")
                        else:
                            typer.echo(
                                typer.style(
                                    f"  Step {step.step}: CRITICAL FAILURE",
                                    fg=typer.colors.RED,
                                    bold=True,
                                )
                            )
                            typer.echo(f"    {_crit_detail}")
                            typer.echo(f"    Skipping remaining {remaining} step(s)")

                        # Skill-mode: CRITICAL_FAILURE block
                        if skill_mode:
                            try:
                                diag = await collect_failure_context(
                                    engine,
                                    StepResult(
                                        step=step.step,
                                        action=step.action,
                                        status=StepStatus.FAILED,
                                        description=step.description,
                                        error_message=getattr(_crit_err, "message", "")
                                        or str(_crit_err),
                                    ),
                                    str(path),
                                    config.data_dir,
                                    # Classification must key off the real cause,
                                    # not the author's reading of the assertion
                                    actual_cause=getattr(_crit_err, "cause", ""),
                                )
                                diag["critical"] = True
                                typer.echo(
                                    format_skill_diagnosis(
                                        diag,
                                        scenario_file=str(path),
                                        attempt=skill_attempt,
                                        max_attempts=skill_max_attempts,
                                    )
                                )
                            except Exception:
                                pass
                        break
                    raise
                total_steps += 1

                # Platform detection (once, after first navigate)
                if not platform_detected and step.action.value == "navigate":
                    platform_detected = True
                    try:
                        pinfo = await detect_platform(engine)
                        ptext = format_platform_info(pinfo)
                        if ptext:
                            typer.echo(ptext)
                            # Load user tips from LearnedStore
                            try:
                                from aat.learning.store import LearnedStore

                                ls = LearnedStore(Path(config.data_dir) / "learned.db")
                                user_tips = ls.get_platform_tips(pinfo["platform"])
                                for tip in user_tips:
                                    typer.echo(f"    💡 {tip}")
                            except Exception:
                                pass
                    except Exception:
                        pass

                # Track for learning
                all_results.append(
                    {
                        "scenario": scenario.id,
                        "step": str(result.step),
                        "action": result.action.value,
                        "description": result.description,
                        "status": result.status.value,
                        "error": result.error_message or "",
                    }
                )

                # Update overlay with result + pause to let user read
                if result.status == StepStatus.PASSED:
                    total_passed += 1
                    status_str = typer.style("PASSED", fg=typer.colors.GREEN)
                    if headed:
                        page = _get_active_page()
                        if page:
                            await _overlay_init(page)
                            await _overlay_update(
                                page,
                                f"✓ Step {step.step}: {step.description}",
                                f"{total_passed} passed / {total_failed} failed",
                                "#4ade80",
                            )
                            await asyncio.sleep(1.2)
                elif result.status == StepStatus.SKIPPED:
                    total_skipped += 1
                    status_str = typer.style("SKIPPED", fg=typer.colors.YELLOW)
                elif result.status == StepStatus.WARNING:
                    # The action ran without error but nothing on screen moved.
                    # Not a pass: report it, and let the exit code carry it.
                    total_warned += 1
                    warnings.append(
                        f"{scenario.id} step {result.step} "
                        f"({result.action.value}): {result.error_message}"
                    )
                    status_str = typer.style("WARNING", fg=typer.colors.YELLOW)
                else:
                    total_failed += 1
                    scenario_failed = True
                    status_str = typer.style(str(result.status.value).upper(), fg=typer.colors.RED)
                    if headed:
                        page = _get_active_page()
                        if page:
                            await _overlay_init(page)
                            fail_msg = (
                                f"✗ Step {step.step}: FAILED"
                                f" — {result.error_message or step.description}"
                            )
                            await _overlay_update(
                                page,
                                fail_msg,
                                f"{total_passed} passed / {total_failed} failed",
                                "#f87171",
                            )
                            await asyncio.sleep(2.0)  # Longer pause on failure

                # CLI output (always)
                if skill_mode:
                    # Skill-mode progress format
                    if result.status == StepStatus.PASSED:
                        icon = "✅"
                    elif result.status == StepStatus.SKIPPED:
                        icon = "⏭️"
                    elif result.status == StepStatus.WARNING:
                        icon = "⚠️"
                    else:
                        icon = "❌"
                    typer.echo(
                        f"[AWT] {icon} {result.step}/{total_scenario_steps} {step.description}"
                    )
                else:
                    typer.echo(f"  Step {result.step}: {status_str} ({result.elapsed_ms:.0f}ms)")
                if result.error_message:
                    typer.echo(f"    Error: {result.error_message}")

                # Nav-zone warning: click in left 20% is likely nav panel
                nav_warning = ""
                if (
                    result.match_result is not None
                    and result.match_result.found
                    and step.action in FIND_ACTIONS
                ):
                    mr = result.match_result
                    vw = config.engine.viewport_width
                    nav_boundary = vw * 0.2
                    if 0 < mr.x < nav_boundary:
                        nav_warning = (
                            f"Step {step.step}: click at x={mr.x} is in "
                            f"the left 20% (nav zone, x < "
                            f"{int(nav_boundary)}). "
                            f"May be nav panel, not main content."
                        )
                        nav_warnings.append(nav_warning)
                        typer.echo(
                            typer.style(
                                f"    WARNING: {nav_warning}",
                                fg=typer.colors.YELLOW,
                            )
                        )

                # Structured diagnosis on failure (not for skipped steps)
                if result.status == StepStatus.FAILED:
                    try:
                        diag = await collect_failure_context(
                            engine, result, str(path), config.data_dir
                        )
                        # Check learned hints
                        learned_hint = None
                        try:
                            from aat.learning.store import LearnedStore

                            store = LearnedStore(Path(config.data_dir) / "learned.db")
                            learned_hint = check_learned_hint(store, diag.get("failure_type", ""))
                        except Exception:
                            pass
                        typer.echo(format_diagnosis(diag, str(path), learned_hint))

                        # Skill-mode: structured block for AI coding assistants
                        if skill_mode:
                            if nav_warnings:
                                diag["nav_warnings"] = nav_warnings
                            typer.echo(
                                format_skill_diagnosis(
                                    diag,
                                    scenario_file=str(path),
                                    attempt=skill_attempt,
                                    max_attempts=skill_max_attempts,
                                )
                            )
                    except Exception:
                        pass  # diagnosis is best-effort

            # --- Teardown ---
            if scenario.teardown and not skip_teardown:
                from aat.core.teardown import TeardownExecutor

                td_vars: dict[str, str] = {}
                if config.url:
                    td_vars["url"] = config.url.rstrip("/")
                td_vars.update(scenario.variables or {})
                td_vars.update(executor._scenario_vars or {})

                if skill_mode:
                    typer.echo(f"[AWT] Running {len(scenario.teardown)} teardown step(s)...")
                try:
                    await TeardownExecutor(td_vars).run(scenario.teardown)
                    if skill_mode:
                        typer.echo("[AWT] Teardown complete")
                except Exception:
                    pass  # TeardownExecutor never raises, but guard anyway

            scenario_elapsed = (time.monotonic() - scenario_start) * 1000
            typer.echo(f"  Scenario completed in {scenario_elapsed:.0f}ms")

            if scenario_failed:
                failed_scenarios.add(scenario.id)
                if critical_failure:
                    had_critical = True
            else:
                passed_scenarios.add(scenario.id)

        # Browser overlay: final result (stays visible for 3 seconds)
        if headed:
            page = _get_active_page()
            if page:
                await _overlay_init(page)
                await _overlay_finish(page, total_passed, total_failed, total_steps)

        # Skill-mode: save final screenshot for verification
        final_screenshot_path = ""
        if skill_mode:
            try:
                ss_dir = Path(config.data_dir) / "screenshots"
                ss_dir.mkdir(parents=True, exist_ok=True)
                ss_path = ss_dir / "final_screen.png"
                ss_bytes = await engine.screenshot()
                ss_path.write_bytes(ss_bytes)
                final_screenshot_path = str(ss_path)
            except Exception:
                pass

        # CLI: test finished
        if headed:
            typer.echo()
            typer.echo("  " + "=" * 50)
            typer.echo(
                typer.style("  ■ TEST FINISHED — closing browser", fg=typer.colors.CYAN, bold=True)
            )
            typer.echo("  " + "=" * 50)

    finally:
        await engine.stop()

    # Summary
    fail_label = f"{total_failed} failed"
    if had_critical:
        fail_label += " (critical)"
    parts = [f"{total_passed} passed", fail_label]
    if total_warned > 0:
        parts.append(f"{total_warned} warning")
    if total_skipped > 0:
        parts.append(f"{total_skipped} skipped")
    parts.append(f"{total_steps} steps total")
    typer.echo(f"\nSummary: {', '.join(parts)}")

    if warnings:
        typer.echo(
            typer.style(
                "\nWarnings — these steps ran but changed nothing on screen:",
                fg=typer.colors.YELLOW,
            )
        )
        for w in warnings:
            typer.echo(typer.style(f"  ⚠ {w}", fg=typer.colors.YELLOW))
        typer.echo(
            "  A click that moves nothing usually means it missed its target. "
            "Check the screenshots for those steps."
        )

    # -- Learn mode: compare with previous run --------------------------------
    run_data = _save_run_result(config.data_dir, scenarios_path, all_results)
    if learn_mode:
        _learn_from_fixes(config.data_dir, scenarios_path, run_data)

    # -- Skill-mode: save attempt state + cloud recommendation ----------------
    if skill_mode:
        _save_skill_attempt(config.data_dir, scenarios_path, skill_attempt, total_failed)

    code = _exit_code(
        had_critical=had_critical,
        total_failed=total_failed,
        total_skipped=total_skipped,
        total_warned=total_warned,
        strict_mode=strict_mode,
    )
    if code in (1, 2):
        raise typer.Exit(code=code)
    if code == 3:
        if skill_mode:
            warn_lines = [
                "",
                "=== AWT SKILL VERIFY ===",
                f"STATUS: WARNINGS ({total_warned} of {total_steps} steps changed nothing)",
                f"SCENARIO: {scenarios_path}",
            ]
            if final_screenshot_path:
                warn_lines.append(f"FINAL_SCREENSHOT: {final_screenshot_path}")
            warn_lines += [f"WARNING: {w}" for w in warnings]
            warn_lines += [
                "ACTION: Do not report this run as passed. A step that changed "
                "nothing usually clicked the wrong place — check its screenshot "
                "and the target it was given.",
                "========================",
                "",
            ]
            typer.echo("\n".join(warn_lines))
        raise typer.Exit(code=3)
    if skill_mode:
        # All passed — output verification block + reset counter
        _save_skill_attempt(config.data_dir, scenarios_path, 0, 0)
        verify_lines = [
            "",
            "=== AWT SKILL VERIFY ===",
            f"STATUS: ALL_PASSED ({total_passed}/{total_steps})",
            f"SCENARIO: {scenarios_path}",
        ]
        if final_screenshot_path:
            verify_lines.append(f"FINAL_SCREENSHOT: {final_screenshot_path}")
        if nav_warnings:
            verify_lines.append(f"NAV_ZONE_WARNINGS: {len(nav_warnings)}")
            for w in nav_warnings:
                verify_lines.append(f"  - {w}")
            verify_lines.append(
                "ACTION: Read FINAL_SCREENSHOT to verify the screen "
                "shows the expected page, not a nav panel or wrong page. "
                "If wrong page → False Positive → fix scenario and retest."
            )
        else:
            verify_lines.append(
                "ACTION: Read FINAL_SCREENSHOT to confirm the test ended on the correct page."
            )
        verify_lines.append("========================")
        verify_lines.append("")
        typer.echo("\n".join(verify_lines))


# -- Skill-mode helpers ----------------------------------------------------

import json as _json  # noqa: E402


def _save_skill_attempt(
    data_dir: str,
    scenarios_path: str,
    attempt: int,
    total_failed: int,
) -> None:
    """Save skill-mode attempt state for cross-invocation tracking."""
    state_dir = Path(data_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "skill_attempts.json"
    state_path.write_text(
        _json.dumps(
            {"scenario": scenarios_path, "attempt": attempt},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Cloud recommendation after 3+ failures
    if attempt >= 3 and total_failed > 0:
        typer.echo()
        typer.echo(
            typer.style(
                "  Repeated failures detected. AWT Cloud provides dedicated AI\n"
                "  that analyzes more accurately. → https://awt.dev",
                fg=typer.colors.YELLOW,
            )
        )


# -- Learning helpers ------------------------------------------------------


def _save_run_result(
    data_dir: str,
    scenarios_path: str,
    results: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Save current run results to .aat/last_run.json for learning comparison."""
    out_dir = Path(data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "last_run.json"
    out_path.write_text(
        _json.dumps(
            {"scenarios_path": scenarios_path, "results": results},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return results


def _learn_from_fixes(
    data_dir: str,
    scenarios_path: str,
    current_results: list[dict[str, str]],
) -> None:
    """Compare current run with previous run and learn from fixes.

    If a step was FAILED in the previous run but PASSED now,
    record it as a learned fix pattern.
    """
    prev_path = Path(data_dir) / "prev_run.json"
    last_path = Path(data_dir) / "last_run.json"

    # Load previous run (saved from the run before this one)
    if not prev_path.exists():
        # First run with --learn: save current as prev for next time
        if last_path.exists():
            import shutil

            shutil.copy2(last_path, prev_path)
        return

    try:
        prev_data = _json.loads(prev_path.read_text(encoding="utf-8"))
        prev_results = prev_data.get("results", [])
    except Exception:
        return

    # Build lookup: (scenario, step) → previous status
    prev_lookup: dict[tuple[str, str], dict[str, str]] = {}
    for r in prev_results:
        key = (r.get("scenario", ""), r.get("step", ""))
        prev_lookup[key] = r

    # Find healed steps: was FAILED → now PASSED
    healed: list[dict[str, str]] = []
    for r in current_results:
        key = (r.get("scenario", ""), r.get("step", ""))
        prev = prev_lookup.get(key)
        if prev and prev.get("status") == "failed" and r.get("status") == "passed":
            healed.append(
                {
                    "scenario": r.get("scenario", ""),
                    "step": r.get("step", ""),
                    "description": r.get("description", ""),
                    "prev_error": prev.get("error", ""),
                    "action": r.get("action", ""),
                }
            )

    if not healed:
        # Rotate: current becomes prev for next run
        import shutil

        shutil.copy2(last_path, prev_path)
        return

    # Record learned fixes
    try:
        from aat.core.diagnosis import classify_failure
        from aat.learning.store import LearnedStore

        store = LearnedStore(Path(data_dir) / "learned.db")

        typer.echo()
        typer.echo(
            typer.style(
                f"  🧠 Learned {len(healed)} fix(es) from this run:",
                fg=typer.colors.GREEN,
                bold=True,
            )
        )

        for h in healed:
            failure_type = classify_failure(h["prev_error"])
            fix_desc = (
                f"Step {h['step']} ({h['action']}): "
                f"'{h['description']}' — was: {h['prev_error'][:80]}"
            )
            store.record_failure(
                error_type=failure_type,
                error_message=h["prev_error"],
                action=h["action"],
                fix_description=fix_desc,
            )
            store.mark_fix_applied(failure_type, fix_desc)

            typer.echo(f"    ✓ {h['scenario']} Step {h['step']}: {h['prev_error'][:60]} → FIXED")

    except Exception as e:
        typer.echo(f"    (learning failed: {e})")

    # Rotate: current becomes prev for next run
    import shutil

    shutil.copy2(last_path, prev_path)
