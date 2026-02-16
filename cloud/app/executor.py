"""Test executor — AI scenario generation + headless Playwright execution.

Flow: URL → page analysis → AI scenarios → Playwright execution → results.
Reuses AAT core modules (aat package must be installed).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

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


async def execute_test(test_id: int, ws: WSManager | None = None) -> dict[str, Any]:
    """Execute a single test end-to-end.

    1. Navigate to target URL with headless Playwright
    2. Capture page content + screenshot
    3. Generate test scenarios via AI adapter
    4. Execute each scenario step by step
    5. Return aggregated results

    Returns dict: {passed, scenarios, duration_ms, error?}
    """
    # -- Fetch test record --
    async with async_session() as db:
        test = (await db.execute(select(Test).where(Test.id == test_id))).scalar_one()
        target_url = test.target_url

    start = time.monotonic()

    # -- Import AAT core (lazy to give clear error if missing) --
    try:
        from aat.core.models import (
            AIConfig,
            EngineConfig,
            HumanizerConfig,
            MatchingConfig,
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

    try:
        await engine.start()

        # -- Navigate & capture page --
        await engine.navigate(target_url)
        page_text = await engine.get_page_text()
        screenshot = await engine.screenshot()

        # -- Generate scenarios via AI --
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

        document = (
            f"Target URL: {target_url}\n\n"
            f"Page content (first 8000 chars):\n{page_text[:8000]}"
        )
        scenarios = await adapter.generate_scenarios(document, images=[screenshot])

        if not scenarios:
            return {
                "passed": False,
                "error": "AI generated no scenarios",
                "duration_ms": _elapsed(start),
            }

        # -- Save scenario info to DB --
        total_steps = sum(len(s.steps) for s in scenarios)
        scenario_data = [
            {"id": s.id, "name": s.name, "steps": len(s.steps)} for s in scenarios
        ]
        async with async_session() as db:
            test = (await db.execute(select(Test).where(Test.id == test_id))).scalar_one()
            test.scenario_yaml = json.dumps(scenario_data, ensure_ascii=False)
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

        step_executor = StepExecutor(
            engine=engine,
            matcher=hybrid or matchers[0] if matchers else _NoopMatcher(),
            humanizer=Humanizer(HumanizerConfig(enabled=False)),
            waiter=Waiter(),
            comparator=Comparator(),
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

                try:
                    result = await step_executor.execute_step(step)
                    status = result.status.value

                    step_results.append({
                        "step": i + 1,
                        "action": result.action if hasattr(result, "action") else str(step.action),
                        "status": status,
                        "elapsed_ms": getattr(result, "elapsed_ms", 0),
                    })

                    if status == "failed":
                        scenario_passed = False
                        overall_passed = False

                    if ws:
                        evt = "step_done" if status == "passed" else "step_fail"
                        await ws.broadcast(test_id, {
                            "type": evt,
                            "step": step_num,
                            "status": status,
                        })

                except Exception as exc:
                    logger.warning("Step %d failed: %s", step_num, exc)
                    step_results.append({
                        "step": i + 1,
                        "status": "error",
                        "error": str(exc),
                    })
                    scenario_passed = False
                    overall_passed = False

                    if ws:
                        await ws.broadcast(test_id, {
                            "type": "step_fail",
                            "step": step_num,
                            "error": str(exc),
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
            "duration_ms": _elapsed(start),
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
