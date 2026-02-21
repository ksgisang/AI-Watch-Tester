"""Shared scenario utilities — used by scan.py, tests.py, executor.py.

Extracted to avoid cross-imports between routers and keep
common logic (compression, validation, form-submit fix) in one place.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_AI_MODELS: dict[str, str] = {
    "claude": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
    "ollama": "codellama:7b",
}

FORM_SUBMIT_RULE = """\
**FORM SUBMIT BUTTON — CRITICAL**:
   After filling form fields (find_and_type steps), the NEXT click MUST be the
   form's own submit button — look for SUBMIT[form] in the PAGE/MODAL FIELDS.
   - SUBMIT[form] = button INSIDE the form → USE THIS for form submission
   - SUBMIT[nav] = navigation menu link → NEVER use this after form input
   - SUBMIT[body] = button outside form/nav → only use if no [form] button exists
   Example: PAGE FIELDS shows SUBMIT[form](button.btn, '다음') and \
SUBMIT[nav](a.nav, '가입')
   → After filling email/password, click '다음' (SUBMIT[form]), \
NOT '가입' (SUBMIT[nav])
   - The nav link '가입' is for PAGE NAVIGATION, NOT for form submission"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_json(text: str | None) -> Any:
    """Safely parse JSON text."""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Observation compression
# ---------------------------------------------------------------------------

def compress_observations_for_ai(
    observations: list[dict],
    max_tokens: int = 15000,
) -> str:
    """Compress observation data into 1-line summaries within token budget."""
    if not observations:
        return "No observations collected."

    # 1) Deduplicate by selector+text
    seen: set[str] = set()
    unique_obs: list[dict] = []
    for obs in observations:
        elem = obs.get("element", {})
        key = f"{elem.get('selector', '')}|{elem.get('text', '').lower()}"
        if key not in seen:
            seen.add(key)
            unique_obs.append(obs)

    # 2) Priority sort (forms/modal > navigation > static)
    def _priority(obs: dict) -> int:
        change = obs.get("observed_change", {})
        ct = change.get("type", "")
        if change.get("modal_form_fields") or change.get("navigated_page_fields"):
            return 0
        if ct == "modal_opened":
            return 1
        if ct == "page_navigation":
            return 2
        if ct == "content_expanded":
            return 3
        if ct in ("anchor_scroll", "section_change"):
            return 4
        return 5
    unique_obs.sort(key=_priority)

    # 3) Build 1-line summaries
    lines: list[str] = []
    form_details: list[str] = []

    for obs in unique_obs:
        elem = obs.get("element", {})
        change = obs.get("observed_change", {})
        ct = change.get("type", "no_change")
        if ct == "no_change":
            continue

        sel = elem.get("selector", "?")
        txt = elem.get("text", "?")
        after_url = obs.get("after", {}).get("url", "")
        new_text = change.get("new_text", [])

        summary_parts = [f"'{txt}' ({sel})"]
        if ct == "page_navigation":
            summary_parts.append(f"→ navigate {after_url}")
        elif ct == "modal_opened":
            summary_parts.append("→ modal opened")
        elif ct == "content_expanded":
            summary_parts.append("→ content expanded")
        elif ct == "anchor_scroll":
            summary_parts.append("→ section scroll")
        elif ct == "file_download":
            summary_parts.append(f"→ file download {after_url}")
        else:
            summary_parts.append(f"→ {ct}")

        if new_text:
            texts_preview = json.dumps(new_text[:5], ensure_ascii=False)
            summary_parts.append(f"assert: {texts_preview}")

        lines.append(" | ".join(summary_parts))

        # Form fields in separate section (critical for test generation)
        modal_fields = change.get("modal_form_fields", [])
        nav_fields = change.get("navigated_page_fields", [])
        for fields, label in [(modal_fields, "MODAL"), (nav_fields, "PAGE")]:
            if fields:
                field_strs = []
                for f in fields:
                    ctx = f.get("context", "")
                    ctx_tag = f"[{ctx}]" if ctx else ""
                    if f.get("type") == "submit_button":
                        field_strs.append(
                            f"SUBMIT{ctx_tag}({f.get('selector', '?')}, "
                            f"{f.get('label', '')!r})"
                        )
                    else:
                        field_strs.append(
                            f"{f.get('type', 'text')}{ctx_tag}("
                            f"{f.get('selector', '?')}, "
                            f"ph={f.get('placeholder', '')!r})"
                        )
                form_details.append(
                    f"  {label} FIELDS after '{txt}': {', '.join(field_strs)}"
                )

    # 4) Token budget check (~1 token per 3 chars, conservative)
    def _build_result() -> str:
        parts = ["## Observations (compressed)"]
        parts.extend(lines)
        if form_details:
            parts.append("\n## Form Fields (CRITICAL — use EXACT selectors)")
            parts.extend(form_details)
        return "\n".join(parts)

    result = _build_result()
    estimated_tokens = len(result) // 3

    while estimated_tokens > max_tokens and lines:
        lines.pop()
        result = _build_result()
        estimated_tokens = len(result) // 3

    return result


