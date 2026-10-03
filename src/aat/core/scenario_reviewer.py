"""ScenarioReviewer — human-readable scenario display + approval prompt.

Converts YAML scenario steps into a readable checklist before execution,
waits for user approval, and supports editing the YAML before proceeding.

Used by `aat devqa` before the first run and before each retry.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import typer
import yaml

# ---------------------------------------------------------------------------
# Action → (icon, label) mapping
# ---------------------------------------------------------------------------

_ACTION_MAP: dict[str, tuple[str, str]] = {
    "navigate": ("🌐", "Navigate"),
    "find_and_click": ("🖱 ", "Click"),
    "find_and_double_click": ("🖱 ", "Double-click"),
    "find_and_right_click": ("🖱 ", "Right-click"),
    "click_at": ("🖱 ", "Click at"),
    "find_and_type": ("⌨ ", "Type"),
    "type_text": ("⌨ ", "Type"),
    "find_and_clear": ("⌨ ", "Clear"),
    "assert_url": ("✅", "Assert URL"),
    "assert_text": ("✅", "Assert text"),
    "assert": ("✅", "Assert"),
    "assert_screen_changed": ("👁 ", "Assert changed"),
    "wait": ("⏳", "Wait"),
    "scroll": ("📜", "Scroll"),
    "screenshot": ("📸", "Screenshot"),
    "go_back": ("↩ ", "Go back"),
    "refresh": ("🔄", "Refresh"),
    "press_key": ("⌨ ", "Press key"),
    "key_combo": ("⌨ ", "Key combo"),
    "save_session": ("💾", "Save session"),
    "load_session": ("💾", "Load session"),
}

_PASSWORD_HINTS = frozenset({"password", "비밀번호", "passwd", "pw", "pass"})

_WIDTH = 56


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class ScenarioReviewer:
    """Show a scenario in human-readable form and collect user approval."""

    def show_and_approve(
        self,
        scenario_yaml: str,
        scenario_path: Path | None = None,
        *,
        attempt: int = 1,
        previous_yaml: str | None = None,
        auto_approve: bool = False,
    ) -> bool:
        """Display scenario and return True if user approves.

        Args:
            scenario_yaml: Current scenario YAML text.
            scenario_path: Path where the YAML is saved (for [e] edit).
            attempt: Attempt number (1 = first run, >1 = retry).
            previous_yaml: Previous scenario YAML (for diff on retries).
            auto_approve: Skip prompt, always return True (CI mode).

        Returns:
            True  → proceed with execution
            False → user cancelled
        """
        try:
            scenario = yaml.safe_load(scenario_yaml) or {}
        except yaml.YAMLError:
            typer.echo("[AWT] Warning: could not parse scenario YAML for review")
            return auto_approve or self._prompt_raw()

        self._print_header(scenario, attempt)
        steps = scenario.get("steps", [])
        self._print_steps(steps, previous_yaml)
        self._print_footer()

        if auto_approve:
            typer.echo("[AWT] --auto-approve: proceeding automatically")
            return True

        return self._prompt(scenario_yaml, scenario_path)

    # -----------------------------------------------------------------------
    # Rendering
    # -----------------------------------------------------------------------

    def _print_header(self, scenario: dict[str, Any], attempt: int) -> None:
        name = scenario.get("name", "Scenario")
        steps = scenario.get("steps", [])
        sc_id = scenario.get("id", "")

        typer.echo()
        typer.echo("━" * _WIDTH)
        label = " Scenario Review" if attempt == 1 else f" Updated Scenario (attempt {attempt})"
        badge = f"{sc_id} · {len(steps)} steps" if sc_id else f"{len(steps)} steps"
        typer.echo(f"{label}  [{badge}]")
        typer.echo(f" {name}")
        typer.echo("━" * _WIDTH)

    def _print_steps(
        self,
        steps: list[dict[str, Any]],
        previous_yaml: str | None,
    ) -> None:
        prev_steps: dict[int, dict[str, Any]] = {}
        if previous_yaml:
            try:
                prev = yaml.safe_load(previous_yaml) or {}
                prev_steps = {s.get("step", i): s for i, s in enumerate(prev.get("steps", []))}
            except yaml.YAMLError:
                pass

        for step in steps:
            line = self._format_step(step)
            step_num = step.get("step", 0)

            # Diff marker for retries
            if prev_steps:
                prev_step = prev_steps.get(step_num)
                changed = prev_step is None or self._step_changed(prev_step, step)
                marker = "  ← changed" if changed else ""
            else:
                marker = ""

            typer.echo(f"{line}{marker}")

    def _print_footer(self) -> None:
        typer.echo("━" * _WIDTH)
        typer.echo(" [Enter] Run    [e] Edit YAML    [n] Cancel")
        typer.echo("━" * _WIDTH)

    # -----------------------------------------------------------------------
    # Step formatting
    # -----------------------------------------------------------------------

    def _format_step(self, step: dict[str, Any]) -> str:
        action = step.get("action", "")
        icon, label = _ACTION_MAP.get(action, ("▸ ", action))
        step_num = step.get("step", "?")
        detail = self._format_detail(step, action)
        critical_tag = "  ⛔stop" if step.get("critical") or step.get("on_fail") == "stop" else ""
        return f" {str(step_num):>2}. {icon} {label:<14}  {detail}{critical_tag}"

    def _format_detail(self, step: dict[str, Any], action: str) -> str:  # noqa: PLR0911
        def _s(key: str, default: str = "") -> str:
            return str(step.get(key) or default)

        if action == "navigate":
            return _s("value")

        if action in ("find_and_click", "find_and_double_click", "find_and_right_click"):
            t = step.get("target") or {}
            text = str(t.get("text") or t.get("selector") or "")
            return f'"{text}"' if text else ""

        if action == "click_at":
            v = _s("value")
            x, _, y = v.partition(",")
            return f"x={x}, y={y}"

        if action == "find_and_type":
            t = step.get("target") or {}
            field = str(t.get("text") or t.get("selector") or "")
            value = self._mask_if_password(field, _s("value"))
            return f'"{field}" → "{value}"'

        if action == "type_text":
            value = self._mask_if_password(_s("description"), _s("value"))
            return f'"{value}"'

        if action == "assert_url":
            return _s("value")

        if action in ("assert_text", "assert"):
            # Mirror executor.py: target.text wins, then value. Reading only
            # `value` left every target.text assertion blank in this panel —
            # the reviewer must show what the step actually checks.
            t = step.get("target") or {}
            return str(t.get("text") or "") or _s("value") or _s("expected")

        if action == "assert_screen_changed":
            thresh = step.get("threshold") or step.get("change_threshold")
            return f"threshold {thresh}" if thresh else ""

        if action == "wait":
            raw = _s("value", "0")
            try:
                return f"{int(raw) / 1000:.1f}s"
            except (ValueError, TypeError):
                return raw

        if action == "scroll":
            return _s("description")

        if action == "screenshot":
            return ""

        if action in ("press_key", "key_combo"):
            return _s("value")

        if action in ("save_session", "load_session"):
            return _s("name")

        # Fallback: show description
        return _s("description")[:40]

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _mask_if_password(hint: str, value: str) -> str:
        hint_lower = hint.lower()
        if any(h in hint_lower for h in _PASSWORD_HINTS):
            return "•" * min(len(value), 8)
        return value

    @staticmethod
    def _step_changed(old: dict[str, Any], new: dict[str, Any]) -> bool:
        """Check if any meaningful field changed between two steps."""
        for key in ("action", "value", "target", "selector", "critical", "on_fail"):
            if old.get(key) != new.get(key):
                return True
        return False

    # -----------------------------------------------------------------------
    # Prompt
    # -----------------------------------------------------------------------

    def _prompt(self, scenario_yaml: str, scenario_path: Path | None) -> bool:
        """Interactive prompt: Enter / e / n.

        Reads from /dev/tty (not stdin) to prevent pipe bypass.
        """
        if not _is_interactive():
            typer.echo(
                "[AWT] ERROR: approval requires an interactive terminal. "
                "Cannot proceed in non-interactive mode."
            )
            return False

        while True:
            try:
                answer = _read_tty("▶ ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                typer.echo()
                typer.echo("[AWT] Cancelled")
                return False

            if answer == "" or answer == "y":
                return True
            if answer == "n":
                typer.echo("[AWT] Cancelled by user.")
                return False
            if answer == "e":
                changed = self._open_editor(scenario_yaml, scenario_path)
                if not changed:
                    typer.echo("[AWT] No changes — running original scenario.")
                return True
            typer.echo("  Enter=Run  e=Edit  n=Cancel")

    @staticmethod
    def _prompt_raw() -> bool:
        """Fallback prompt when YAML parse failed."""
        if not _is_interactive():
            typer.echo("[AWT] ERROR: approval requires an interactive terminal.")
            return False
        try:
            answer = _read_tty("Proceed? [Enter=yes / n=no] ").strip().lower()
            return answer != "n"
        except (EOFError, KeyboardInterrupt):
            return False

    @staticmethod
    def _open_editor(scenario_yaml: str, scenario_path: Path | None) -> bool:
        """Open YAML in $EDITOR. Returns True if file was modified."""
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"

        # Use existing file or write to temp
        if scenario_path and scenario_path.exists():
            target = scenario_path
            original_mtime = target.stat().st_mtime
            subprocess.run([editor, str(target)])
            return target.stat().st_mtime != original_mtime

        # No file path — write to temp, then copy back if changed
        with tempfile.NamedTemporaryFile(
            suffix=".yaml", mode="w", encoding="utf-8", delete=False
        ) as f:
            f.write(scenario_yaml)
            tmp = Path(f.name)

        original_mtime = tmp.stat().st_mtime
        subprocess.run([editor, str(tmp)])
        changed = tmp.stat().st_mtime != original_mtime

        if changed and scenario_path:
            scenario_path.write_text(tmp.read_text("utf-8"), encoding="utf-8")
            typer.echo(f"[AWT] Saved → {scenario_path}")

        tmp.unlink(missing_ok=True)
        return changed


# ---------------------------------------------------------------------------
# TTY helpers — read from /dev/tty to prevent pipe bypass (like sudo)
# ---------------------------------------------------------------------------


def _is_interactive() -> bool:
    """Check if the current process has an interactive terminal."""
    if not sys.stdin.isatty():
        return False
    # Also check /dev/tty accessibility (may not exist in containers)
    try:
        with open("/dev/tty"):  # noqa: SIM115
            return True
    except OSError:
        return sys.stdin.isatty()  # Windows fallback


def can_prompt() -> bool:
    """Whether there is a human to ask in this process.

    Read-only, and it decides nothing: approval still comes from the prompt and
    from nowhere else, and both answers lead to the same place when approval is
    missing — nothing runs.

    It exists so the exit code can tell two opposite events apart. "The human
    said no" and "there was no human to ask" are the same event to the gate,
    but to a CI pipeline the first is a deliberate stop and the second means
    the suite was never run. Reporting both as 0 told the pipeline that
    unchecked work had passed.
    """
    return _is_interactive()


def _read_tty(prompt: str = "") -> str:
    """Read a line from /dev/tty, bypassing stdin redirection.

    This is the same technique sudo uses to read passwords — even if
    stdin is piped (``echo "" | aat run``), /dev/tty reads from the
    actual terminal device.
    """
    if prompt:
        sys.stderr.write(prompt)
        sys.stderr.flush()
    try:
        with open("/dev/tty") as tty:  # noqa: SIM115
            return tty.readline().rstrip("\n")
    except OSError:
        # /dev/tty unavailable (Windows, Docker without tty)
        return input(prompt)
