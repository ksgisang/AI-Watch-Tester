#!/usr/bin/env python3
"""Generate the scenario schema reference for the AWT agent skill.

The skill's schema reference is what an AI reads before writing a scenario, so
a field missing from it is a field that will never be used. Keeping it by hand
failed: it described 18 actions while the code had 26, and omitted `critical`,
`message` and `on_fail` entirely.

Everything that can drift is taken from the models:

* field names, types, defaults and requiredness — from the Pydantic models
* enum members — from the enums themselves
* "requires target / requires value" — measured by constructing a StepConfig
  without that field and seeing whether validation rejects it

Only prose that has no home in the code (what an action is for, what its value
looks like) lives in the tables below, and generation fails if a table and an
enum disagree.

Usage:
    python scripts/gen_scenario_schema.py           # write the file
    python scripts/gen_scenario_schema.py --check   # fail if it is out of date
"""

from __future__ import annotations

import argparse
import sys
import typing
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo

from aat.core.models import (
    ActionType,
    AssertType,
    ExpectedResult,
    FindMethod,
    MatchMethod,
    Scenario,
    ScreenRegion,
    StepConfig,
    TargetSpec,
    TeardownStep,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_ROOT = REPO_ROOT / "awt-skill" / "awt"
OUTPUT = SKILL_ROOT / "references" / "scenario-schema.md"
SKILL_DOC = SKILL_ROOT / "SKILL.md"
GENERATOR = "scripts/gen_scenario_schema.py"

# SKILL.md is mostly hand-written prose, so only its action table is generated,
# between these markers.
BLOCK_BEGIN = "<!-- BEGIN GENERATED: actions -->"
BLOCK_END = "<!-- END GENERATED: actions -->"


# ─── Prose that has no home in the code ──────────────────────


@dataclass(frozen=True)
class ActionDoc:
    """What an action is for, and what it needs in order to run.

    ``target`` and ``value`` describe what the action needs at *runtime*, which
    is not the same as what the validators reject — only some requirements are
    enforced by `aat validate`. The generator compares the two and marks the
    difference, so a step that would blow up mid-run is visible up front.
    """

    group: str
    summary: str
    value_format: str = "—"
    target: str = "unused"  # required | optional | unused
    value: str = "unused"


_ACTIONS: dict[ActionType, ActionDoc] = {
    ActionType.NAVIGATE: ActionDoc(
        "Navigation", "Open a URL", "URL (supports `{{url}}`)", value="required"
    ),
    ActionType.GO_BACK: ActionDoc("Navigation", "Go back one entry in history"),
    ActionType.REFRESH: ActionDoc("Navigation", "Reload the current page"),
    ActionType.FIND_AND_CLICK: ActionDoc(
        "Find + mouse",
        "Click the element found by selector, text or image",
        target="required",
    ),
    ActionType.FIND_AND_DOUBLE_CLICK: ActionDoc(
        "Find + mouse", "Double-click the element", target="required"
    ),
    ActionType.FIND_AND_RIGHT_CLICK: ActionDoc(
        "Find + mouse", "Right-click the element", target="required"
    ),
    ActionType.FIND_AND_TYPE: ActionDoc(
        "Find + keyboard",
        "Focus the element, then type into it",
        "Text to type",
        target="required",
        value="required",
    ),
    ActionType.FIND_AND_CLEAR: ActionDoc(
        "Find + keyboard", "Clear the element's content", target="required"
    ),
    ActionType.CLICK_AT: ActionDoc(
        "Direct", "Click fixed coordinates", "`x,y`", value="required"
    ),
    ActionType.TYPE_TEXT: ActionDoc(
        "Direct", "Type into whatever has focus", "Text to type", value="required"
    ),
    ActionType.PRESS_KEY: ActionDoc(
        "Direct", "Press a single key", "`Enter`, `Tab`, `Escape`, ...", value="required"
    ),
    ActionType.KEY_COMBO: ActionDoc(
        "Direct", "Press a key combination", "`Ctrl+A`, `Cmd+C`", value="required"
    ),
    ActionType.ASSERT: ActionDoc(
        "Assert", "Check `assert_type` against `expected`", "Unused — see `expected`"
    ),
    ActionType.ASSERT_TEXT: ActionDoc(
        "Assert",
        "Check that text is on screen (DOM first, OCR fallback)",
        "Text to look for, if `target.text` is not used",
        target="required",
        value="optional",
    ),
    ActionType.ASSERT_SCREEN_CHANGED: ActionDoc(
        "Assert", "Check the screen changed by at least `threshold`"
    ),
    ActionType.ASSERT_URL: ActionDoc(
        "Assert",
        "Check the current URL contains a substring",
        "Substring, e.g. `/dashboard`",
        value="required",
    ),
    ActionType.SAVE_SESSION: ActionDoc(
        "Session",
        "Save cookies and storage under a name",
        "Session name, if `name` is not used",
        value="optional",
    ),
    ActionType.LOAD_SESSION: ActionDoc(
        "Session",
        "Restore a saved session",
        "Session name, if `name` is not used",
        value="optional",
    ),
    ActionType.UPLOAD_FILE: ActionDoc(
        "Input",
        "Attach a file to a file input; needs `file_path` or `file_paths`",
        "Selector, if `target.selector` is not used",
        target="optional",
        value="optional",
    ),
    ActionType.IF_VISIBLE: ActionDoc(
        "Control flow",
        "Run the `then` sub-steps only if the target is visible",
        target="required",
    ),
    ActionType.INCLUDE: ActionDoc(
        "Control flow",
        "Inline another scenario file",
        "Scenario path, if `scenario` is not used",
        value="optional",
    ),
    ActionType.FIND: ActionDoc(
        "Query",
        "Locate an element without clicking it; pairs with `save_as`",
        target="required",
    ),
    ActionType.GET_TEXT: ActionDoc(
        "Query",
        "Read an element's text into a runtime variable via `save_as`",
        "Selector, if `target.selector` is not used",
        target="optional",
        value="optional",
    ),
    ActionType.WAIT: ActionDoc("Utility", "Wait", "Milliseconds, e.g. `2000`", value="optional"),
    ActionType.SCREENSHOT: ActionDoc("Utility", "Capture the screen"),
    ActionType.SCROLL: ActionDoc(
        "Utility", "Scroll the page", "`x,y,delta` (delta > 0 = down)", value="required"
    ),
}

_GROUP_ORDER = (
    "Navigation",
    "Find + mouse",
    "Find + keyboard",
    "Direct",
    "Assert",
    "Session",
    "Input",
    "Control flow",
    "Query",
    "Utility",
)

_ASSERT_TYPES: dict[AssertType, str] = {
    AssertType.TEXT_VISIBLE: "Text appears anywhere on the page",
    AssertType.TEXT_EQUALS: "Text matches exactly",
    AssertType.IMAGE_VISIBLE: "Image template is found on screen",
    AssertType.URL_CONTAINS: "Current URL contains the substring",
    AssertType.URL_NOT_CONTAINS: "Current URL does not contain the substring",
    AssertType.SCREENSHOT_MATCH: "Screen matches a reference image",
}

_FIND_METHODS: dict[FindMethod, str] = {
    FindMethod.AUTO: "Full chain (default): Semantics → template → OCR → Vision AI",
    FindMethod.SEMANTICS: "Flutter Semantics only (aria-label / role lookup)",
    FindMethod.TEMPLATE: "Template matching only (OpenCV)",
    FindMethod.OCR: "OCR only (Tesseract with CLAHE + sharpening)",
    FindMethod.VISION: "Vision AI only (API call — costs money)",
}

_MATCH_METHODS: dict[MatchMethod, tuple[str, str]] = {
    MatchMethod.LEARNED: ("SQLite lookup", "Matches that already worked once"),
    MatchMethod.SEMANTICS: ("Flutter Semantics", "Flutter CanvasKit apps"),
    MatchMethod.TEMPLATE: ("cv2.matchTemplate", "Exact visual matching"),
    MatchMethod.OCR: ("pytesseract + CLAHE", "Finding elements by their text"),
    MatchMethod.FEATURE: ("ORB keypoints", "Rotation- and scale-invariant matching"),
    MatchMethod.VISION_AI: ("Claude / OpenAI / Gemini Vision", "Canvas text, complex UIs"),
}

_REGIONS: dict[ScreenRegion, str] = {
    ScreenRegion.FULL: "Entire screen (default)",
    ScreenRegion.TOP: "Top 30%",
    ScreenRegion.BOTTOM: "Bottom 30%",
    ScreenRegion.LEFT: "Left 20%",
    ScreenRegion.RIGHT: "Right 80%",
    ScreenRegion.CENTER: "Central 60% x 60%",
    ScreenRegion.MAIN: "Everything except the left 20% (navigation excluded)",
}


def _check_tables_cover_enums() -> None:
    """Fail loudly when an enum grew and its prose table did not."""
    for table, enum in (
        (_ACTIONS, ActionType),
        (_ASSERT_TYPES, AssertType),
        (_FIND_METHODS, FindMethod),
        (_MATCH_METHODS, MatchMethod),
        (_REGIONS, ScreenRegion),
    ):
        missing = [m.value for m in enum if m not in table]
        if missing:
            msg = (
                f"{enum.__name__} members missing from the description table "
                f"in {GENERATOR}: {', '.join(missing)}"
            )
            raise SystemExit(msg)

    ungrouped = sorted({d.group for d in _ACTIONS.values()} - set(_GROUP_ORDER))
    if ungrouped:
        msg = f"Action groups missing from _GROUP_ORDER in {GENERATOR}: {', '.join(ungrouped)}"
        raise SystemExit(msg)


# ─── Reading the models ──────────────────────────────────────


def _type_name(annotation: object) -> str:
    """Render a field annotation the way a scenario author would say it."""
    if annotation is None:
        return "—"
    origin = typing.get_origin(annotation)
    if origin is not None:
        args = typing.get_args(annotation)
        inner = " | ".join(_type_name(a) for a in args)
        if origin is list:
            return f"list[{inner}]"
        if origin is dict:
            key, val = (_type_name(a) for a in args)
            return f"dict[{key}, {val}]"
        return inner  # unions (incl. `X | None`) render as their members
    if annotation is type(None):
        return "null"
    name = getattr(annotation, "__name__", str(annotation))
    return {"str": "string", "bool": "bool", "int": "int", "float": "float"}.get(name, name)


def _yaml_literal(value: object) -> str:
    """Render a default the way it would be written in a scenario file."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '""' if value == "" else value
    if isinstance(value, list | dict):
        return "[]" if isinstance(value, list) else "{}"
    if isinstance(value, ActionType | AssertType | FindMethod | MatchMethod | ScreenRegion):
        return str(value.value)
    return str(value)


def _default_repr(field: FieldInfo) -> str:
    if field.is_required():
        return "—"
    if field.default_factory is not None:
        return f"`{_yaml_literal(field.default_factory())}`"  # type: ignore[call-arg]
    return f"`{_yaml_literal(field.default)}`"


def _cell(text: str) -> str:
    """Escape pipes so union types and prose cannot break the table."""
    return text.replace("|", r"\|")


def _field_rows(model: type[BaseModel]) -> list[str]:
    rows = []
    for name, field in model.model_fields.items():
        required = "Yes" if field.is_required() else "No"
        rows.append(
            f"| `{name}` | {_cell(_type_name(field.annotation))} | {required} "
            f"| {_default_repr(field)} | {_cell(field.description or '')} |"
        )
    return rows


def _table(model: type[BaseModel]) -> str:
    head = "| Field | Type | Required | Default | Description |\n|---|---|---|---|---|"
    return "\n".join([head, *_field_rows(model)])


_PROBE: dict[str, object] = {
    "target": TargetSpec(text="probe"),
    "value": "probe",
    "assert_type": AssertType.TEXT_VISIBLE,
    "name": "probe",
    "scenario": "probe.yaml",
}


def _requires(action: ActionType, field: str) -> bool:
    """Ask the model itself whether this action refuses to validate without `field`.

    Measured rather than declared, so the table cannot claim something the
    validators do not actually enforce.
    """
    kwargs = {k: v for k, v in _PROBE.items() if k != field}
    try:
        StepConfig(step=1, action=action, description="probe", **kwargs)  # type: ignore[arg-type]
    except ValidationError as e:
        return field in str(e)
    return False


_NEED_LABEL = {"required": "required", "optional": "optional", "unused": "—"}


def _requirements_table() -> str:
    """Render what each action needs, and mark where validation does not enforce it.

    Two sources meet here: `_ACTIONS` says what the handler needs in order to run,
    and `_requires()` measures what the validators actually reject. Where they
    disagree the cell is flagged, because that is exactly the case that passes
    `aat validate` and then fails in the middle of a run.
    """
    lines = [
        "| Action | Target | Value | Value format | Purpose |",
        "|---|---|---|---|---|",
    ]
    gaps: list[str] = []
    for action, doc in _ACTIONS.items():
        cells = []
        for field, need in (("target", doc.target), ("value", doc.value)):
            if _requires(action, field):
                cells.append("required")
            elif need == "required":
                cells.append("required ⚠")
                gaps.append(f"`{action.value}`/`{field}`")
            else:
                cells.append(_NEED_LABEL[need])
        lines.append(
            f"| `{action.value}` | {cells[0]} | {cells[1]} | {doc.value_format} | {doc.summary} |"
        )
    if gaps:
        lines += [
            "",
            "⚠ — needed at run time but **not** rejected by `aat validate`: "
            + ", ".join(gaps)
            + ". A step that omits one of these passes validation and then fails "
            "mid-run, so check these by hand when you write a scenario.",
        ]
    return "\n".join(lines)


def _action_groups() -> str:
    blocks = []
    for group in _GROUP_ORDER:
        members = [(a, d) for a, d in _ACTIONS.items() if d.group == group]
        if not members:
            continue
        lines = [f"**{group}**", ""]
        lines += [f"- `{a.value}` — {d.summary}" for a, d in members]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


# ─── Rendering ───────────────────────────────────────────────


def render() -> str:
    _check_tables_cover_enums()

    return f"""# AWT Scenario Schema Reference

<!-- Generated by {GENERATOR} from src/aat/core/models.py. Do not edit by hand:
     run `python {GENERATOR}` after changing the models. -->

## Scenario (root)

{_table(Scenario)}

## StepConfig

{_table(StepConfig)}

## TargetSpec

{_table(TargetSpec)}

At least one of `image`, `text`, `selector` or `icon` is required.

## ExpectedResult

{_table(ExpectedResult)}

## TeardownStep

Cleanup that runs after the scenario finishes, whether it passed or failed. A
failing teardown step is logged and does not change the test result.

{_table(TeardownStep)}

## ActionType ({len(ActionType)} values)

{_action_groups()}

## Action requirements

What each action needs in order to run. Cells marked ⚠ are needed by the handler
but not enforced by the validators, so `aat validate` lets them through.

{_requirements_table()}

## AssertType

| Value | Meaning |
|---|---|
{chr(10).join(f"| `{m.value}` | {d} |" for m, d in _ASSERT_TYPES.items())}

## FindMethod (step-level)

| Value | Meaning |
|---|---|
{chr(10).join(f"| `{m.value}` | {d} |" for m, d in _FIND_METHODS.items())}

With `fallback: true` (the default), a failed specific method falls back to the
full chain. `semantics` is activated automatically on Flutter CanvasKit apps.

## MatchMethod (target-level)

| Value | Algorithm | Best for |
|---|---|---|
{chr(10).join(f"| `{m.value}` | {a} | {b} |" for m, (a, b) in _MATCH_METHODS.items())}

## ScreenRegion

| Value | Area |
|---|---|
{chr(10).join(f"| `{m.value}` | {d} |" for m, d in _REGIONS.items())}
"""


def render_skill_actions() -> str:
    """The one-screen action table SKILL.md shows before the full reference."""
    lines = [
        BLOCK_BEGIN,
        "",
        f"### Actions ({len(ActionType)} types)",
        "",
        "| Category | Actions |",
        "|----------|---------|",
    ]
    for group in _GROUP_ORDER:
        members = [a for a, d in _ACTIONS.items() if d.group == group]
        if not members:
            continue
        lines.append(f"| {group} | {', '.join(f'`{a.value}`' for a in members)} |")
    lines += [
        "",
        "See `references/scenario-schema.md` for what each action needs.",
        "",
        BLOCK_END,
    ]
    return "\n".join(lines)


def _splice(path: Path, block: str) -> str:
    """Return `path`'s text with the generated block swapped in."""
    text = path.read_text()
    start = text.find(BLOCK_BEGIN)
    end = text.find(BLOCK_END)
    if start == -1 or end == -1:
        msg = (
            f"{path.relative_to(REPO_ROOT)} has no {BLOCK_BEGIN} / {BLOCK_END} markers; "
            "the generated action table has nowhere to go"
        )
        raise SystemExit(msg)
    return text[:start] + block + text[end + len(BLOCK_END) :]


def targets() -> list[tuple[Path, str]] | None:
    """Every (file, wanted content) pair, or None if the skill is not checked out."""
    if not SKILL_ROOT.is_dir():
        return None
    return [(OUTPUT, render()), (SKILL_DOC, _splice(SKILL_DOC, render_skill_actions()))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the files on disk differ from what would be generated",
    )
    args = parser.parse_args()

    wanted_files = targets()
    if wanted_files is None:
        print(
            "[SKIP] awt-skill is not checked out "
            "(git submodule update --init awt-skill to get it)"
        )
        return 0

    stale = []
    for path, wanted in wanted_files:
        rel = path.relative_to(REPO_ROOT)
        if args.check:
            if not path.exists() or path.read_text() != wanted:
                stale.append(str(rel))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(wanted)
        print(f"Wrote {rel}")

    if args.check:
        if stale:
            print(
                f"[FAIL] out of date: {', '.join(stale)}\n       Run: python {GENERATOR}"
            )
            return 1
        print("[PASS] the skill docs match the models")
    return 0


if __name__ == "__main__":
    sys.exit(main())