# ---------------------------------------------------------------------------
# Scenario validation
# ---------------------------------------------------------------------------

def _find_closest(
    target: str, candidates: set[str],
) -> str | None:
    """Find the most similar string from candidates."""
    if not candidates:
        return None
    best = None
    best_score = 0
    for c in candidates:
        common = sum(1 for ch in target if ch in c)
        score = common / max(len(target), len(c), 1)
        if score > best_score:
            best_score = score
            best = c
    return best if best_score > 0.3 else None


def validate_scenarios(
    scenarios: list,
    observations: list[dict],
    page_data: list[dict] | None = None,
) -> list[dict]:
    """Validate scenario step targets against observation/crawl data.

    Returns list of validation results per step:
    [{"scenario_idx": 0, "step": 1, "status": "verified"|"unverified",
      "target_text": "...", "closest_match": "..."|null}]
    """
    observed_texts: set[str] = set()
    observed_selectors: set[str] = set()
    observed_urls: set[str] = set()
    form_fields: set[str] = set()

    for obs in observations:
        elem = obs.get("element", {})
        txt = (elem.get("text") or "").strip().lower()
        sel = (elem.get("selector") or "").strip().lower()
        if txt:
            observed_texts.add(txt)
        if sel:
            observed_selectors.add(sel)
        for nt in obs.get("observed_change", {}).get("new_text", []):
            nt_lower = nt.strip().lower()
            if nt_lower:
                observed_texts.add(nt_lower)
        for key in ("before", "after"):
            u = obs.get(key, {}).get("url", "")
            if u:
                observed_urls.add(u.lower())

    for pdata in (page_data or []):
        for nav in pdata.get("nav_menus", []):
            for item in nav.get("items", []):
                txt = (item.get("text") or "").strip().lower()
                if txt:
                    observed_texts.add(txt)
        for btn in pdata.get("buttons", []):
            txt = (btn.get("text") or "").strip().lower()
            if txt:
                observed_texts.add(txt)
        for link in pdata.get("links", []):
            txt = (link.get("text") or "").strip().lower()
            href = (link.get("href") or "").lower()
            if txt:
                observed_texts.add(txt)
            if href:
                observed_urls.add(href)
        for form in pdata.get("forms", []):
            for field in form.get("fields", []):
                for fkey in ("name", "placeholder", "label", "aria_label"):
                    val = (field.get(fkey) or "").strip().lower()
                    if val:
                        form_fields.add(val)
                        observed_texts.add(val)
                sel = (field.get("selector") or "").strip().lower()
                if sel:
                    observed_selectors.add(sel)

    results: list[dict] = []

    for si, scenario in enumerate(scenarios):
        steps = []
        if hasattr(scenario, "steps"):
            steps = scenario.steps
        elif isinstance(scenario, dict):
            steps = scenario.get("steps", [])

        for step in steps:
            if hasattr(step, "target"):
                target_obj = step.target
                action = (
                    step.action.value
                    if hasattr(step.action, "value")
                    else str(step.action)
                )
                step_num = step.step
                target_text = (
                    target_obj.text if target_obj else None
                )
                value = step.value
            else:
                target_obj = step.get("target")
                action = str(step.get("action", ""))
                step_num = step.get("step", 0)
                target_text = (
                    target_obj.get("text") if target_obj else None
                )
                value = step.get("value")

            if action in ("navigate", "wait", "screenshot"):
                if action == "navigate" and value:
                    results.append({
                        "scenario_idx": si,
                        "step": step_num,
                        "status": "verified",
                        "target_text": value,
                    })
                continue

            if not target_text:
                continue

            tt_lower = target_text.strip().lower()

            if tt_lower in observed_texts:
                results.append({
                    "scenario_idx": si,
                    "step": step_num,
                    "status": "verified",
                    "target_text": target_text,
                })
                continue

            partial = None
            for ot in observed_texts:
                if tt_lower in ot or ot in tt_lower:
                    partial = ot
                    break

            if partial:
                results.append({
                    "scenario_idx": si,
                    "step": step_num,
                    "status": "verified",
                    "target_text": target_text,
                    "closest_match": partial,
                })
                continue

            if tt_lower in form_fields:
                results.append({
                    "scenario_idx": si,
                    "step": step_num,
                    "status": "verified",
                    "target_text": target_text,
                })
                continue

            closest = _find_closest(tt_lower, observed_texts)
            results.append({
                "scenario_idx": si,
                "step": step_num,
                "status": "unverified",
                "target_text": target_text,
                "closest_match": closest,
            })

    return results


