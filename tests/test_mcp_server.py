"""Tests for the MCP server's command building.

The server is not part of the installed package — it is a script the MCP host
runs — so it is loaded from its path here, and the whole module is skipped when
the `mcp` SDK is not installed (CI installs only the project's own extras).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytest.importorskip("mcp.server.fastmcp", reason="the MCP SDK is an optional, separate install")

_SERVER = Path(__file__).resolve().parents[1] / "mcp" / "server.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("awt_mcp_server_under_test", _SERVER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def server() -> ModuleType:
    return _load()


class TestRunCommand:
    """What the two run tools hand to the CLI."""

    def test_no_report_leaves_the_flag_off(self, server: ModuleType) -> None:
        """An empty value must not become `--report=`, which the CLI rejects."""
        cmd = server._run_command("scenarios/login.yaml", "concise", "before-after", "")

        assert not any(part.startswith("--report") for part in cmd)
        assert cmd[-1] == "scenarios/login.yaml"

    def test_a_requested_format_is_passed_through(self, server: ModuleType) -> None:
        cmd = server._run_command("scenarios/login.yaml", "concise", "before-after", "pdf")

        assert "--report=pdf" in cmd
        assert "--report-screenshots=failures" in cmd
        assert cmd[-1] == "scenarios/login.yaml"

    def test_the_screenshot_policy_is_passed_through(self, server: ModuleType) -> None:
        """Asking through MCP for the passing steps must reach the CLI too."""
        cmd = server._run_command("scenarios/login.yaml", "concise", "before-after", "pdf", "all")

        assert "--report-screenshots=all" in cmd

    def test_the_policy_stays_off_when_no_report_is_wanted(self, server: ModuleType) -> None:
        """Without a report there is nothing to illustrate, so nothing is said."""
        cmd = server._run_command("scenarios/login.yaml", "concise", "before-after", "", "all")

        assert not any(part.startswith("--report") for part in cmd)

    def test_the_approval_gate_is_still_there(self, server: ModuleType) -> None:
        """--skill-mode moves approval to the tool call; it never removes it.

        There is no flag here that answers the prompt on the user's behalf, and
        this test exists so that adding one has to be a deliberate act.
        """
        cmd = server._run_command("scenarios/login.yaml", "concise", "before-after", "pdf")

        assert "--skill-mode" in cmd
        assert not any("approve" in part or part == "-y" for part in cmd)

    def test_verbosity_and_screenshots_reach_the_cli(self, server: ModuleType) -> None:
        cmd = server._run_command("scenarios/", "detailed", "on-failure", "")

        assert "--verbosity=detailed" in cmd
        assert "--screenshots=on-failure" in cmd
