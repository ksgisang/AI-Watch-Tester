"""aat devqa — fully automated test loop orchestrator.

Single command that controls the entire test cycle:
  URL detect → scan → scenario generate → run → fix → retry

The AI coding assistant only runs this command.
AWT handles everything else — no AI intervention in the loop.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import typer

from aat.core.config import load_config
from aat.core.exceptions import AATError

_MAX_ATTEMPTS = 5
_COMMON_PORTS = [3000, 8080, 5000, 4200, 8000, 5173, 3001, 8888, 9500]


def devqa_command(
    description: str = typer.Argument(
        help="Test description (e.g. 'login and dashboard test').",
    ),
    url: str | None = typer.Option(
        None,
        "--url",
        "-u",
        help="App URL (auto-detected if omitted).",
    ),
    config_path: str | None = typer.Option(None, "--config", "-c"),
    max_attempts: int = typer.Option(_MAX_ATTEMPTS, "--max-attempts", "-m"),
    fast: bool = typer.Option(
        False,
        "--fast",
        help=(
            "Enable fast mode: DOM matching, skipping OCR and Vision AI. "
            "If the selector breaks, one deterministic attempt is still made "
            "from the picture an earlier run banked for that element."
        ),
    ),
    verbosity: str = typer.Option(
        "detailed",
        "--verbosity",
        "-V",
        help=(
            "Scenario verbosity: 'detailed' (60-80 steps, all verification) or "
            "'concise' (12-15 steps, core actions only)."
        ),
    ),
    screenshots: str = typer.Option(
        "all",
        "--screenshots",
        help=(
            "Screenshot strategy: 'all' (every step, default), "
            "'before-after' (action boundaries, ~70% fewer files), "
            "'on-failure' (failures only, CI/CD optimized)."
        ),
    ),
) -> None:
    """Run fully automated DevQA loop: scan → generate → test → fix → retry."""
    try:
        asyncio.run(
            _devqa(
                description,
                url,
                config_path,
                max_attempts,
                fast,
                verbosity,
                screenshots,
            )
        )
    except AATError as e:
        typer.echo(f"[AWT] Error: {e}", err=True)
        raise typer.Exit(code=1) from None


async def _devqa(
    description: str,
    url_override: str | None,
    config_path: str | None,
    max_attempts: int,
    fast_mode: bool = False,
    verbosity: str = "detailed",
    screenshots: str = "all",
) -> None:
    start_time = time.monotonic()
    cfg_path = Path(config_path) if config_path else None
    config = load_config(config_path=cfg_path)
    data_dir = Path(config.data_dir)

    typer.echo()
    typer.echo(f'[AWT] DevQA: "{description}"')
    typer.echo("[AWT] " + "=" * 50)

    # -- Step 1: Detect URL ---------------------------------------------------
    app_url: str = url_override or config.url or ""
    if not app_url:
        app_url = await _detect_url() or ""
    if not app_url:
        app_url = typer.prompt("[AWT] App URL not detected. Enter URL")
    typer.echo(f"[AWT] Target: {app_url}")

    # -- Step 2: Scan ---------------------------------------------------------
    typer.echo("[AWT] Step 1/4: Scanning...")
    scan_path = data_dir / "scan_result.json"
    compare_arg = str(scan_path) if scan_path.exists() else None
    _run_aat(["scan", "--url", app_url] + (["--compare", compare_arg] if compare_arg else []))

    if not scan_path.exists():
        typer.echo("[AWT] Scan failed — no scan_result.json")
        raise typer.Exit(code=1)

    scan_data = json.loads(scan_path.read_text("utf-8"))
    elem_count = scan_data.get("element_count", 0)
    typer.echo(f"[AWT] Scan complete: {elem_count} elements found")

    # -- Step 3: Generate scenario -------------------------------------------
    typer.echo("[AWT] Step 2/4: Generating scenario...")
    scenario_dir = Path("scenarios")
    scenario_dir.mkdir(exist_ok=True)

    scenario_yaml = _generate_scenario(
        description,
        scan_data,
        app_url,
        config.test_accounts,
        verbosity=verbosity,
    )
    # Extract generated ID for filename
    sc_id = _next_scenario_id()
    # Re-read from generated YAML (id already set by _generate_scenario)
    import re as _re

    m = _re.search(r"id:\s*['\"]?(SC-\d+)", scenario_yaml)
    if m:
        sc_id = m.group(1)
    scenario_path = scenario_dir / f"{sc_id.lower()}_devqa.yaml"
    scenario_path.write_text(scenario_yaml, encoding="utf-8")
    typer.echo(f"[AWT] Scenario: {scenario_path}")

    # Show scenario in human-readable form and wait for approval
    from aat.core.scenario_reviewer import ScenarioReviewer

    reviewer = ScenarioReviewer()
    if not reviewer.show_and_approve(
        scenario_yaml,
        scenario_path,
        attempt=1,
        auto_approve=False,  # devqa always requires human approval
    ):
        # Same rule as `aat run`: a person saying no is 0, no person to ask is 4.
        from aat.cli.commands.run_cmd import _unapproved_exit_code

        raise typer.Exit(code=_unapproved_exit_code(1))

    # -- Step 4-6: Run + fix loop --------------------------------------------
    typer.echo("[AWT] Step 3/4: Testing...")
    passed = False
    attempt = 0
    #: How many times the scenario file was rewritten. The loop only ever
    #: repoints a locator, and every rewrite was shown and approved — but a
    #: run that needed four of them is telling you the scenario was stale,
    #: and nothing in the old ending said so.
    scenario_edits = 0

    for attempt in range(1, max_attempts + 1):
        typer.echo(f"\n[AWT] Attempt {attempt}/{max_attempts}")

        run_args = [
            "run",
            "--skill-mode",
            "--learn",
        ]
        if fast_mode:
            run_args.append("--fast")
        if verbosity != "detailed":
            run_args.extend(["--verbosity", verbosity])
        if screenshots != "all":
            run_args.extend(["--screenshots", screenshots])
        run_args.append(str(scenario_path))

        # Pass approval bypass via one-time token — user already approved above in this session
        import os as _os

        from aat.core.approval_token import ENV_VAR as _TOKEN_ENV
        from aat.core.approval_token import generate_token, store_token

        _token = generate_token()
        store_token(_token)
        env = {**_os.environ, _TOKEN_ENV: _token}
        exit_code = _run_aat(run_args, env=env)

        if exit_code == 0:
            passed = True
            break

        if attempt >= max_attempts:
            break

        # Fix: re-scan + update scenario
        typer.echo(f"[AWT] Fixing scenario (attempt {attempt})...")
        _run_aat(["scan", "--url", app_url, "--compare", str(scan_path)])

        # Reload scan data and regenerate
        scan_data = json.loads(scan_path.read_text("utf-8"))
        fail_info = _read_last_failure(data_dir)
        previous_yaml = scenario_yaml
        scenario_yaml = _fix_scenario(
            scenario_yaml,
            scan_data,
            fail_info,
            attempt,
        )
        scenario_path.write_text(scenario_yaml, encoding="utf-8")
        scenario_edits += 1

        # Show diff + approval before retry
        from aat.core.scenario_reviewer import ScenarioReviewer

        if not ScenarioReviewer().show_and_approve(
            scenario_yaml,
            scenario_path,
            attempt=attempt + 1,
            previous_yaml=previous_yaml,
            auto_approve=False,  # always require human approval for retry
        ):
            typer.echo("[AWT] Retry cancelled. The scenario file is left as it was rewritten.")
            raise typer.Exit(code=1)

    # -- Step 7/9: Report -----------------------------------------------------
    elapsed = (time.monotonic() - start_time) / 60
    typer.echo()
    typer.echo("[AWT] " + "=" * 50)
    if passed:
        typer.echo(f"[AWT] ✅ DevQA complete: ALL PASSED ({attempt} attempt(s), {elapsed:.1f}min)")
    else:
        typer.echo(f"[AWT] ❌ DevQA failed after {attempt} attempts ({elapsed:.1f}min)")

    _print_devqa_verdict(
        passed=passed,
        attempts=attempt,
        scenario_edits=scenario_edits,
        data_dir=data_dir,
    )

    if not passed:
        _report_failure(data_dir)
        raise typer.Exit(code=1)
    typer.echo("[AWT] " + "=" * 50)


# -- URL detection ------------------------------------------------------------


async def _detect_url() -> str | None:
    """Check common localhost ports for a running server."""
    import httpx

    for port in _COMMON_PORTS:
        url = f"http://localhost:{port}"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(url)
                if resp.status_code < 500:
                    typer.echo(f"[AWT] Detected: {url} (HTTP {resp.status_code})")
                    return url
        except Exception:
            continue
    return None


# -- Scenario generation from scan data --------------------------------------


def _generate_scenario(
    description: str,
    scan_data: dict[str, Any],
    app_url: str,
    test_accounts: dict[str, dict[str, str]] | None = None,
    verbosity: str = "detailed",
) -> str:
    """Generate YAML scenario from scan_result.json elements.

    Smart generation:
    1. Detect form fields (input/textarea) and add fill steps
    2. Use test_accounts for login/signup flows
    3. Match description keywords to infer intent
    4. Validate: every input has a value, submit follows inputs

    verbosity:
        'detailed' — include assert_screen_changed after each click (default)
        'concise'  — omit assert/wait steps; aim for 12-15 core steps
    """
    import yaml

    elements = scan_data.get("elements", [])
    account = (test_accounts or {}).get("default", {})
    desc_lower = description.lower()

    steps: list[dict[str, Any]] = [
        {
            "step": 1,
            "action": "navigate",
            "value": app_url,
            "description": f"Open {app_url}",
        }
    ]
    step_num = 2

    # Classify elements — handle both DOM and Flutter Semantics
    is_flutter = scan_data.get("is_flutter", False)
    inputs = _classify_inputs(elements, is_flutter)
    buttons = [
        e
        for e in elements
        if e.get("type") in ("button", "a", "semantics")
        and e.get("source") in ("dom", "semantics")
        and e.get("x", 0) > 100
        and e.get("role", "") != "textbox"
    ]

    # Detect intent from description
    intent = _detect_intent(desc_lower)

    # --- Form filling: add input steps before button clicks ---
    if intent in ("login", "signup", "search") or inputs:
        for inp_idx, inp in enumerate(inputs):
            value = _infer_input_value(inp, intent, account)
            if not value:
                continue

            target, extra = _build_input_target(
                inp,
                inp_idx,
                inputs,
                is_flutter,
            )
            if not target:
                continue

            step_dict: dict[str, Any] = {
                "step": step_num,
                "action": "find_and_type",
                "target": target,
                "value": value,
                "region": "main",
                "description": f"Enter {_input_description(inp)}",
            }
            step_dict.update(extra)

            steps.append(step_dict)
            step_num += 1

    # --- Button clicks: match keywords to buttons ---
    keywords = _extract_keywords(description)
    clicked_labels: set[str] = set()

    for kw in keywords:
        matched = _find_matching_elements(kw, buttons)
        for el in matched[:1]:
            label = el["label"]
            if label in clicked_labels:
                continue
            clicked_labels.add(label)

            is_submit = _is_submit_button(el, intent)
            click_step: dict[str, Any] = {
                "step": step_num,
                "action": "find_and_click",
                "target": {"text": label},
                "region": "main",
                "description": f'Click "{label}"',
            }
            if el.get("selector") and el["source"] == "dom":
                click_step["target"]["selector"] = el["selector"]
            if is_submit:
                click_step["critical"] = True

            steps.append(click_step)
            step_num += 1

            # Assert after click — detailed mode only
            if verbosity == "detailed":
                steps.append(
                    {
                        "step": step_num,
                        "action": "assert_screen_changed",
                        "threshold": 0.05,
                        "region": "main",
                        "description": f'Verify screen changed after "{label}"',
                    }
                )
                step_num += 1

    # --- Fallback: if no keywords matched, use prominent buttons ---
    if not clicked_labels:
        for el in buttons[:3]:
            steps.append(
                {
                    "step": step_num,
                    "action": "find_and_click",
                    "target": {"text": el["label"]},
                    "region": "main",
                    "description": f'Click "{el["label"]}"',
                }
            )
            step_num += 1

    # --- Validate: ensure inputs before submit ---
    steps = _validate_form_flow(steps, inputs, account)

    # Final screenshot
    steps.append(
        {
            "step": len(steps) + 1,
            "action": "screenshot",
            "description": "Capture final state",
        }
    )

    # Re-number steps
    for i, s in enumerate(steps, 1):
        s["step"] = i

    scenario = {
        "id": _next_scenario_id(),
        "name": description,
        "description": f"Auto-generated from scan: {description}",
        "steps": steps,
    }

    return yaml.safe_dump(
        scenario,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )


# -- Intent detection ---------------------------------------------------------


_INTENT_KEYWORDS: dict[str, list[str]] = {
    "login": ["로그인", "login", "sign in", "signin", "로그 인"],
    "signup": ["회원가입", "signup", "sign up", "register", "가입"],
    "search": ["검색", "search", "찾기", "find"],
    "generate": ["생성", "generate", "만들기", "create"],
}


def _classify_inputs(
    elements: list[dict[str, Any]],
    is_flutter: bool,
) -> list[dict[str, Any]]:
    """Classify input elements from scan data.

    Handles both DOM inputs and Flutter Semantics textboxes.
    Sorted by y-coordinate (top to bottom) for form order.
    """
    inputs: list[dict[str, Any]] = []

    for el in elements:
        el_type = el.get("type", "")
        role = el.get("role", "")

        if el_type in ("input", "textarea") or role == "textbox":
            inputs.append(el)

    # Sort by y-coordinate (form order: top to bottom)
    inputs.sort(key=lambda e: (e.get("y", 0), e.get("x", 0)))
    return inputs


def _build_input_target(
    inp: dict[str, Any],
    inp_idx: int,
    all_inputs: list[dict[str, Any]],
    is_flutter: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build target dict for an input field.

    Returns (target_dict, extra_step_fields).
    Priority: Semantics label > input type selector > nth-of-type > match_index
    """
    target: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    source = inp.get("source", "")
    label = str(inp.get("label", ""))

    # --- Priority 1: Semantics aria-label (Flutter) ---
    if source == "semantics" and label:
        target["text"] = label
        # Use method: semantics to force Semantics lookup
        if is_flutter:
            extra["method"] = "semantics"
        return target, extra

    # --- Priority 2: input[type] selector (DOM) ---
    input_type = inp.get("input_type", "")
    if input_type and input_type not in ("text", ""):
        target["selector"] = f'input[type="{input_type}"]'
        if label:
            target["text"] = label
        return target, extra

    # --- Priority 3: nth-of-type (DOM, multiple generic inputs) ---
    if source == "dom":
        # Count how many inputs before this one
        y_sorted_dom = [e for e in all_inputs if e.get("source") == "dom"]
        position = next(
            (i for i, e in enumerate(y_sorted_dom) if e is inp),
            inp_idx,
        )
        tag = inp.get("type", "input")
        if tag not in ("input", "textarea"):
            tag = "input"
        target["selector"] = f"{tag}:nth-of-type({position + 1})"
        if label:
            target["text"] = label
        return target, extra

    # --- Priority 4: match_index fallback ---
    if label:
        target["text"] = label
    else:
        target["selector"] = "input"
    extra["match_index"] = inp_idx
    return target, extra