async def validate_and_retry(
    scenarios: list,
    observations: list[dict],
    page_data: list[dict] | None,
    adapter: Any,
    prompt_context: str,
) -> tuple[list, list[dict]]:
    """Validate scenarios and retry once if too many unverified.

    Returns (possibly_fixed_scenarios, validation_results).
    """
    results = validate_scenarios(scenarios, observations, page_data)
    unverified = [r for r in results if r["status"] == "unverified"]
    total_validated = len(results)

    if (
        total_validated > 0
        and len(unverified) / total_validated > 0.3
        and observations
    ):
        logger.info(
            "Validation: %d/%d unverified, retrying",
            len(unverified), total_validated,
        )
        retry_prompt = (
            f"{prompt_context}\n\n"
            "## VALIDATION FAILED — FIX REQUIRED\n"
            "The following targets were NOT found in the "
            "observation data:\n"
        )
        for uv in unverified:
            closest = uv.get("closest_match")
            hint = f" (closest: \"{closest}\")" if closest else ""
            retry_prompt += (
                f"- Step {uv['step']}: "
                f"\"{uv['target_text']}\"{hint}\n"
            )
        retry_prompt += (
            "\nFix these targets using ONLY elements from "
            "the observation data. Return the complete "
            "corrected scenario JSON array."
        )

        try:
            fixed = await adapter.generate_scenarios(retry_prompt)
            if fixed:
                scenarios = fixed
                results = validate_scenarios(
                    scenarios, observations, page_data,
                )
        except Exception as exc:
            logger.warning("Validation retry failed: %s", exc)

    return scenarios, results


# ---------------------------------------------------------------------------
# Form-submit post-generation fix
# ---------------------------------------------------------------------------

