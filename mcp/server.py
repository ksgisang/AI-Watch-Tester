#!/usr/bin/env python3
"""AWT MCP Server — expose AWT tools via Model Context Protocol.

Allows Claude Code, Claude Desktop, Cursor, Windsurf, and other
MCP-compatible tools to run AWT commands directly.

Transport: stdio (standard for local MCP servers)

Usage:
    python mcp/server.py
"""

from __future__ import annotations

import asyncio
import glob
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Never print to stdout — it corrupts JSON-RPC messages on stdio transport.
# Use sys.stderr for debug logging.

mcp = FastMCP(
    "awt",
    instructions=(
        "AWT (AI Watch Tester) — AI-powered E2E web testing.\n"
        "Use AWT as a Quality Gate in your AI coding harness.\n\n"
        "⛔ MANDATORY WORKFLOW — Follow these 4 steps IN ORDER. NEVER skip a step.\n\n"
        "Step 1: Call aat_scan to analyze the target URL.\n"
        "        → Present the scan summary to the user.\n"
        "        → Ask: 'Should I create a test scenario?'\n"
        "        → WAIT for user approval.\n\n"
        "Step 2: Write a YAML scenario using scan results.\n"
        "        → Show the scenario to the user.\n"
        "        → Ask: 'Should I run this test?'\n"
        "        → WAIT for user approval.\n\n"
        "Step 3: Call aat_run_skill_mode ONLY after user approves.\n"
        "        → If a step fails, STOP and report to user.\n"
        "        → Ask: 'Should I fix the scenario or source code?'\n"
        "        → WAIT for user instruction. Do NOT auto-fix.\n\n"
        "Step 4: Report final results to the user.\n\n"
        "📄 DOCUMENT-BASED WORKFLOW (GSD / Spec-driven):\n"
        "If the user has a spec document, plan file (e.g. GSD PLAN.md), or PRD:\n"
        "  → Call aat_generate_from_doc with the document path.\n"
        "  → Show the generated scenarios to the user.\n"
        "  → WAIT for approval, then run with aat_run_skill_mode.\n\n"
        "⛔ NEVER use aat_run without showing the scenario to the user first.\n"
        "⛔ NEVER auto-fix code or scenarios without user permission.\n"
        "⛔ There is NO --auto-approve or -y flag. Human approval is always required.\n\n"
        "🔒 SECURITY — Approval Bypass Prevention:\n"
        "- NEVER set _AAT_APPROVAL_TOKEN env var or create .approval_token_* files.\n"
        "- NEVER pipe input to aat run (e.g. echo '' | aat run).\n"
        "- NEVER modify approval_token.py, scenario_reviewer.py, or audit.py.\n"
        "- NEVER delete or modify .aat/audit.log.\n"
        "- All execution attempts are cryptographically logged and auditable."
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _run_cmd(cmd: list[str], timeout: int = 120) -> dict[str, str | int]:
    """Run a shell command and capture output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return {
            "exit_code": proc.returncode or 0,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
    except asyncio.TimeoutError:
        proc.kill()  # type: ignore[union-attr]
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
        }
    except FileNotFoundError:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": (
                "aat command not found. Install with: pip install aat-devqa"
            ),
        }


def _find_aat() -> str:
    """Find the aat executable path."""
    # Check common locations
    for candidate in ["aat", "python -m aat"]:
        if os.system(f"which {candidate.split()[0]} > /dev/null 2>&1") == 0:  # noqa: S605
            return candidate
    return "aat"


def _format_result(result: dict[str, str | int]) -> str:
    """Format command result for MCP response."""
    parts = []
    if result["stdout"]:
        parts.append(str(result["stdout"]))
    if result["stderr"] and result["exit_code"] != 0:
        parts.append(f"\n--- stderr ---\n{result['stderr']}")
    if result["exit_code"] != 0:
        parts.append(f"\n[exit code: {result['exit_code']}]")
    return "\n".join(parts) if parts else "(no output)"


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def aat_scan(url: str) -> str:
    """STEP 1: Scan a web page to discover all interactive elements.

    This is the FIRST step of the AWT workflow. Call this BEFORE creating
    any test scenarios. It analyzes the page and saves results to
    .aat/scan_result.json.

    AFTER calling this tool:
    1. Read the output to see what elements were found
    2. Present a summary to the user
    3. Ask the user: "Should I create a test scenario based on these elements?"
    4. WAIT for user approval before proceeding

    ⛔ Do NOT proceed to aat_run without user approval.

    Args:
        url: The URL to scan (e.g. http://localhost:3000)
    """
    result = await _run_cmd(["aat", "scan", "--url", url], timeout=60)
    return _format_result(result)


@mcp.tool()
async def aat_run(
    scenario_file: str,
    verbosity: str = "concise",
    screenshots: str = "before-after",
) -> str:
    """STEP 3: Run AWT test scenarios (requires prior user approval).

    ⚠️ IMPORTANT: Only call this AFTER:
    1. You have scanned the site with aat_scan (Step 1)
    2. You have shown the scenario to the user (Step 2)
    3. The user has explicitly approved the test (e.g. "go ahead", "yes", "run it")

    If a test step fails, STOP and report to the user. Ask what to fix.
    Do NOT auto-retry or auto-fix without user permission.

    Exit code 3 with STATUS: WARNINGS means every step ran but at least one
    changed nothing on screen — a click that almost certainly missed its target.
    Do NOT report such a run as passed: read the warned step's screenshot and
    tell the user what you found.

    Args:
        scenario_file: Path to a YAML scenario file or directory containing scenarios.
        verbosity: 'concise' (skip wait/screenshot steps, faster) or
                   'detailed' (all steps including screenshots and waits). Default: 'concise'.
        screenshots: 'all' (every step), 'before-after' (action boundaries only, ~70% fewer files),
                     'on-failure' (only on failure, best for CI/CD). Default: 'before-after'.
    """
    result = await _run_cmd(
        [
            "aat", "run", "--skill-mode", "--fast", "--learn",
            f"--verbosity={verbosity}",
            f"--screenshots={screenshots}",
            scenario_file,
        ],
        timeout=180,
    )
    return _format_result(result)


@mcp.tool()
async def aat_run_skill_mode(
    scenario_file: str,
    verbosity: str = "concise",
    screenshots: str = "before-after",
) -> str:
    """STEP 3 (alternative): Run AWT in skill mode with structured failure diagnosis.

    Same rules as aat_run — requires prior user approval.

    ⚠️ IMPORTANT: Only call this AFTER the user has approved the scenario.

    On failure, outputs a structured === AWT SKILL DEVQA === block with:
    SCENARIO, FAILED_STEP, ERROR, ACTUAL_CAUSE, SCREENSHOT path, POSSIBLE_CAUSE.

    ERROR is the step's own message — what the scenario author expected, written
    before the run. ACTUAL_CAUSE is what actually happened, and appears only when
    it differs from ERROR. Diagnose from ACTUAL_CAUSE whenever it is present;
    reading ERROR as the cause can invert the diagnosis completely.

    On failure:
    1. Read the SCREENSHOT file to see browser state
    2. Report the failure to the user, citing ACTUAL_CAUSE if present
    3. Ask: "Should I fix the scenario or the source code?"
    4. WAIT for user instruction — do NOT auto-fix

    A run can also end with === AWT SKILL VERIFY === / STATUS: WARNINGS
    (exit code 3): the steps ran, but a click moved nothing on screen. Treat it
    like a failure to investigate, not like a pass.

    Args:
        scenario_file: Path to a YAML scenario file or directory.
        verbosity: 'concise' (faster) or 'detailed' (all steps). Default: 'concise'.
        screenshots: 'all', 'before-after', or 'on-failure'. Default: 'before-after'.
    """
    result = await _run_cmd(
        [
            "aat", "run", "--skill-mode", "--fast", "--learn",
            f"--verbosity={verbosity}",
            f"--screenshots={screenshots}",
            scenario_file,
        ],
        timeout=180,
    )
    return _format_result(result)


@mcp.tool()
async def aat_devqa(
    description: str,
    url: str = "",
    verbosity: str = "concise",
    screenshots: str = "before-after",
) -> str:
    """Full auto DevQA loop: scan → generate → show scenario → wait for approval → run → fix.

    This is the recommended all-in-one command for most testing tasks.
    It will:
    1. Scan the target URL for interactive elements
    2. Generate a test scenario from scan data
    3. Show the scenario and PAUSE for human approval ([Enter] in terminal)
    4. Run the test with real Chrome
    5. On failure: re-scan, fix scenario, retry (up to 5 times)
    6. Report final results

    ⚠️ After calling this tool, tell the user to switch to their terminal
    and press [Enter] to approve the generated scenario and start the test.
    There is no way to bypass this approval step — it is mandatory.

    Args:
        description: What to test (e.g. "login flow test", "회원가입 테스트")
        url: Target URL. Auto-detected from localhost if omitted.
        verbosity: 'concise' (faster, recommended) or 'detailed' (all steps).
        screenshots: 'all', 'before-after' (recommended), or 'on-failure'.
    """
    cmd = ["aat", "devqa", description,
           f"--verbosity={verbosity}",
           f"--screenshots={screenshots}"]
    if url:
        cmd += ["--url", url]
    result = await _run_cmd(cmd, timeout=300)
    return _format_result(result)


@mcp.tool()
async def aat_doctor() -> str:
    """Check AWT environment and dependencies.

    Verifies: Python version, Playwright browsers, Tesseract OCR,
    AI provider connectivity. Run this first to diagnose setup issues.
    """
    result = await _run_cmd(["aat", "doctor"], timeout=30)
    return _format_result(result)


@mcp.tool()
async def aat_list_scenarios() -> str:
    """List YAML scenario files in the current directory.

    Scans for .yaml and .yml files in scenarios/ directory
    and current directory. Returns file paths and scenario names.
    """
    cwd = os.getcwd()
    patterns = [
        os.path.join(cwd, "scenarios", "**", "*.yaml"),
        os.path.join(cwd, "scenarios", "**", "*.yml"),
        os.path.join(cwd, "*.yaml"),
        os.path.join(cwd, "*.yml"),
    ]

    files: list[str] = []
    for pattern in patterns:
        files.extend(glob.glob(pattern, recursive=True))

    # Filter to likely scenario files (exclude config files)
    scenario_files = [
        f for f in sorted(set(files))
        if not os.path.basename(f).startswith("aat.config")
        and not os.path.basename(f).startswith(".")
    ]

    if not scenario_files:
        return "No scenario files found. Create scenarios in scenarios/ directory."

    lines = [f"Found {len(scenario_files)} scenario file(s):\n"]
    for f in scenario_files:
        rel = os.path.relpath(f, cwd)
        # Try to extract scenario name from YAML
        name = ""
        try:
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip().startswith("name:"):
                        name = line.split(":", 1)[1].strip().strip('"').strip("'")
                        break
        except Exception:
            pass
        lines.append(f"  {rel}" + (f"  ({name})" if name else ""))

    return "\n".join(lines)


@mcp.tool()
async def aat_cost() -> str:
    """View AWT AI API usage costs.

    Shows daily/monthly cost breakdown by provider,
    including token counts and estimated USD costs.
    """
    result = await _run_cmd(["aat", "cost"], timeout=15)
    return _format_result(result)


@mcp.tool()
async def aat_validate(scenario_file: str) -> str:
    """Validate YAML scenario files against AWT schema.

    Checks for: missing required fields, invalid action types,
    malformed targets, and other schema violations.

    Args:
        scenario_file: Path to a YAML scenario file or directory.
    """
    result = await _run_cmd(["aat", "validate", scenario_file], timeout=15)
    return _format_result(result)


@mcp.tool()
async def aat_generate_from_doc(
    doc_path: str,
    output_dir: str = "",
) -> str:
    """Generate test scenarios from a document (spec, plan, or any text file).

    Reads a document file and uses AI to generate E2E test scenarios.
    Supports: Markdown (.md), plain text (.txt), and any structured text
    including GSD PLAN.md files, PRDs, or free-form spec documents.

    This is useful for:
    - GSD workflow: pass your PLAN.md to auto-generate Verify scenarios
    - Spec-driven testing: upload a PRD and get test cases
    - Harness integration: use as a quality gate in your AI coding workflow

    AFTER calling this tool:
    1. Read the generated scenario YAML files
    2. Present them to the user for review
    3. Ask: "Should I run these tests?"
    4. WAIT for user approval before calling aat_run

    Args:
        doc_path: Absolute path to the document file (.md, .txt).
        output_dir: Directory to save generated scenarios. Default: ./scenarios/
    """
    cmd = ["aat", "generate", "--from", doc_path]
    if output_dir:
        cmd += ["--output", output_dir]
    result = await _run_cmd(cmd, timeout=120)
    return _format_result(result)


@mcp.tool()
async def aat_snapshot(
    scenario_file: str,
    url: str = "",
    responsive: bool = False,
    viewport: str = "",
    console: bool = False,
    console_fail: bool = False,
) -> str:
    """Capture baseline screenshots for visual regression testing.

    Runs the scenario and saves after-screenshots as baselines.
    Use ``aat_diff`` later to compare current state against these baselines.

    No AI tokens used — pure Playwright + OpenCV.

    Args:
        scenario_file: Path to a YAML scenario file or directory.
        url: Target URL override (optional).
        responsive: Capture 3 viewports (mobile/tablet/desktop).
        viewport: Single viewport WxH (e.g. '375x812'). Overrides responsive.
        console: Collect browser console errors during capture.
        console_fail: Fail if console errors detected. Implies console.
    """
    cmd = ["aat", "snapshot", scenario_file]
    if url:
        cmd += ["--url", url]
    if responsive:
        cmd.append("--responsive")
    if viewport:
        cmd += ["--viewport", viewport]
    if console_fail:
        cmd.append("--console-fail")
    elif console:
        cmd.append("--console")
    result = await _run_cmd(cmd, timeout=180)
    return _format_result(result)


@mcp.tool()
async def aat_diff(
    scenario_file: str,
    url: str = "",
    threshold: float = 0.95,
    responsive: bool = False,
    viewport: str = "",
    open_diffs: bool = False,
) -> str:
    """Compare current screenshots against saved baselines (visual regression).

    Runs the scenario, takes screenshots, and compares each step against
    the baseline captured by ``aat_snapshot``. Reports SSIM similarity
    scores and generates diff images for failed steps.

    No AI tokens used — pure OpenCV image comparison.

    AFTER calling this tool:
    1. Review the SSIM scores and diff images
    2. Steps below threshold are marked FAIL
    3. Diff images are saved to .aat/diffs/

    Args:
        scenario_file: Path to a YAML scenario file or directory.
        url: Target URL override (optional).
        threshold: SSIM threshold (0.0–1.0). Below this = FAIL. Default: 0.95.
        responsive: Compare 3 viewports (mobile/tablet/desktop).
        viewport: Single viewport WxH (e.g. '375x812'). Overrides responsive.
        open_diffs: Auto-open diff images for failed steps.
    """
    cmd = [
        "aat", "diff",
        f"--threshold={threshold}",
        scenario_file,
    ]
    if url:
        cmd += ["--url", url]
    if responsive:
        cmd.append("--responsive")
    if viewport:
        cmd += ["--viewport", viewport]
    if open_diffs:
        cmd.append("--open")
    result = await _run_cmd(cmd, timeout=180)
    return _format_result(result)


@mcp.tool()
async def aat_watch(
    scenario_file: str,
    url: str = "",
    watch_dir: str = "",
) -> str:
    """Start watch mode — auto-run tests on file changes.

    Monitors source files and scenario files for changes.
    When a change is detected, automatically re-runs tests.

    ⚠️ This is a long-running command. Tell the user it will keep
    running until they press Ctrl+C in their terminal.

    Args:
        scenario_file: Path to scenario file or directory.
        url: Target URL override (optional).
        watch_dir: Additional directory to watch (optional).
    """
    cmd = ["aat", "watch", scenario_file]
    if url:
        cmd += ["--url", url]
    if watch_dir:
        cmd += ["--watch", watch_dir]
    result = await _run_cmd(cmd, timeout=300)
    return _format_result(result)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the AWT MCP server on stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