def _detect_intent(desc_lower: str) -> str:
    """Detect test intent from description."""
    for intent, keywords in _INTENT_KEYWORDS.items():
        if any(kw in desc_lower for kw in keywords):
            return intent
    return "explore"


# -- Input value inference ----------------------------------------------------


_INPUT_TYPE_MAP: dict[str, str] = {
    "email": "test@example.com",
    "password": "Test1234!",
    "tel": "010-1234-5678",
    "search": "test query",
    "number": "1",
    "url": "https://example.com",
}

_LABEL_HINTS: dict[str, str] = {
    "이메일": "email",
    "email": "email",
    "e-mail": "email",
    "비밀번호": "password",
    "password": "password",
    "패스워드": "password",
    "이름": "name",
    "name": "name",
    "nickname": "name",
    "닉네임": "name",
    "전화": "tel",
    "phone": "tel",
    "연락처": "tel",
    "검색": "search",
    "search": "search",
}


def _infer_input_value(
    inp: dict[str, Any],
    intent: str,
    account: dict[str, str],
) -> str:
    """Infer a test value for an input field."""
    # Check input_type from scan data first
    input_type = (inp.get("input_type") or "").lower()
    if input_type in _INPUT_TYPE_MAP:
        if input_type == "email" and account.get("email"):
            return account["email"]
        if input_type == "password" and account.get("password"):
            return account["password"]
        return _INPUT_TYPE_MAP[input_type]

    # Check selector/label for type hints
    selector = (inp.get("selector") or "").lower()
    label = (inp.get("label") or "").lower()
    role = (inp.get("role") or "").lower()
    combined = f"{selector} {label} {role}"

    # Match by label hints
    for hint_text, field_type in _LABEL_HINTS.items():
        if hint_text in combined:
            # Use account data if available
            if field_type == "email" and account.get("email"):
                return account["email"]
            if field_type == "password" and account.get("password"):
                return account["password"]
            if field_type == "name" and account.get("name"):
                return account["name"]
            return _INPUT_TYPE_MAP.get(field_type, "test input")

    # Match by input type in selector
    for input_type, default_val in _INPUT_TYPE_MAP.items():
        if f'type="{input_type}"' in selector or f"type={input_type}" in selector:
            if input_type == "email" and account.get("email"):
                return account["email"]
            if input_type == "password" and account.get("password"):
                return account["password"]
            return default_val

    # Default for text inputs
    if intent == "search":
        return "test query"
    return "test input"


