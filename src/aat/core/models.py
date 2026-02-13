"""AAT data models — Pydantic v2.

This module is a leaf: no internal project imports.
All Enum and Model definitions live here.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator
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
    # Utility
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    SCROLL = "scroll"


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
    SCREENSHOT_MATCH = "screenshot_match"


class MatchMethod(StrEnum):
    """Image matching algorithm."""

    LEARNED = "learned"
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
        ],
    )


class HumanizerConfig(BaseModel):
    """Humanizer configuration."""

    enabled: bool = Field(default=True)
    mouse_speed_min: float = Field(default=0.5)
    mouse_speed_max: float = Field(default=1.2)
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
    engine: EngineConfig = Field(default_factory=EngineConfig)
    matching: MatchingConfig = Field(default_factory=MatchingConfig)
    humanizer: HumanizerConfig = Field(default_factory=HumanizerConfig)
    scenarios_dir: str = Field(default="scenarios")
    reports_dir: str = Field(default="reports")
    assets_dir: str = Field(default="assets")
    data_dir: str = Field(default=".aat")
    max_loops: int = Field(default=10, ge=1, le=100)
    approval_mode: ApprovalMode = Field(default=ApprovalMode.MANUAL)


# ============================================================
# Scenario Models
# ============================================================

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
    """Match target. At least one of image, text, icon is required."""

    image: str | None = Field(default=None, description="Target image relative path")
    text: str | None = Field(default=None, description="OCR fallback text")
    icon: IconHint | None = Field(default=None, description="Icon hint (future)")
    match_method: MatchMethod | None = Field(default=None)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def at_least_one_target(self) -> TargetSpec:
        if not self.image and not self.text and not self.icon:
            msg = "TargetSpec requires at least one of: image, text, icon"
            raise ValueError(msg)
        return self


class ExpectedResult(BaseModel):
    """Expected result assertion."""

    type: AssertType
    value: str = Field(..., description="Comparison value")
    tolerance: float = Field(default=0.0, ge=0.0, le=1.0)


class StepConfig(BaseModel):
    """Individual test step within a scenario."""

    step: int = Field(..., ge=1, description="Step number (1-based)")
    action: ActionType
    target: TargetSpec | None = Field(default=None)
    value: str | None = Field(default=None)
    description: str = Field(..., min_length=1)
    humanize: bool = Field(default=True)
    screenshot_before: bool = Field(default=False)
    screenshot_after: bool = Field(default=False)
    timeout_ms: int = Field(default=10000, ge=0, le=120000)
    optional: bool = Field(default=False)
    assert_type: AssertType | None = Field(default=None)
    expected: list[ExpectedResult] = Field(default_factory=list)

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
        return self


class Scenario(BaseModel):
    """Test scenario definition."""

    id: str = Field(..., pattern=r"^SC-\d{3,}$", description="Scenario ID: SC-001")
    name: str = Field(..., min_length=1)
    description: str = Field(default="")
    tags: list[str] = Field(default_factory=list)
    steps: list[StepConfig] = Field(..., min_length=1)
    expected_result: list[ExpectedResult] = Field(default_factory=list)
    variables: dict[str, str] = Field(default_factory=dict)


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
