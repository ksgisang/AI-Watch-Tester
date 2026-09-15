"""AAT data models — Pydantic v2.

This module is a leaf: no internal project imports.
All Enum and Model definitions live here.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ============================================================
# Enums
# ============================================================


class ActionType(StrEnum):
    """Test step action type."""

    # Navigation
    NAVIGATE = "navigate"
    GO_BACK = "go_back"
    REFRESH = "refresh"
    # Image + Mouse
    FIND_AND_CLICK = "find_and_click"
    FIND_AND_DOUBLE_CLICK = "find_and_double_click"
    FIND_AND_RIGHT_CLICK = "find_and_right_click"
    # Image + Keyboard
    FIND_AND_TYPE = "find_and_type"
    FIND_AND_CLEAR = "find_and_clear"
    # Direct (coordinate / value)
    CLICK_AT = "click_at"
    TYPE_TEXT = "type_text"
    PRESS_KEY = "press_key"
    KEY_COMBO = "key_combo"
    # Assert
    ASSERT = "assert"
    ASSERT_TEXT = "assert_text"
    ASSERT_SCREEN_CHANGED = "assert_screen_changed"
    ASSERT_URL = "assert_url"
    # Session
    SAVE_SESSION = "save_session"
    LOAD_SESSION = "load_session"
    # File
    UPLOAD_FILE = "upload_file"
    # Conditional
    IF_VISIBLE = "if_visible"
    # Subroutine
    INCLUDE = "include"
    # Find / Extract
    FIND = "find"
    GET_TEXT = "get_text"
    # Utility
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    SCROLL = "scroll"


class ScreenRegion(StrEnum):
    """Screen region for restricting search/assert area."""

    FULL = "full"
    TOP = "top"
    BOTTOM = "bottom"
    LEFT = "left"
    RIGHT = "right"
    CENTER = "center"
    MAIN = "main"


class LabelPosition(StrEnum):
    """Icon hint label position."""

    ABOVE = "above"
    BELOW = "below"
    LEFT = "left"
    RIGHT = "right"
    INSIDE = "inside"


class AssertType(StrEnum):
    """Assert action sub-type."""

    TEXT_VISIBLE = "text_visible"
    TEXT_EQUALS = "text_equals"
    IMAGE_VISIBLE = "image_visible"
    URL_CONTAINS = "url_contains"
    URL_NOT_CONTAINS = "url_not_contains"
    SCREENSHOT_MATCH = "screenshot_match"


class MatchMethod(StrEnum):
    """Image matching algorithm."""

    LEARNED = "learned"
    SEMANTICS = "semantics"
    TEMPLATE = "template"
    OCR = "ocr"
    FEATURE = "feature"
    VISION_AI = "vision_ai"


class Severity(StrEnum):
    """Failure analysis severity."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class ApprovalMode(StrEnum):
    """DevQA Loop approval mode for AI-generated fixes."""

    MANUAL = "manual"
    BRANCH = "branch"
    AUTO = "auto"