def fix_form_submit_steps(
    scenarios: list,
    observations: list[dict],
) -> list:
    """Fix scenarios where form input is followed by a nav click.

    After find_and_type steps, the next click should be a form submit
    button (context=form), not a navigation link (context=nav).
    """
    form_submits: dict[str, dict] = {}
    all_submit_buttons: list[dict] = []
    for obs in observations:
        change = obs.get("observed_change", {})
        nav_fields = change.get("navigated_page_fields", [])
        if not nav_fields:
            continue
        elem_text = (obs.get("element", {}).get("text") or "").strip()
        for f in nav_fields:
            if f.get("type") == "submit_button":
                all_submit_buttons.append({
                    "obs_elem": elem_text,
                    "label": f.get("label"),
                    "selector": f.get("selector"),
                    "context": f.get("context"),
                })
                if f.get("context") == "form" and elem_text not in form_submits:
                    form_submits[elem_text] = {
                        "selector": f.get("selector", ""),
                        "label": f.get("label", ""),
                    }

    logger.debug(
        "=== FORM-SUBMIT FIX: all submit buttons found ===\n%s",
        json.dumps(all_submit_buttons, ensure_ascii=False, indent=2),
    )
    logger.debug(
        "=== FORM-SUBMIT FIX: form_submits (context=form) ===\n%s",
        json.dumps(form_submits, ensure_ascii=False, indent=2),
    )

    if not form_submits:
        logger.debug("=== FIX APPLIED: NO (no form submit buttons found) ===")
        return scenarios

    nav_labels: set[str] = set()
    for obs in observations:
        change = obs.get("observed_change", {})
        for f in change.get("navigated_page_fields", []):
            if f.get("type") == "submit_button" and f.get("context") == "nav":
                lbl = (f.get("label") or "").strip().lower()
                if lbl:
                    nav_labels.add(lbl)

    for obs in observations:
        elem = obs.get("element", {})
        elem_type = elem.get("type", "")
        if elem_type == "nav_item":
            t = (elem.get("text") or "").strip().lower()
            if t:
                nav_labels.add(t)

    logger.debug(
        "=== FORM-SUBMIT FIX: nav_labels (will be replaced) === %s",
        nav_labels,
    )

    for scenario in scenarios:
        steps = []
        if hasattr(scenario, "steps"):
            steps = scenario.steps
        elif isinstance(scenario, dict):
            steps = scenario.get("steps", [])

        last_was_input = False
        nav_click_text = ""

        for step in steps:
            action = (
                step.action.value
                if hasattr(step, "action") and hasattr(step.action, "value")
                else str(
                    getattr(step, "action", "")
                    or (step.get("action", "") if isinstance(step, dict) else "")
                )
            )
            target = (
                step.target
                if hasattr(step, "target")
                else (step.get("target") if isinstance(step, dict) else None)
            )

            if action == "find_and_click" and not last_was_input:
                target_text = ""
                if target:
                    target_text = (
                        target.text
                        if hasattr(target, "text")
                        else target.get("text", "")
                    ) or ""
                if target_text in form_submits:
                    nav_click_text = target_text

            if action == "find_and_type":
                last_was_input = True
                continue

            if action == "find_and_click" and last_was_input and target:
                target_text = (
                    target.text
                    if hasattr(target, "text")
                    else target.get("text", "")
                ) or ""
                tt_lower = target_text.strip().lower()

                is_nav_click = tt_lower in nav_labels

                form_btn = form_submits.get(nav_click_text) or (
                    next(iter(form_submits.values())) if form_submits else None
                )

                logger.debug(
                    "=== FORM-SUBMIT CHECK: after input, click='%s', "
                    "is_nav=%s, nav_click_text='%s', form_btn=%s ===",
                    target_text, is_nav_click, nav_click_text, form_btn,
                )

                if is_nav_click and form_btn:
                    btn_label = form_btn["label"]
                    btn_selector = form_btn["selector"]

                    if tt_lower != btn_label.strip().lower():
                        logger.warning(
                            "FORM-SUBMIT FIX: Replacing nav click '%s' "
                            "with form submit '%s' (%s)",
                            target_text, btn_label, btn_selector,
                        )
                        if hasattr(target, "text"):
                            target.text = btn_label
                            if hasattr(target, "selector") and btn_selector:
                                target.selector = btn_selector
                        elif isinstance(target, dict):
                            target["text"] = btn_label
                            if btn_selector:
                                target["selector"] = btn_selector

            last_was_input = False

    return scenarios