def _input_description(inp: dict[str, Any]) -> str:
    """Human-readable description of an input field."""
    label = str(inp.get("label", ""))
    if label and len(label) < 30:
        return label
    input_type = str(inp.get("input_type", ""))
    if input_type and input_type != "text":
        return input_type
    selector = str(inp.get("selector", ""))
    if "email" in selector.lower():
        return "email"
    if "password" in selector.lower():
        return "password"
    return "text field"


def _is_submit_button(el: dict[str, Any], intent: str) -> bool:
    """Check if element is a form submit button."""
    label = (el.get("label") or "").lower()
    submit_words = [
        "로그인",
        "login",
        "sign in",
        "submit",
        "제출",
        "가입",
        "register",
        "확인",
        "검색",
        "search",
        "생성",
        "create",
        "만들기",
        "generate",
    ]
    return any(w in label for w in submit_words)


# -- Flow validation ----------------------------------------------------------


def _validate_form_flow(
    steps: list[dict[str, Any]],
    inputs: list[dict[str, Any]],
    account: dict[str, str],
) -> list[dict[str, Any]]:
    """Validate and fix: ensure inputs are filled before submit."""
    # Check if there are find_and_type steps
    has_type_steps = any(s.get("action") == "find_and_type" for s in steps)

    if not has_type_steps and inputs:
        # Inputs exist but no type steps — add them before first click
        first_click_idx = next(
            (i for i, s in enumerate(steps) if s.get("action") == "find_and_click"),
            len(steps),
        )
        insert_steps: list[dict[str, Any]] = []
        for inp in inputs:
            value = _infer_input_value(inp, "explore", account)
            if not value:
                continue
            target: dict[str, Any] = {}
            if inp.get("selector"):
                target["selector"] = inp["selector"]
            if inp.get("label"):
                target["text"] = inp["label"]
            if not target:
                continue
            insert_steps.append(
                {
                    "step": 0,
                    "action": "find_and_type",
                    "target": target,
                    "value": value,
                    "region": "main",
                    "description": f"Enter {_input_description(inp)}",
                }
            )

        for s in reversed(insert_steps):
            steps.insert(first_click_idx, s)

    return steps