class StepStatus(StrEnum):
    """Individual step execution status."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


# ============================================================
# Config Models
# ============================================================


class AIConfig(BaseModel):
    """AI Adapter configuration."""

    provider: str = Field(default="claude", description="AI provider name")
    api_key: str = Field(default="", description="API key (env: AAT_AI__API_KEY)")
    model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Model ID",
    )
    max_tokens: int = Field(default=4000, ge=100, le=32000)
    temperature: float = Field(default=0.3, ge=0.0, le=1.0)
    step_verify: bool = Field(
        default=False,
        description="Verify each step result with Vision AI",
    )
    step_verify_critical_only: bool = Field(
        default=True,
        description="When step_verify=true, only verify critical steps (saves cost)",
    )


class VisionConfig(BaseModel):
    """Vision AI configuration for 3-tier matching Tier 3.

    Separate from AIConfig so users can use different providers
    for scenario generation (AIConfig) and visual matching (VisionConfig).
    If api_key is empty, Vision AI tier is skipped (free tiers only).
    """

    provider: str = Field(
        default="",
        description="Vision provider: claude, openai, gemini, or empty (disabled)",
    )
    api_key: str = Field(
        default="",
        description="Vision API key (env: AAT_VISION__API_KEY)",
    )
    model: str = Field(
        default="",
        description="Vision model ID (auto-detected from provider if empty)",
    )


class EngineConfig(BaseModel):
    """Test engine configuration."""

    type: str = Field(default="web", description="Engine type: web | desktop")
    browser: str = Field(
        default="chromium",
        description="Browser: chromium | firefox | webkit",
    )
    headless: bool = Field(default=False)
    viewport_width: int = Field(default=1280, ge=320, le=3840)
    viewport_height: int = Field(default=720, ge=240, le=2160)
    timeout_ms: int = Field(default=30000, ge=1000, le=120000)
    slow_mo: int | None = Field(
        default=None,
        ge=0,
        le=5000,
        description=(
            "Slow down actions by ms. None=auto (100 in headed, 0 in headless). "
            "Set 0 to explicitly disable even in headed mode."
        ),
    )
    window_x: int | None = Field(default=None, description="Browser window X position")
    window_y: int | None = Field(default=None, description="Browser window Y position")
    fast_mode: bool = Field(
        default=False,
        description="Strictly use DOM matching; skip Vision/OCR fallbacks for maximum speed",
    )
    speed: str = Field(
        default="normal",
        description=(
            "Execution speed preset. "
            "'fast' for Next.js/React/Vue (regular web), "
            "'normal' for default/mixed apps, "
            "'slow' for Flutter CanvasKit or heavy animations."
        ),
    )
    screenshot_mode: str = Field(
        default="all",
        description=(
            "Screenshot strategy: 'all' (every step, default), "
            "'before-after' (action boundaries only, ~70% fewer files), "
            "'on-failure' (failure steps only, CI/CD optimized)"
        ),
    )
    verbosity: str = Field(
        default="detailed",
        description=(
            "Execution verbosity: 'detailed' (all steps, default) "
            "or 'concise' (skip wait/screenshot/assert_screen_changed)"
        ),
    )


class MatchingConfig(BaseModel):
    """Image matching configuration."""

    confidence_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    multi_scale: bool = Field(default=True)
    scale_range_min: float = Field(default=0.5, ge=0.1, le=1.0)
    scale_range_max: float = Field(default=2.0, ge=1.0, le=4.0)
    grayscale: bool = Field(default=True)
    ocr_languages: list[str] = Field(default=["eng", "kor"])
    chain_order: list[MatchMethod] = Field(
        default=[
            MatchMethod.LEARNED,
            MatchMethod.TEMPLATE,
            MatchMethod.OCR,
            MatchMethod.FEATURE,
            MatchMethod.VISION_AI,
        ],
    )


class HumanizerConfig(BaseModel):
    """Humanizer configuration."""

    enabled: bool = Field(default=True)
    mouse_speed_min: float = Field(default=0.1)
    mouse_speed_max: float = Field(default=0.25)
    typing_delay_min: float = Field(default=0.05)
    typing_delay_max: float = Field(default=0.15)
    bezier_control_points: int = Field(default=3, ge=2, le=5)


class Config(BaseSettings):
    """Project configuration. Merged from YAML + env var + CLI flag."""

    model_config = SettingsConfigDict(
        env_prefix="AAT_",
        env_nested_delimiter="__",
    )

    project_name: str = Field(default="aat-project")
    source_path: str = Field(default=".")
    url: str = Field(default="")
    ai: AIConfig = Field(default_factory=AIConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    engine: EngineConfig = Field(default_factory=EngineConfig)
    matching: MatchingConfig = Field(default_factory=MatchingConfig)
    humanizer: HumanizerConfig = Field(default_factory=HumanizerConfig)
    test_accounts: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description="Test accounts: {name: {email, password, ...}}",
    )
    scenarios_dir: str = Field(default="scenarios")
    reports_dir: str = Field(default="reports")
    assets_dir: str = Field(default="assets")
    data_dir: str = Field(default=".aat")
    max_loops: int = Field(default=10, ge=1, le=100)
    approval_mode: ApprovalMode = Field(default=ApprovalMode.MANUAL)


# ============================================================
# Scenario Models
# ============================================================


def compute_region_bounds(
    region: ScreenRegion,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    """Compute pixel bounds (x, y, w, h) for a named screen region.

    Args:
        region: Named region.
        width: Viewport width in pixels.
        height: Viewport height in pixels.

    Returns:
        Tuple of (x, y, crop_width, crop_height).
    """
    if region == ScreenRegion.FULL:
        return 0, 0, width, height
    if region == ScreenRegion.TOP:
        return 0, 0, width, int(height * 0.3)
    if region == ScreenRegion.BOTTOM:
        y = int(height * 0.7)
        return 0, y, width, height - y
    if region == ScreenRegion.LEFT:
        return 0, 0, int(width * 0.2), height
    if region == ScreenRegion.RIGHT:
        x = int(width * 0.2)
        return x, 0, width - x, height
    if region == ScreenRegion.CENTER:
        x = int(width * 0.2)
        y = int(height * 0.2)
        return x, y, int(width * 0.6), int(height * 0.6)
    if region == ScreenRegion.MAIN:
        x = int(width * 0.2)
        return x, 0, width - x, height
    return 0, 0, width, height


# Actions that require a target for image matching
FIND_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.FIND_AND_CLICK,
        ActionType.FIND_AND_DOUBLE_CLICK,
        ActionType.FIND_AND_RIGHT_CLICK,
        ActionType.FIND_AND_TYPE,
        ActionType.FIND_AND_CLEAR,
    }
)


class IconHint(BaseModel):
    """Icon-based search hint (stub for Ultra-MVP)."""

    description: str = Field(..., description="Icon description")
    label: str | None = Field(default=None)
    label_position: LabelPosition | None = Field(default=None)


class TargetSpec(BaseModel):
    """Match target. At least one of image, text, selector, icon is required."""

    image: str | None = Field(default=None, description="Target image relative path")
    text: str | None = Field(default=None, description="OCR fallback text")
    selector: str | None = Field(default=None, description="CSS selector (highest priority)")
    icon: IconHint | None = Field(default=None, description="Icon hint (future)")
    match_method: MatchMethod | None = Field(default=None)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def at_least_one_target(self) -> TargetSpec:
        if not self.image and not self.text and not self.icon and not self.selector:
            msg = "TargetSpec requires at least one of: image, text, selector, icon"
            raise ValueError(msg)
        return self


class ExpectedResult(BaseModel):
    """Expected result assertion."""

    type: AssertType
    value: str = Field(..., description="Comparison value")
    tolerance: float = Field(default=0.0, ge=0.0, le=1.0)
    case_insensitive: bool = Field(default=False)


class FindMethod(StrEnum):
    """find_and_click matching method preference."""

    AUTO = "auto"
    SEMANTICS = "semantics"
    TEMPLATE = "template"
    OCR = "ocr"
    VISION = "vision"


class StepConfig(BaseModel):
    """Individual test step within a scenario."""

    step: int = Field(..., ge=1, description="Step number (1-based)")
    action: ActionType
    target: TargetSpec | None = Field(default=None)
    value: str | None = Field(default=None)
    description: str = Field(..., min_length=1)
    humanize: bool = Field(default=True)
    method: FindMethod = Field(
        default=FindMethod.AUTO,
        description="Matching method: auto (3-tier fallback), template, ocr, vision",
    )
    learn: bool = Field(
        default=True,
        description="Save successful match to pattern DB for future runs",
    )
    fallback: bool = Field(
        default=True,
        description="Allow tier fallback when specific method fails",
    )
    region: ScreenRegion = Field(
        default=ScreenRegion.FULL,
        description="Screen region to search: full, top, bottom, left, right, center, main",
    )
    threshold: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Change threshold for assert_screen_changed (0.0-1.0)",
    )
    verify: bool = Field(
        default=False,
        description="For type_text: verify typed text appears on screen via OCR",
    )
    message: str = Field(
        default="",
        description="Custom error message for assert_text / assert_screen_changed",
    )
    match_index: int = Field(
        default=0,
        description="Select Nth match when multiple found (0=first, -1=last)",
    )
    name: str = Field(
        default="",
        description="Session name for save_session/load_session",
    )
    if_visible: bool = Field(
        default=False,
        description="Only execute if target is visible on screen. Skip silently if not.",
    )
    critical: bool = Field(
        default=False,
        description="If True, test stops immediately on failure",
    )
    on_fail: str = Field(
        default="",
        description="Action on failure: 'stop' to halt test immediately",
    )
    expect_login_redirect: bool | None = Field(
        default=None,
        description=(
            "Landing on a login page is the expected outcome of this step "
            "(e.g. access-control tests). Disables the login-redirect hard stop "
            "for this step only. None = inherit the scenario-level setting."
        ),
    )
    file_path: str = Field(
        default="",
        description="File path for upload_file action",
    )
    file_paths: list[str] = Field(
        default_factory=list,
        description="Multiple file paths for upload_file action",
    )
    save_as: str = Field(
        default="",
        description="Save result to runtime variable (for find/get_text)",
    )
    expect: dict[str, Any] = Field(
        default_factory=dict,
        description="Post-action expectations: url_contains, text_visible, etc.",
    )
    then: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Sub-steps to execute if if_visible target is found",
    )
    scenario: str = Field(
        default="",
        description="Sub-scenario file path for include action",
    )
    vars: dict[str, str] = Field(
        default_factory=dict,
        description="Variables to pass to included sub-scenario",
    )
    change_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="For critical steps: required pixel change ratio (auto-detected if None)",
    )
    wait_for: str | None = Field(
        default=None,
        description=(
            "Wait for page load state after action: "
            "'networkidle' | 'load' | 'domcontentloaded'. "
            "networkidle waits until no network requests for 500ms."
        ),
    )

    @field_validator("humanize", mode="before")
    @classmethod
    def coerce_humanize(cls, v: object) -> bool:
        """Convert null/None to default True."""
        if v is None:
            return True
        return bool(v)

    screenshot_before: bool = Field(default=False)
    screenshot_after: bool = Field(default=False)
    timeout_ms: int = Field(default=10000, ge=0, le=120000)
    optional: bool = Field(default=False)
    ai_verify: bool | None = Field(
        default=None,
        description="Vision AI step verification. None=follow global config, True/False=override",
    )
    assert_type: AssertType | None = Field(default=None)
    expected: list[ExpectedResult] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def fix_assert_fields(cls, data: Any) -> Any:
        """Auto-fix malformed assert steps from AI output.

        AI sometimes generates assert steps without assert_type or
        expected list. This pre-validator patches missing fields before
        the after-validator rejects them.
        """
        if not isinstance(data, dict):
            return data
        if data.get("action") != "assert":
            return data

        has_at = bool(data.get("assert_type"))
        has_exp = bool(data.get("expected"))
        has_val = bool(data.get("value"))

        if has_at and (has_exp or has_val):
            # Build expected from assert_type + value if missing
            if not has_exp and has_val:
                data["expected"] = [
                    {
                        "type": data["assert_type"],
                        "value": data["value"],
                        "tolerance": 0.0,
                        "case_insensitive": True,
                    }
                ]
            return data

        # Has expected list but no assert_type → derive from first item
        if has_exp and not has_at:
            exp = data["expected"]
            if isinstance(exp, list) and exp:
                first = exp[0]
                if isinstance(first, dict) and first.get("type"):
                    data["assert_type"] = first["type"]
                elif isinstance(first, str):
                    data["assert_type"] = "text_visible"
            return data

        # Has value only → infer assert_type
        if has_val and not has_at:
            val = data["value"]
            if isinstance(val, str):
                is_url = val.startswith("/") or val.startswith("http")
                at = "url_contains" if is_url else "text_visible"
                data["assert_type"] = at
                if not has_exp:
                    data["expected"] = [
                        {
                            "type": at,
                            "value": val,
                            "tolerance": 0.0,
                            "case_insensitive": True,
                        }
                    ]
            return data

        # Don't guess — let validation catch the missing assert_type
        pass

        return data

    @field_validator("expected", mode="before")
    @classmethod
    def coerce_expected(cls, v: object) -> list[dict[str, object]]:
        """Convert string items to ExpectedResult dicts in step-level expected."""
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        result: list[dict[str, object]] = []
        for item in v:
            if isinstance(item, str):
                result.append(
                    {
                        "type": "text_visible",
                        "value": item,
                        "tolerance": 0.0,
                    }
                )
            elif isinstance(item, dict):
                result.append(item)
            else:
                result.append(item)
        return result

    @model_validator(mode="after")
    def validate_action_requirements(self) -> StepConfig:
        if self.action in FIND_ACTIONS and self.target is None:
            msg = f"action={self.action.value} requires a target"
            raise ValueError(msg)
        if self.action == ActionType.ASSERT and self.assert_type is None:
            msg = "action=assert requires assert_type"
            raise ValueError(msg)
        if self.action == ActionType.NAVIGATE and not self.value:
            msg = "action=navigate requires value (URL)"
            raise ValueError(msg)
        if self.action == ActionType.ASSERT_TEXT and self.target is None:
            msg = "action=assert_text requires a target (text to find)"
            raise ValueError(msg)
        if self.action in (
            ActionType.SAVE_SESSION,
            ActionType.LOAD_SESSION,
        ) and not (self.name or self.value):
            msg = f"action={self.action.value} requires name or value"
            raise ValueError(msg)
        if self.action == ActionType.FIND and self.target is None:
            msg = "action=find requires a target"
            raise ValueError(msg)
        if self.action == ActionType.INCLUDE and not (self.scenario or self.value):
            msg = "action=include requires scenario path"
            raise ValueError(msg)
        return self


class TeardownStep(BaseModel):
    """A single cleanup action executed after a scenario completes (pass or fail).

    Supported types:
        api_call  — HTTP request to a cleanup endpoint
        db_query  — raw SQL executed against a database URL
        shell     — shell command (use with caution)
    """

    type: str = Field(..., description="'api_call' | 'db_query' | 'shell'")

    # api_call fields
    method: str | None = Field(default=None, description="HTTP method: GET POST PUT DELETE PATCH")
    url: str | None = Field(default=None, description="Request URL (supports {{variables}})")
    headers: dict[str, str] | None = Field(default=None)
    body: dict[str, Any] | None = Field(default=None)
    expected_status: int | None = Field(
        default=None,
        description="Expected HTTP status code; failure logged but does not stop teardown",
    )

    # db_query fields
    connection: str | None = Field(
        default=None,
        description="DB connection string, e.g. postgresql://host/db",
    )
    query: str | None = Field(default=None, description="SQL to execute (supports {{variables}})")

    # shell fields
    command: str | None = Field(default=None, description="Shell command (supports {{variables}})")
    timeout: int | None = Field(default=30, description="Shell command timeout in seconds")


class Scenario(BaseModel):
    """Test scenario definition."""

    id: str = Field(..., pattern=r"^SC-\d{3,}$", description="Scenario ID: SC-001")
    name: str = Field(..., min_length=1)
    description: str = Field(default="")
    tags: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(
        default_factory=list,
        description="Scenario IDs that must pass before this one runs (e.g. ['SC-001'])",
    )
    vars: dict[str, str] = Field(
        default_factory=dict,
        description="Scenario-level variables (supports {{env.VAR}} references)",
    )
    steps: list[StepConfig] = Field(..., min_length=1)
    expect_login_redirect: bool = Field(
        default=False,
        description=(
            "Landing on a login page is expected throughout this scenario. "
            "Inherited by every step that does not set expect_login_redirect itself. "
            "Disables login-redirect detection for the whole file — prefer the "
            "step-level field unless the entire scenario tests access control."
        ),
    )
    teardown: list[TeardownStep] = Field(
        default_factory=list,
        description="Cleanup steps executed after scenario completes (pass or fail)",
    )

    @field_validator("vars", mode="before")
    @classmethod
    def coerce_vars(cls, v: object) -> dict[str, str]:
        """Coerce vars values to strings; ignore None."""
        if v is None:
            return {}
        if isinstance(v, dict):
            return {str(k): str(val) for k, val in v.items() if val is not None}
        return {}

    @field_validator("depends_on", mode="before")
    @classmethod
    def coerce_depends_on(cls, v: object) -> list[str]:
        """Convert null/None to empty list."""
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x) for x in v if x is not None]
        return []

    @field_validator("tags", mode="before")
    @classmethod
    def coerce_tags(cls, v: object) -> list[str]:
        """Convert null/None to empty list."""
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x) for x in v if x is not None]
        return []

    expected_result: list[ExpectedResult] = Field(default_factory=list)
    variables: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def inherit_expect_login_redirect(cls, data: Any) -> Any:
        """Propagate scenario-level expect_login_redirect to steps that omit it.

        Only steps whose value is None (field absent in YAML) inherit. A step
        that spells out ``expect_login_redirect: false`` keeps its own answer.
        """
        if not isinstance(data, dict) or not data.get("expect_login_redirect"):
            return data

        steps = data.get("steps")
        if not isinstance(steps, list):
            return data

        inherited: list[Any] = []
        for step in steps:
            if isinstance(step, dict):
                if step.get("expect_login_redirect") is None:
                    step = {**step, "expect_login_redirect": True}
            elif getattr(step, "expect_login_redirect", False) is None:
                step = step.model_copy(update={"expect_login_redirect": True})
            inherited.append(step)

        return {**data, "steps": inherited}

    @model_validator(mode="before")
    @classmethod
    def merge_vars_alias(cls, data: Any) -> Any:
        """Support 'vars' as alias for 'variables'."""
        if isinstance(data, dict) and "vars" in data:
            v = data.pop("vars")
            if isinstance(v, dict):
                existing = data.get("variables", {})
                if isinstance(existing, dict):
                    existing.update(v)
                    data["variables"] = existing
                else:
                    data["variables"] = v
        return data

    @field_validator("expected_result", mode="before")
    @classmethod
    def coerce_expected_result(cls, v: object) -> list[dict[str, object]]:
        """Convert string items to ExpectedResult dicts.

        AI sometimes returns plain strings like "User sees welcome message"
        instead of proper ExpectedResult objects.
        """
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        result: list[dict[str, object]] = []
        for item in v:
            if isinstance(item, str):
                result.append(
                    {
                        "type": "text_visible",
                        "value": item,
                        "tolerance": 0.0,
                    }
                )
            elif isinstance(item, dict):
                result.append(item)
            else:
                result.append(item)
        return result


# ============================================================
# Result Models
# ============================================================


class MatchResult(BaseModel):
    """Image matching result."""

    found: bool
    x: int = Field(default=0)
    y: int = Field(default=0)
    width: int = Field(default=0)
    height: int = Field(default=0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    method: MatchMethod = Field(default=MatchMethod.TEMPLATE)
    elapsed_ms: float = Field(default=0.0, ge=0.0)


class StepResult(BaseModel):
    """Individual step execution result."""

    step: int
    action: ActionType
    status: StepStatus
    description: str
    match_result: MatchResult | None = None
    screenshot_before: str | None = None
    screenshot_after: str | None = None
    error_message: str | None = None
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    timestamp: datetime = Field(default_factory=datetime.now)


class TestResult(BaseModel):
    """Single scenario execution result."""

    scenario_id: str
    scenario_name: str
    passed: bool
    steps: list[StepResult]
    total_steps: int = Field(ge=0)
    passed_steps: int = Field(ge=0)
    failed_steps: int = Field(ge=0)
    duration_ms: float = Field(ge=0.0)
    timestamp: datetime = Field(default_factory=datetime.now)


class FileChange(BaseModel):
    """Individual file change from AI fix."""

    path: str = Field(..., description="File path relative to project root")
    original: str
    modified: str
    description: str = Field(default="")


class AnalysisResult(BaseModel):
    """AI failure analysis result."""

    cause: str
    suggestion: str
    severity: Severity
    related_files: list[str] = Field(default_factory=list)


class FixResult(BaseModel):
    """AI code fix result."""

    description: str
    files_changed: list[FileChange]
    confidence: float = Field(..., ge=0.0, le=1.0)


class LoopIteration(BaseModel):
    """Single DevQA Loop iteration result."""

    iteration: int = Field(..., ge=1)
    test_result: TestResult
    analysis: AnalysisResult | None = None
    fix: FixResult | None = None
    approved: bool | None = None
    branch_name: str | None = None
    commit_hash: str | None = None
    timestamp: datetime = Field(default_factory=datetime.now)


class LoopResult(BaseModel):
    """Full DevQA Loop execution result."""

    success: bool
    total_iterations: int = Field(ge=0)
    iterations: list[LoopIteration]
    reason: str | None = Field(default=None)
    duration_ms: float = Field(ge=0.0)
    timestamp: datetime = Field(default_factory=datetime.now)


# ============================================================
# Learning Model
# ============================================================


class LearnedElement(BaseModel):
    """Learned element position from interactive learning."""

    id: int | None = Field(default=None, description="DB PK")
    scenario_id: str
    step_number: int = Field(ge=1)
    target_name: str
    screenshot_hash: str
    correct_x: int = Field(ge=0)
    correct_y: int = Field(ge=0)
    cropped_image_path: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    use_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


# ============================================================
# Visual Regression Models
# ============================================================


class StepDiffResult(BaseModel):
    """Single step visual regression comparison result."""

    step: int = Field(ge=1)
    baseline_path: str | None = None
    current_path: str | None = None
    ssim_score: float = Field(default=0.0, ge=0.0, le=1.0)
    status: str = Field(
        default="pass",
        description="pass | fail | missing_baseline | missing_current",
    )
    diff_image_path: str | None = None


class VisualDiffReport(BaseModel):
    """Full visual regression diff report for a scenario."""

    scenario_id: str
    scenario_name: str
    threshold: float = Field(default=0.95, ge=0.0, le=1.0)
    steps: list[StepDiffResult] = Field(default_factory=list)
    passed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    timestamp: datetime = Field(default_factory=datetime.now)


class BaselineMeta(BaseModel):
    """Metadata for a saved baseline."""

    scenario_id: str
    scenario_name: str = ""
    url: str = ""
    step_count: int = Field(default=0, ge=0)
    captured_at: datetime = Field(default_factory=datetime.now)