# ---------------------------------------------------------------------------
# Fix generic/wrong field targets → observed field data
# ---------------------------------------------------------------------------

# Mapping from generic English keywords to field type for matching
_FIELD_TYPE_HINTS: dict[str, list[str]] = {
    "email": ["email", "mail", "이메일", "e-mail"],
    "password": [
        "password", "비밀번호", "패스워드", "pw", "passwd",
    ],
    "confirm_password": [
        "confirm password", "password confirm", "비밀번호 확인",
        "비밀번호확인", "패스워드 확인", "re-enter", "retype",
        "confirm", "확인",
    ],
    "name": [
        "name", "이름", "닉네임", "nickname", "username", "아이디",
        "full name", "fullname",
    ],
    "phone": [
        "phone", "전화", "휴대폰", "핸드폰", "tel", "연락처", "mobile",
    ],
}


def _classify_field_hint(text: str) -> str:
    """Classify a field target text into a type hint (email, password, etc.)."""
    t = text.strip().lower()
    # confirm_password must be checked BEFORE password
    for hint_type in ("confirm_password", "email", "password", "name", "phone"):
        for keyword in _FIELD_TYPE_HINTS[hint_type]:
            if keyword in t:
                return hint_type
    return "unknown"


def _classify_observed_field(field: dict) -> str:
    """Classify an observed form field by its attributes."""
    f_type = (field.get("type") or "").lower()
    selector = (field.get("selector") or "").lower()
    placeholder = (field.get("placeholder") or "").lower()
    label = (field.get("label") or "").lower()
    hint = f"{f_type} {selector} {placeholder} {label}"

    # Check confirm password first (label/placeholder usually has "확인"/"confirm")
    for kw in _FIELD_TYPE_HINTS["confirm_password"]:
        if kw in hint:
            return "confirm_password"

    if f_type == "email" or any(kw in hint for kw in _FIELD_TYPE_HINTS["email"]):
        return "email"
    if f_type == "password" or any(
        kw in hint for kw in _FIELD_TYPE_HINTS["password"]
    ):
        return "password"
    if f_type == "tel" or any(kw in hint for kw in _FIELD_TYPE_HINTS["phone"]):
        return "phone"
    if any(kw in hint for kw in _FIELD_TYPE_HINTS["name"]):
        return "name"

    return "unknown"