def _next_scenario_id() -> str:
    """Generate next SC-NNN id based on existing scenario files."""
    import glob
    import re

    existing: list[int] = []
    for f in glob.glob("scenarios/SC-*.yaml") + glob.glob("scenarios/SC-*.yml"):
        m = re.search(r"SC-(\d+)", f)
        if m:
            existing.append(int(m.group(1)))
    next_num = max(existing, default=0) + 1
    return f"SC-{next_num:03d}"


def _extract_keywords(description: str) -> list[str]:
    """Extract meaningful keywords from test description."""
    # Remove common filler words
    fillers = {
        "테스트",
        "test",
        "testing",
        "확인",
        "check",
        "verify",
        "the",
        "a",
        "an",
        "and",
        "or",
        "을",
        "를",
        "이",
        "가",
        "에서",
        "으로",
        "하기",
        "해줘",
        "해주세요",
    }
    words = description.replace("-", " ").replace("→", " ").split()
    return [w for w in words if w.lower() not in fillers and len(w) > 1]


def _find_matching_elements(
    keyword: str,
    elements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Find elements whose label contains the keyword."""
    kw = keyword.lower()
    matches = [el for el in elements if kw in el.get("label", "").lower()]
    # Prefer semantics > dom > ocr
    source_priority = {"semantics": 0, "dom": 1, "ocr": 2}
    matches.sort(key=lambda e: source_priority.get(e.get("source", "ocr"), 9))
    return matches


# -- Scenario fixing ----------------------------------------------------------


def _fix_scenario(
    yaml_text: str,
    scan_data: dict[str, Any],
    fail_info: dict[str, Any],
    attempt: int,
) -> str:
    """Fix scenario based on failure info and fresh scan data.

    Narrower than its name suggests, and the limit is worth stating: the
    rematch is driven by :func:`_find_matching_elements`, which keeps elements
    whose fresh label *contains* the text the scenario asked for. A label that
    grew ("Log in" -> "Log in now") is found; a label that was replaced
    ("Login" -> "Sign in") is not, and a genuine rename is the usual reason a
    step stops working. When nothing matches, the scenario comes back
    unchanged and the retry fails the same way -- which reads as the fixer
    having tried and failed rather than having found nothing to try.

    The annotation is written as ``(auto-fixed attempt N)`` and only once.
    It used to be ``# Fixed attempt N``, written with ``+=``, which was wrong
    in three ways of descending severity. It was appended again on every
    attempt, so a step that kept failing accumulated the note (live defect,
    reachable with ``--max-attempts 3``). The ``#`` reads as a YAML comment
    while in fact being part of the ``description`` value, so the annotation
    shows up in reports as if it were part of what the step does. And ``+=``
    assumes the key exists: ``description`` is required by
    :class:`~aat.core.models.StepConfig` and every step :func:`_generate_scenario`
    builds does set it, so nothing in devqa's own path can trip this -- but the
    function takes raw YAML, so a hand-edited or otherwise-generated file would
    have raised ``KeyError`` on the one branch where the fixer had found
    something, after the user had already approved the run.
    """
    import yaml

    try:
        scenario = yaml.safe_load(yaml_text)
    except Exception:
        return yaml_text

    failed_step = fail_info.get("step", 0)
    elements = scan_data.get("elements", [])

    if not scenario or "steps" not in scenario:
        return yaml_text

    for step in scenario["steps"]:
        if step.get("step") != failed_step:
            continue

        target = step.get("target", {})
        text = target.get("text", "")
        if not text:
            continue

        # Try to find updated element in fresh scan
        matches = _find_matching_elements(text, elements)
        if matches:
            best = matches[0]
            target["text"] = best["label"]
            if best.get("selector") and best["source"] == "dom":
                target["selector"] = best["selector"]
            # Idempotent, and tolerant of a missing key -- see the docstring.
            note = f"(auto-fixed attempt {attempt})"
            previous = step.get("description") or ""
            step["description"] = previous if note in previous else f"{previous} {note}".strip()
        break

    return yaml.safe_dump(
        scenario,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )


def _read_last_failure(data_dir: Path) -> dict[str, Any]:
    """Read last failure info from skill_attempts or last_run."""
    try:
        last_run = data_dir / "last_run.json"
        if last_run.exists():
            data = json.loads(last_run.read_text("utf-8"))
            results = data.get("results", [])
            for r in results:
                if r.get("status") == "failed":
                    return {
                        "step": int(r.get("step", 0)),
                        "error": r.get("error", ""),
                        "action": r.get("action", ""),
                    }
    except Exception:
        pass
    return {}


# -- Helpers ------------------------------------------------------------------


def _run_aat(args: list[str], env: dict[str, str] | None = None) -> int:
    """Run aat CLI command as subprocess.

    Args:
        args: CLI arguments for aat (e.g. ["run", "--skill-mode", "scenario.yaml"]).
        env: Optional environment variables to pass. Used internally to set
             _AAT_DEVQA_APPROVED=1 after user approves in devqa prompt.
    """
    import shutil

    aat_bin = shutil.which("aat")
    cmd = [aat_bin, *args] if aat_bin else [sys.executable, "-m", "aat", *args]
    result = subprocess.run(cmd, capture_output=False, env=env)
    return result.returncode


def _wait_for_approval(seconds: int) -> bool:
    """Wait N seconds, return False if user types 'n'."""
    import select

    try:
        for _remaining in range(seconds, 0, -1):
            # Check stdin for 'n'
            if select.select([sys.stdin], [], [], 1.0)[0]:
                line = sys.stdin.readline().strip().lower()
                if line == "n":
                    return False
        return True
    except Exception:
        # Non-interactive (CI, piped) — auto-proceed
        import time as _time

        _time.sleep(min(seconds, 3))
        return True


def _print_devqa_verdict(
    *,
    passed: bool,
    attempts: int,
    scenario_edits: int,
    data_dir: Path,
) -> None:
    """Close with the same two registers ``aat loop`` closes with.

    ``devqa`` never edits source. Everything it rewrites is the scenario's
    own locators, each rewrite shown as a diff and approved at the terminal,
    so the plain register says that in those words rather than borrowing the
    language of a code fix.
    """
    from aat.core.verdict import EDITED_SCENARIO, Verdict, render

    fail = _read_last_failure(data_dir)
    failing: tuple[str, ...] = ()
    if fail and not passed:
        error = str(fail.get("error", "")).strip() or "no error message recorded"
        failing = (f"Step {fail.get('step')} ({fail.get('action', '?')}) — {error}",)

    verdict = Verdict(
        passed=passed,
        attempts=attempts,
        disposition=EDITED_SCENARIO,
        scenario_edits=scenario_edits,
        failing_steps=failing,
        report_hint=str(data_dir / "last_run.json"),
    )
    typer.echo()
    for line in render(verdict):
        typer.echo(f"[AWT] {line}" if line else "[AWT]")


def _report_failure(data_dir: Path) -> None:
    """Report failure summary."""
    fail = _read_last_failure(data_dir)
    if fail:
        typer.echo(
            f"[AWT] Last failure: Step {fail.get('step')} — {fail.get('error', 'unknown')[:100]}"
        )
    typer.echo("[AWT] Suggestions:")
    typer.echo("  1. Check .aat/screenshots/ for failure screenshots")
    typer.echo("  2. Run: aat scan --url <url> to re-scan elements")
    typer.echo("  3. Check source code for the failing component")
