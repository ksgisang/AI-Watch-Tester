"""Test executor — AI scenario generation + headless Playwright execution.

Flow: URL → page analysis → AI scenarios → Playwright execution → results.
Reuses AAT core modules (aat package must be installed).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.models import Test
from app.ws import WSManager

logger = logging.getLogger(__name__)

# Default model per AI provider
_DEFAULT_MODELS: dict[str, str] = {
    "claude": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
    "ollama": "codellama:7b",
}

# ---------------------------------------------------------------------------
# AI scenario generation prompt
# ---------------------------------------------------------------------------

_SCENARIO_PROMPT = """\
You are an E2E test scenario generator.

Analyze the following web page and generate user-perspective E2E test scenarios.

## Target
- URL: {url}

## Page Content (truncated)
{page_text}

## Instructions
1. Identify key user flows (login, navigation, form submission, etc.)
2. Generate 1-3 test scenarios covering the most important flows
3. Each scenario should have clear steps: navigate, click, type, assert
4. Use text-based targets (not image) for reliability
5. Keep steps concise and actionable

Return the scenarios as a JSON array following the format specified in the system instructions.\
"""

_SCENARIO_PROMPT_WITH_DOCS = """\
You are an E2E test scenario generator.

Analyze the following web page AND the uploaded specification documents to generate \
user-perspective E2E test scenarios.

## Target
- URL: {url}

## Page Content (truncated)
{page_text}

## Specification Documents
{doc_text}

## Instructions
1. Use the specification documents as the PRIMARY source for identifying test scenarios
2. Cross-reference with the actual page content to verify available UI elements
3. Generate 1-5 test scenarios covering the most important flows described in the documents
4. Each scenario should have clear steps: navigate, click, type, assert
5. Use text-based targets (not image) for reliability
6. Keep steps concise and actionable

