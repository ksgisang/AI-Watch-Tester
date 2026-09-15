"""Failure diagnosis — structured analysis without AI dependency.

Collects browser context (URL, console errors, network failures, DOM snapshot)
and classifies failures into actionable categories with investigation checklists.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aat.core.models import StepResult
    from aat.learning.store import LearnedStore

logger = logging.getLogger(__name__)

# -- Failure classification + checklists -----------------------------------

_INVESTIGATION_CHECKLISTS: dict[str, list[str]] = {
    "element_not_found": [
        "Check if the element's text/selector changed in the latest commit",
        "Check if the element is inside an iframe",
        "Check if the page requires login/auth before this element appears",
        "Try adding a wait step before this step",
        "Use browser DevTools to find the current selector",
    ],
    "timeout": [
        "Check if the server is running and responding",
        "Check network tab for slow API calls (>5s)",
        "Check if a modal/popup is blocking the page",
        "Increase timeout_ms in the step or config",
    ],
    "navigation_error": [
        "Verify the URL is correct and accessible",
        "Check if the server is running on the expected port",
        "Check for CORS or SSL certificate issues",
    ],
    "auth_error": [
        "Verify login credentials in the scenario",
        "Check if the session/token has expired",
        "Check if the auth API endpoint has changed",
    ],
    "server_error": [
        "Check server logs for the error details",
        "Verify database connection and migrations",
        "Check if required environment variables are set",
    ],
    "selector_changed": [
        "The UI was updated — find the new selector with DevTools",
        "Consider using OCR text matching instead of CSS selectors",
        "Add selector + text together for resilience",
    ],
    "assertion_failed": [
        "Verify the expected text matches what's actually on screen",
        "Check if the page is in the correct language/locale",
        "Check if the content is loaded dynamically (add wait)",
        "Check the screenshot to see what's actually displayed",
    ],
    "unknown": [
        "Check the screenshot at the failure point",
        "Check browser console for JavaScript errors",
        "Try running the scenario with --slow-mo 300 to observe",
    ],
}


def classify_failure(error_message: str) -> str:
    """Classify a failure into an actionable category."""
    err = (error_message or "").lower()
    if "not visible" in err or "not found" in err:
        return "element_not_found"
    if "timeout" in err or "timed out" in err:
        return "timeout"
    if "navigation" in err or "goto" in err or "net::" in err:
        return "navigation_error"
    if "401" in err or "403" in err or "auth" in err:
        return "auth_error"
    if "500 internal" in err or "internal server error" in err or "502" in err or "503" in err:
        return "server_error"
    if "selector" in err:
        return "selector_changed"
    if "assert" in err or "text_visible" in err:
        return "assertion_failed"
    return "unknown"


async def collect_failure_context(
    engine: object,
    step_result: StepResult,
    scenario_path: str,
    data_dir: str = ".aat",
    actual_cause: str = "",
) -> dict[str, Any]:
    """Collect structured diagnostic data from the browser at failure point.

    This runs WITHOUT AI — pure data collection from Playwright.

    Args:
        actual_cause: Underlying error when ``error`` holds the scenario
            author's interpretation (step.message). Classification keys off
            this, so a step that died for an unrelated reason is not
            diagnosed as a broken assertion.
    """
    context: dict[str, Any] = {
        "step": step_result.step,
        "action": step_result.action.value,
        "description": step_result.description,
        "error": step_result.error_message or "",
        "actual_cause": actual_cause,
        "elapsed_ms": step_result.elapsed_ms,
    }

    try:
        # Current URL
        if hasattr(engine, "get_url"):
            context["url"] = await engine.get_url()

        # Screenshot
        if hasattr(engine, "screenshot"):
            ss_dir = Path(data_dir) / "screenshots"
            ss_dir.mkdir(parents=True, exist_ok=True)
            ss_path = ss_dir / f"fail_step{step_result.step}.png"
            ss_bytes = await engine.screenshot()
            ss_path.write_bytes(ss_bytes)
            context["screenshot"] = str(ss_path)

        # Console errors
        if hasattr(engine, "page"):
            try:
                page = engine.page
                # Collect console errors via JS
                errors = await page.evaluate("""() => {
                    return (window.__awtConsoleErrors || []).slice(-10);
                }""")
                if errors:
                    context["console_errors"] = errors
            except Exception:
                pass

        # Page title
        if hasattr(engine, "page"):
            with contextlib.suppress(Exception):
                context["page_title"] = await engine.page.title()

    except Exception as e:
        logger.debug("Failed to collect some diagnostic data: %s", e)

    # Classify — the real cause wins over the author's interpretation
    context["failure_type"] = classify_failure(
        context.get("actual_cause", "") or context.get("error", "")
    )
    context["investigation"] = _INVESTIGATION_CHECKLISTS.get(
        context["failure_type"], _INVESTIGATION_CHECKLISTS["unknown"]
    )

    return context


def format_diagnosis(
    context: dict[str, Any],
    scenario_file: str = "",
    learned_hint: dict[str, Any] | None = None,
) -> str:
    """Format diagnosis into readable CLI output."""
    lines: list[str] = []
    lines.append("")
    lines.append("  " + "=" * 55)
    lines.append("  📊 AWT Diagnosis (deterministic — no AI)")
    lines.append("  " + "=" * 55)

    # Basic info
    lines.append(f"  Step:     {context.get('step')} — {context.get('description', '')}")
    lines.append(f"  Action:   {context.get('action', '')}")
    lines.append(f"  Error:    {context.get('error', '')}")
    if context.get("actual_cause"):
        lines.append(f"    ↳ actual cause: {context['actual_cause']}")

    # Browser context
    if context.get("url"):
        lines.append(f"  URL:      {context['url']}")
    if context.get("page_title"):
        lines.append(f"  Title:    {context['page_title']}")
    if context.get("screenshot"):
        lines.append(f"  Screenshot: {context['screenshot']}")

    # Console errors
    if context.get("console_errors"):
        lines.append(f"  Console:  {len(context['console_errors'])} error(s)")
        for err in context["console_errors"][:3]:
            lines.append(f"    → {str(err)[:120]}")

    # Classification
    ftype = context.get("failure_type", "unknown")
    lines.append("")
    lines.append(f"  Category: {ftype}")

    # Investigation checklist
    checklist = context.get("investigation", [])
    if checklist:
        lines.append("  Investigation:")
        for item in checklist:
            lines.append(f"    □ {item}")

    # Learned hint
    if learned_hint:
        lines.append("")
        lines.append("  💡 Previously solved:")
        lines.append(
            f"    This failure ({learned_hint.get('error_type', '')}) "
            f"was fixed before: {learned_hint.get('fix_description', '')}"
        )
        lines.append(f"    (seen {learned_hint.get('hit_count', 0)} time(s))")

    # Re-run guide
    if scenario_file:
        lines.append("")
        lines.append(f"  Retest: aat run {scenario_file}")

    lines.append("  " + "=" * 55)
    return "\n".join(lines)


def format_skill_diagnosis(
    context: dict[str, Any],
    scenario_file: str = "",
    attempt: int = 1,
    max_attempts: int = 5,
) -> str:
    """Format diagnosis as structured block for AI coding assistants.

    Output is a machine-readable block that Claude Code, Gemini Code Assist,
    GitHub Copilot, and other AI tools can parse and act on.
    """
    # Infer possible cause from failure type
    cause_map = {
        "element_not_found": "Target text/selector changed or not yet rendered",
        "timeout": "Page/element load exceeded timeout",
        "navigation_error": "URL unreachable — check server",
        "auth_error": "Auth failed — wrong credentials or expired session",
        "server_error": "Server returned 5xx — check server logs",
        "selector_changed": "CSS selector no longer matches — UI updated",
        "assertion_failed": "Expected content not found on page",
        "unknown": "Unexpected error — check screenshot",
    }
    ftype = context.get("failure_type", "unknown")
    possible_cause = cause_map.get(ftype, cause_map["unknown"])

    lines = [
        "",
        "=== AWT SKILL DEVQA ===",
        f"SCENARIO: {scenario_file}",
        f"FAILED_STEP: {context.get('step', '?')} - {context.get('action', '?')}",
        f"ERROR: {context.get('error', 'unknown')}",
    ]
    # The step's own message can be an interpretation of a broken assertion.
    # When the step died for another reason, say so explicitly.
    if context.get("actual_cause"):
        lines.append(f"ACTUAL_CAUSE: {context['actual_cause']}")
    lines += [
        f"SCREENSHOT: {context.get('screenshot', 'N/A')}",
        f"URL: {context.get('url', 'N/A')}",
        f"PAGE_TITLE: {context.get('page_title', 'N/A')}",
        f"CATEGORY: {ftype}",
        f"POSSIBLE_CAUSE: {possible_cause}",
    ]

    # Critical failure flag
    if context.get("critical"):
        lines.append("CRITICAL_FAILURE: true")
        lines.append("EFFECT: Test stopped, remaining steps skipped")

    # Nav-zone warnings (False Positive risk)
    nav_warns = context.get("nav_warnings", [])
    if nav_warns:
        lines.append(f"NAV_ZONE_WARNINGS: {len(nav_warns)}")
        for w in nav_warns:
            lines.append(f"  - {w}")

    lines.extend(
        [
            f"FIX_TARGET: {scenario_file}",
            f"RETRY_CMD: aat run --skill-mode {scenario_file}",
            f"ATTEMPTS: {attempt}/{max_attempts}",
            "=======================",
            "",
        ]
    )
    return "\n".join(lines)


def check_learned_hint(
    store: LearnedStore | None,
    failure_type: str,
) -> dict[str, Any] | None:
    """Check if we've seen this failure before."""
    if store is None:
        return None
    try:
        return store.find_similar_failure(failure_type)
    except Exception:
        return None