def fix_field_targets(
    scenarios: list,
    observations: list[dict],
) -> list:
    """Fix AI-generated find_and_type targets to use actual observed field data.

    When the AI generates generic targets like {text: "Email"} instead of
    actual observed selectors/placeholders, this maps them to real field data.
    Critical for:
    - Ensuring correct CSS selectors are used
    - Distinguishing password vs confirm password fields
    - Using Korean placeholders instead of English generic names
    """
    # 1) Collect all form fields from observations
    observed_fields: list[dict] = []
    for obs in observations:
        change = obs.get("observed_change", {})
        for fields_key in ("navigated_page_fields", "modal_form_fields"):
            for f in change.get(fields_key, []):
                if f.get("type") == "submit_button":
                    continue
                observed_fields.append(f)

    if not observed_fields:
        return scenarios

    # 2) Classify each observed field
    classified: dict[str, list[dict]] = {}
    for f in observed_fields:
        ftype = _classify_observed_field(f)
        classified.setdefault(ftype, []).append(f)

    # Track password field count for confirm password disambiguation
    password_fields = classified.get("password", [])
    confirm_fields = classified.get("confirm_password", [])

    # If we have 2+ password-type fields but none classified as confirm,
    # treat the second one as confirm password
    if len(password_fields) >= 2 and not confirm_fields:
        confirm_fields = [password_fields.pop()]
        classified["confirm_password"] = confirm_fields
        classified["password"] = password_fields

    logger.debug(
        "FIELD-TARGET FIX: observed fields classified: %s",
        {k: len(v) for k, v in classified.items()},
    )

    # 3) Fix each find_and_type step
    for scenario in scenarios:
        steps: list = []
        if hasattr(scenario, "steps"):
            steps = scenario.steps
        elif isinstance(scenario, dict):
            steps = scenario.get("steps", [])

        for step in steps:
            action = ""
            if hasattr(step, "action") and hasattr(step.action, "value"):
                action = step.action.value
            elif hasattr(step, "action"):
                action = str(step.action)
            elif isinstance(step, dict):
                action = step.get("action", "")

            if action != "find_and_type":
                continue

            # Get target
            target = None
            if hasattr(step, "target"):
                target = step.target
            elif isinstance(step, dict):
                target = step.get("target")

            if not target:
                continue

            # Get target text
            target_text = ""
            if hasattr(target, "text"):
                target_text = target.text or ""
            elif isinstance(target, dict):
                target_text = target.get("text", "")

            target_selector = ""
            if hasattr(target, "selector"):
                target_selector = target.selector or ""
            elif isinstance(target, dict):
                target_selector = target.get("selector", "")

            # Already has a selector → likely correct from observation data
            if target_selector:
                continue

            # Classify what the AI intended
            intended_type = _classify_field_hint(target_text)
            if intended_type == "unknown":
                continue

            # Find matching observed field
            matches = classified.get(intended_type, [])
            if not matches:
                continue

            observed = matches[0]
            new_selector = observed.get("selector", "")
            new_text = (
                observed.get("placeholder")
                or observed.get("label")
                or target_text
            )

            if new_selector or new_text != target_text:
                logger.warning(
                    "FIELD-TARGET FIX: '%s' → selector='%s', text='%s' "
                    "(type=%s)",
                    target_text, new_selector, new_text, intended_type,
                )
                if hasattr(target, "text"):
                    target.text = new_text
                    if hasattr(target, "selector") and new_selector:
                        target.selector = new_selector
                elif isinstance(target, dict):
                    target["text"] = new_text
                    if new_selector:
                        target["selector"] = new_selector

    return scenarios


def ensure_post_submit_assert(scenarios: list) -> list:
    """Ensure every form scenario has wait+assert after the submit click.

    If find_and_type steps are followed by a submit click with no subsequent
    assert, insert a wait(1500) step so the post-submit page state is captured
    in screenshots. Logs a warning when this safety net triggers.
    """
    for scenario in scenarios:
        steps: list = []
        if hasattr(scenario, "steps"):
            steps = scenario.steps
        elif isinstance(scenario, dict):
            steps = scenario.get("steps", [])

        if not steps:
            continue

        def _get_action(step: object) -> str:
            if hasattr(step, "action") and hasattr(step.action, "value"):
                return step.action.value
            if hasattr(step, "action"):
                return str(step.action)
            if isinstance(step, dict):
                return step.get("action", "")
            return ""

        # Find the last submit click after form input
        has_type = False
        last_submit_idx = -1
        for i, step in enumerate(steps):
            action = _get_action(step)
            if action == "find_and_type":
                has_type = True
            elif action == "find_and_click" and has_type:
                last_submit_idx = i

        if last_submit_idx < 0:
            continue

        # Check if there's already an assert or wait after the submit
        has_post_submit = False
        for step in steps[last_submit_idx + 1:]:
            action = _get_action(step)
            if action in ("assert", "wait"):
                has_post_submit = True
                break

        if has_post_submit:
            continue

        # Safety net: insert wait step after submit for screenshot capture
        sc_name = ""
        if hasattr(scenario, "name"):
            sc_name = scenario.name
        elif isinstance(scenario, dict):
            sc_name = scenario.get("name", "")

        logger.warning(
            "POST-SUBMIT SAFETY: No assert after form submit in '%s' "
            "— inserting wait(1500) for screenshot capture",
            sc_name,
        )

        next_step_num = len(steps) + 1
        wait_step = {
            "step": next_step_num,
            "action": "wait",
            "value": "1500",
            "description": "Wait for page transition after form submit",
        }
        steps.append(wait_step)

    return scenarios