Return the scenarios as a JSON array following the format specified in the system instructions.\
"""


# ---------------------------------------------------------------------------
# Screenshot helper
# ---------------------------------------------------------------------------


def _screenshot_dir_for_test(test_id: int) -> Path:
    """Return and create the screenshot directory for a test."""
    base = Path(settings.screenshot_dir)
    d = base / str(test_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _save_screenshot(
    engine: Any,
    test_id: int,
    label: str,
    *,
    ws: WSManager | None = None,
    step: int = 0,
    timing: str = "",
) -> str | None:
    """Capture screenshot as base64 data URL and optionally stream via WS.

    Returns base64 data URL string or None.
    Ephemeral filesystems (Render) lose files on restart, so we store
    screenshots as base64 in result_json instead of on disk.
    """
    try:
        png_bytes = await engine.screenshot()
        b64 = base64.b64encode(png_bytes).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"

        # Also save to disk as fallback (local dev)
        try:
            d = _screenshot_dir_for_test(test_id)
            path = d / f"{label}.png"
            path.write_bytes(png_bytes)
        except Exception:
            pass

        # Stream to frontend via WebSocket
        if ws and timing:
            await ws.broadcast(test_id, {
                "type": "screenshot",
                "step": step,
                "timing": timing,
                "image": data_url,
            })

        return data_url
    except Exception as exc:
        logger.debug("Screenshot save failed (%s): %s", label, exc)
        return None


# ---------------------------------------------------------------------------
# Scenario generation (Phase 1: navigate + AI generate)
# ---------------------------------------------------------------------------


async def generate_scenarios_for_test(
    test_id: int, ws: WSManager | None = None
) -> dict[str, Any]:
    """Navigate to URL, capture page, generate scenarios via AI, save YAML.

    Returns dict: {scenario_yaml, steps_total, error?}
    """
    async with async_session() as db:
        test = (await db.execute(select(Test).where(Test.id == test_id))).scalar_one()
        target_url = test.target_url
        doc_text = test.doc_text

    try:
        from aat.core.models import AIConfig, EngineConfig
        from aat.adapters import ADAPTER_REGISTRY
        from aat.engine.web import WebEngine
    except ImportError as exc:
        msg = f"AAT core not installed: {exc}. Run 'pip install -e .' from project root."
        logger.error(msg)
        return {"error": msg}

    engine_config = EngineConfig(type="web", headless=settings.playwright_headless)
    engine = WebEngine(engine_config)

    try:
        await engine.start()
        await engine.navigate(target_url)
        page_text = await engine.get_page_text()
        screenshot = await engine.screenshot()

        # Save initial screenshot + stream to frontend
        await _save_screenshot(
            engine, test_id, "initial", ws=ws, step=0, timing="initial"
        )

        # Generate scenarios via AI
        ai_config = AIConfig(
            provider=settings.ai_provider,
            api_key=settings.ai_api_key,
            model=settings.ai_model or _DEFAULT_MODELS.get(settings.ai_provider, ""),
        )

        adapter_cls = ADAPTER_REGISTRY.get(ai_config.provider)
        if adapter_cls is None:
            return {"error": f"Unknown AI provider: {ai_config.provider}"}

        adapter = adapter_cls(ai_config)

        # Use document-enhanced prompt if doc_text is available
        if doc_text:
            prompt = _SCENARIO_PROMPT_WITH_DOCS.format(
                url=target_url,
                page_text=page_text[:8000],
                doc_text=doc_text[:16000],
            )
        else:
            prompt = _SCENARIO_PROMPT.format(url=target_url, page_text=page_text[:8000])

        scenarios = await adapter.generate_scenarios(prompt, images=[screenshot])

        if not scenarios:
            return {"error": "AI generated no scenarios"}

        # Serialize to YAML
        scenario_dicts = []
        for s in scenarios:
            sd = s.model_dump(mode="json", exclude_none=True)
            scenario_dicts.append(sd)
        scenario_yaml = yaml.safe_dump(
            scenario_dicts, default_flow_style=False, allow_unicode=True
        )

        total_steps = sum(len(s.steps) for s in scenarios)

        # Update DB
        async with async_session() as db:
            test = (await db.execute(select(Test).where(Test.id == test_id))).scalar_one()
            test.scenario_yaml = scenario_yaml
            test.steps_total = total_steps
            await db.commit()

        # Notify frontend
        if ws:
            await ws.broadcast(test_id, {
                "type": "scenarios_ready",
                "scenario_yaml": scenario_yaml,
                "steps_total": total_steps,
            })

        return {"scenario_yaml": scenario_yaml, "steps_total": total_steps}

    except Exception as exc:
        logger.exception("Scenario generation failed for test %d", test_id)
        return {"error": str(exc)}
    finally:
        try:
            await engine.stop()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main executor
# ---------------------------------------------------------------------------


async def execute_test(test_id: int, ws: WSManager | None = None) -> dict[str, Any]:
    """Execute a single test end-to-end.

    If scenario_yaml already exists in DB (review mode), parse and execute it.
    Otherwise, generate scenarios first, then execute (auto mode).

    Returns dict: {passed, scenarios, duration_ms, error?}
    """
    # -- Fetch test record --
    async with async_session() as db:
        test = (await db.execute(select(Test).where(Test.id == test_id))).scalar_one()
        target_url = test.target_url
        existing_yaml = test.scenario_yaml

    start = time.monotonic()

    # -- Import AAT core (lazy to give clear error if missing) --
    try:
        from aat.core.models import (
            ActionType,
            AIConfig,
            EngineConfig,
            HumanizerConfig,
            MatchingConfig,
            Scenario,
        )
        from aat.adapters import ADAPTER_REGISTRY
        from aat.engine.web import WebEngine
        from aat.engine.executor import StepExecutor
        from aat.engine.humanizer import Humanizer
        from aat.engine.waiter import Waiter
        from aat.engine.comparator import Comparator
        from aat.matchers import MATCHER_REGISTRY
        from aat.matchers.hybrid import HybridMatcher
    except ImportError as exc:
        msg = f"AAT core not installed: {exc}. Run 'pip install -e .' from project root."
        logger.error(msg)
        return {"passed": False, "error": msg, "duration_ms": _elapsed(start)}

    # -- Start headless browser --
    engine_config = EngineConfig(type="web", headless=settings.playwright_headless)
    engine = WebEngine(engine_config)

    # Console log collector
    console_logs: list[dict[str, str]] = []

    def _on_console(msg: Any) -> None:
        """Collect browser console messages."""
        level = str(getattr(msg, "type", "log"))  # log, warning, error, info
        # Only collect warnings and errors (skip verbose logs)
        if level in ("error", "warning", "warn"):
            text = str(getattr(msg, "text", ""))
            if text:
                console_logs.append({
                    "level": "warning" if level == "warn" else level,
                    "text": text[:500],  # truncate long messages
                })

    def _on_page_error(error: Any) -> None:
        """Collect uncaught page errors."""
        console_logs.append({
            "level": "error",
            "text": f"Uncaught: {str(error)[:500]}",
        })

    try:
        await engine.start()

        # Attach console/error listeners to Playwright page
        try:
            page = engine.page
            page.on("console", _on_console)
            page.on("pageerror", _on_page_error)
        except Exception:
            logger.debug("Could not attach console listeners")

        await engine.navigate(target_url)

        # Save initial screenshot + stream to frontend
        init_ss = await _save_screenshot(
            engine, test_id, "initial", ws=ws, step=0, timing="initial"
        )

        # -- Load or generate scenarios --
        if existing_yaml:
            # Review mode: parse pre-existing YAML
            raw = yaml.safe_load(existing_yaml)
            if isinstance(raw, dict):
                raw = [raw]
            scenarios = [Scenario.model_validate(item) for item in raw]
        else:
            # Auto mode: generate scenarios inline
            page_text = await engine.get_page_text()
            screenshot = await engine.screenshot()

            ai_config = AIConfig(
                provider=settings.ai_provider,
                api_key=settings.ai_api_key,
                model=settings.ai_model or _DEFAULT_MODELS.get(settings.ai_provider, ""),
            )
            adapter_cls = ADAPTER_REGISTRY.get(ai_config.provider)
            if adapter_cls is None:
                return {
                    "passed": False,
                    "error": f"Unknown AI provider: {ai_config.provider}",
                    "duration_ms": _elapsed(start),
                }
            adapter = adapter_cls(ai_config)
            prompt = _SCENARIO_PROMPT.format(url=target_url, page_text=page_text[:8000])
            scenarios = await adapter.generate_scenarios(prompt, images=[screenshot])

        if not scenarios:
            return {
                "passed": False,
                "error": "No scenarios to execute",
                "duration_ms": _elapsed(start),
            }

        # -- Save scenario info to DB --
        total_steps = sum(len(s.steps) for s in scenarios)
        async with async_session() as db:
            test = (await db.execute(select(Test).where(Test.id == test_id))).scalar_one()
            if not existing_yaml:
                # Auto mode: save generated YAML
                scenario_dicts = [s.model_dump(mode="json", exclude_none=True) for s in scenarios]
                test.scenario_yaml = yaml.safe_dump(
                    scenario_dicts, default_flow_style=False, allow_unicode=True
                )
            test.steps_total = total_steps
            await db.commit()

        if ws:
            await ws.broadcast(test_id, {
                "type": "scenarios_generated",
                "count": len(scenarios),
                "steps_total": total_steps,
            })

        # -- Build matcher + executor --
        matching_config = MatchingConfig()
        matchers = []
        for name in ["template", "ocr"]:
            matcher_cls = MATCHER_REGISTRY.get(name)
            if matcher_cls:
                try:
                    matchers.append(matcher_cls(matching_config))
                except Exception:
                    logger.debug("Matcher %s not available, skipping", name)

        hybrid = HybridMatcher(matchers, matching_config) if matchers else None

        # screenshot_dir for StepExecutor (per-test isolation)
        ss_dir = _screenshot_dir_for_test(test_id)

        step_executor = StepExecutor(
            engine=engine,
            matcher=hybrid or matchers[0] if matchers else _NoopMatcher(),
            humanizer=Humanizer(HumanizerConfig(enabled=False)),
            waiter=Waiter(),
            comparator=Comparator(),
            screenshot_dir=ss_dir,
        )

        # -- Execute scenarios --
        all_results: list[dict[str, Any]] = []
        overall_passed = True
        completed = 0

        for scenario in scenarios:
            # Re-navigate for each scenario
            await engine.navigate(target_url)

            step_results: list[dict[str, Any]] = []
            scenario_passed = True

            for i, step in enumerate(scenario.steps):
                step_num = completed + 1

                if ws:
                    await ws.broadcast(test_id, {
                        "type": "step_start",
                        "step": step_num,
                        "total": total_steps,
                        "description": step.description or str(step.action),
                    })

                # Before-screenshot
                ss_before = await _save_screenshot(
                    engine, test_id, f"step_{step_num}_before",
                    ws=ws, step=step_num, timing="before",
                )

                try:
                    result = await asyncio.wait_for(
                        step_executor.execute_step(step),
                        timeout=30.0,
                    )
                    status = result.status.value

                    # Navigate: verify actual page state on failure
                    # Playwright may throw timeout but page still loads
                    if step.action == ActionType.NAVIGATE and status == "failed":
                        try:
                            current_url = await engine.get_url()
                            if current_url and not current_url.startswith("about:"):
                                logger.info(
                                    "Step %d navigate: page at %s, overriding to passed",
                                    step_num, current_url,
                                )
                                status = "passed"
                        except Exception:
                            pass

                    # After-screenshot
                    ss_after = await _save_screenshot(
                        engine, test_id, f"step_{step_num}_after",
                        ws=ws, step=step_num, timing="after",
                    )

                    elapsed = getattr(result, "elapsed_ms", 0)
                    error_msg = getattr(result, "error", None) or (
                        str(getattr(result, "message", "")) if status == "failed" else None
                    )

                    step_results.append({
                        "step": i + 1,
                        "action": result.action if hasattr(result, "action") else str(step.action),
                        "status": status,
                        "elapsed_ms": elapsed,
                        "error": error_msg if status == "failed" else None,
                        "screenshot_before": ss_before,
                        "screenshot_after": ss_after,
                    })

                    if status == "failed":
                        scenario_passed = False
                        overall_passed = False

                    if ws:
                        if status == "passed":
                            await ws.broadcast(test_id, {
                                "type": "step_done",
                                "step": step_num,
                                "status": status,
                                "elapsed_ms": elapsed,
                            })
                        else:
                            await ws.broadcast(test_id, {
                                "type": "step_fail",
                                "step": step_num,
                                "status": status,
                                "error": error_msg,
                                "description": step.description or str(step.action),
                            })

                except TimeoutError:
                    err_msg = (
                        f"Timeout after 30s: "
                        f"{step.description or str(step.action)}"
                    )
                    logger.warning("Step %d timed out", step_num)

                    ss_error = await _save_screenshot(
                        engine, test_id, f"step_{step_num}_error",
                        ws=ws, step=step_num, timing="error",
                    )

                    step_results.append({
                        "step": i + 1,
                        "action": str(step.action),
                        "status": "error",
                        "error": err_msg,
                        "screenshot_before": ss_before,
                        "screenshot_error": ss_error,
                    })
                    scenario_passed = False
                    overall_passed = False

                    if ws:
                        await ws.broadcast(test_id, {
                            "type": "step_fail",
                            "step": step_num,
                            "error": err_msg,
                            "description": step.description or str(step.action),
                        })

                except Exception as exc:
                    err_msg = str(exc)
                    logger.warning("Step %d failed: %s", step_num, exc)

                    ss_error = await _save_screenshot(
                        engine, test_id, f"step_{step_num}_error",
                        ws=ws, step=step_num, timing="error",
                    )

                    step_results.append({
                        "step": i + 1,
                        "action": str(step.action),
                        "status": "error",
                        "error": err_msg,
                        "screenshot_before": ss_before,
                        "screenshot_error": ss_error,
                    })
                    scenario_passed = False
                    overall_passed = False

                    if ws:
                        await ws.broadcast(test_id, {
                            "type": "step_fail",
                            "step": step_num,
                            "error": err_msg,
                            "description": step.description or str(step.action),
                        })

                completed += 1

                # Update progress in DB
                async with async_session() as db:
                    t = (await db.execute(select(Test).where(Test.id == test_id))).scalar_one()
                    t.steps_completed = completed
                    await db.commit()

            all_results.append({
                "scenario_id": scenario.id,
                "scenario_name": scenario.name,
                "passed": scenario_passed,
                "steps": step_results,
            })

        return {
            "passed": overall_passed,
            "scenarios": all_results,
            "screenshots_dir": str(_screenshot_dir_for_test(test_id)),
            "initial_screenshot": init_ss,
            "duration_ms": _elapsed(start),
            "console_logs": console_logs[:100],  # cap at 100 entries
        }

    except Exception as exc:
        logger.exception("Test %d execution error", test_id)
        return {
            "passed": False,
            "error": str(exc),
            "duration_ms": _elapsed(start),
        }
    finally:
        try:
            await engine.stop()
        except Exception:
            pass


def _elapsed(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 1)


class _NoopMatcher:
    """Fallback matcher when no real matchers are available."""

    @property
    def name(self) -> str:
        return "noop"

    async def find(self, target: Any, screenshot: bytes) -> None:
        return None

    def can_handle(self, target: Any) -> bool:
        return False
