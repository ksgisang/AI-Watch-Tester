"""Tests for core data models."""

import pytest
from pydantic import ValidationError

from aat import __version__
from aat.core.models import (
    FIND_ACTIONS,
    ActionType,
    AIConfig,
    AnalysisResult,
    ApprovalMode,
    AssertType,
    Config,
    EngineConfig,
    ExpectedResult,
    FileChange,
    FixResult,
    IconHint,
    LabelPosition,
    LearnedElement,
    LoopIteration,
    LoopResult,
    MatchingConfig,
    MatchMethod,
    MatchResult,
    Scenario,
    Severity,
    StepConfig,
    StepResult,
    StepStatus,
    TargetSpec,
    TestResult,
)


def test_version() -> None:
    assert __version__ == "1.5.5"


# ── Enum Tests ──


class TestActionType:
    def test_values(self) -> None:
        assert ActionType.NAVIGATE == "navigate"
        assert ActionType.FIND_AND_CLICK == "find_and_click"
        assert ActionType.ASSERT == "assert"
        assert ActionType.SCREENSHOT == "screenshot"

    def test_all_members(self) -> None:
        assert len(ActionType) == 27

    def test_from_string(self) -> None:
        assert ActionType("navigate") is ActionType.NAVIGATE
        assert ActionType("find_and_type") is ActionType.FIND_AND_TYPE

    def test_invalid_value(self) -> None:
        with pytest.raises(ValueError):
            ActionType("invalid_action")


class TestLabelPosition:
    def test_all_values(self) -> None:
        assert len(LabelPosition) == 5
        assert LabelPosition.ABOVE == "above"
        assert LabelPosition.INSIDE == "inside"


class TestAssertType:
    def test_all_values(self) -> None:
        assert len(AssertType) == 6
        assert AssertType.TEXT_VISIBLE == "text_visible"
        assert AssertType.URL_NOT_CONTAINS == "url_not_contains"
        assert AssertType.SCREENSHOT_MATCH == "screenshot_match"


class TestMatchMethod:
    def test_all_values(self) -> None:
        assert len(MatchMethod) == 6
        assert MatchMethod.LEARNED == "learned"
        assert MatchMethod.VISION_AI == "vision_ai"

    def test_chain_order(self) -> None:
        order = [MatchMethod.TEMPLATE, MatchMethod.OCR]
        assert order[0] == "template"


class TestSeverity:
    def test_all_values(self) -> None:
        assert len(Severity) == 3
        assert Severity.CRITICAL == "critical"


class TestStepStatus:
    def test_all_values(self) -> None:
        assert len(StepStatus) == 7
        assert StepStatus.PASSED == "passed"
        assert StepStatus.WARNING == "warning"
        assert StepStatus.ERROR == "error"


class TestFindActions:
    def test_contains_find_actions(self) -> None:
        assert ActionType.FIND_AND_CLICK in FIND_ACTIONS
        assert ActionType.FIND_AND_TYPE in FIND_ACTIONS
        assert ActionType.FIND_AND_CLEAR in FIND_ACTIONS
        assert len(FIND_ACTIONS) == 5

    def test_excludes_non_find_actions(self) -> None:
        assert ActionType.NAVIGATE not in FIND_ACTIONS
        assert ActionType.CLICK_AT not in FIND_ACTIONS
        assert ActionType.ASSERT not in FIND_ACTIONS


# ── Config Model Tests ──


class TestAIConfig:
    def test_defaults(self) -> None:
        cfg = AIConfig()
        assert cfg.provider == "claude"
        assert cfg.api_key == ""
        assert cfg.max_tokens == 4000
        assert cfg.temperature == 0.3

    def test_custom_values(self) -> None:
        cfg = AIConfig(provider="gpt", api_key="sk-test", max_tokens=8000)
        assert cfg.provider == "gpt"
        assert cfg.api_key == "sk-test"
        assert cfg.max_tokens == 8000

    def test_temperature_bounds(self) -> None:
        with pytest.raises(ValidationError):
            AIConfig(temperature=1.5)
        with pytest.raises(ValidationError):
            AIConfig(temperature=-0.1)


class TestEngineConfig:
    def test_defaults(self) -> None:
        cfg = EngineConfig()
        assert cfg.type == "web"
        assert cfg.browser == "chromium"
        assert cfg.headless is False
        assert cfg.viewport_width == 1280
        assert cfg.viewport_height == 720

    def test_viewport_bounds(self) -> None:
        with pytest.raises(ValidationError):
            EngineConfig(viewport_width=100)


class TestMatchingConfig:
    def test_defaults(self) -> None:
        cfg = MatchingConfig()
        assert cfg.confidence_threshold == 0.85
        assert cfg.multi_scale is True
        assert cfg.chain_order == [
            MatchMethod.LEARNED,
            MatchMethod.TEMPLATE,
            MatchMethod.OCR,
            MatchMethod.FEATURE,
            MatchMethod.VISION_AI,
        ]

    def test_custom_chain_order(self) -> None:
        cfg = MatchingConfig(chain_order=[MatchMethod.TEMPLATE, MatchMethod.OCR])
        assert len(cfg.chain_order) == 2


class TestConfig:
    def test_defaults(self) -> None:
        cfg = Config()
        assert cfg.project_name == "aat-project"
        assert cfg.ai.provider == "claude"
        assert cfg.engine.type == "web"
        assert cfg.matching.confidence_threshold == 0.85
        assert cfg.humanizer.enabled is True
        assert cfg.max_loops == 10

    def test_nested_override(self) -> None:
        cfg = Config(
            project_name="test-proj",
            ai=AIConfig(provider="gpt"),
            max_loops=5,
        )
        assert cfg.project_name == "test-proj"
        assert cfg.ai.provider == "gpt"
        assert cfg.max_loops == 5

    def test_max_loops_bounds(self) -> None:
        with pytest.raises(ValidationError):
            Config(max_loops=0)
        with pytest.raises(ValidationError):
            Config(max_loops=200)


# ── Scenario Model Tests ──


class TestTargetSpec:
    def test_image_only(self) -> None:
        t = TargetSpec(image="button.png")
        assert t.image == "button.png"
        assert t.text is None

    def test_text_only(self) -> None:
        t = TargetSpec(text="Login")
        assert t.text == "Login"

    def test_icon_only(self) -> None:
        t = TargetSpec(icon=IconHint(description="magnifying glass"))
        assert t.icon is not None

    def test_image_and_text(self) -> None:
        t = TargetSpec(image="btn.png", text="Login")
        assert t.image == "btn.png"
        assert t.text == "Login"

    def test_no_target_fails(self) -> None:
        with pytest.raises(ValidationError, match="at least one"):
            TargetSpec()

    def test_confidence_override(self) -> None:
        t = TargetSpec(image="btn.png", confidence=0.95)
        assert t.confidence == 0.95

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            TargetSpec(image="btn.png", confidence=1.5)

    def test_match_method_override(self) -> None:
        t = TargetSpec(image="btn.png", match_method=MatchMethod.FEATURE)
        assert t.match_method == MatchMethod.FEATURE


class TestExpectedResult:
    def test_basic(self) -> None:
        er = ExpectedResult(type=AssertType.TEXT_VISIBLE, value="Welcome")
        assert er.type == AssertType.TEXT_VISIBLE
        assert er.tolerance == 0.0

    def test_with_tolerance(self) -> None:
        er = ExpectedResult(
            type=AssertType.SCREENSHOT_MATCH,
            value="expected.png",
            tolerance=0.1,
        )
        assert er.tolerance == 0.1


class TestStepConfig:
    def test_navigate_valid(self) -> None:
        step = StepConfig(
            step=1,
            action=ActionType.NAVIGATE,
            value="http://localhost",
            description="Go to homepage",
        )
        assert step.step == 1
        assert step.humanize is True

    def test_navigate_without_value_fails(self) -> None:
        with pytest.raises(ValidationError, match="navigate requires value"):
            StepConfig(
                step=1,
                action=ActionType.NAVIGATE,
                description="Go somewhere",
            )

    def test_find_and_click_valid(self) -> None:
        step = StepConfig(
            step=2,
            action=ActionType.FIND_AND_CLICK,
            target=TargetSpec(image="btn.png"),
            description="Click button",
        )
        assert step.target is not None
        assert step.target.image == "btn.png"

    def test_find_and_click_without_target_fails(self) -> None:
        with pytest.raises(ValidationError, match="requires a target"):
            StepConfig(
                step=2,
                action=ActionType.FIND_AND_CLICK,
                description="Click button",
            )

    def test_assert_valid(self) -> None:
        step = StepConfig(
            step=3,
            action=ActionType.ASSERT,
            assert_type=AssertType.URL_CONTAINS,
            value="/dashboard",
            description="Check URL",
        )
        assert step.assert_type == AssertType.URL_CONTAINS

    def test_assert_without_type_auto_fixed(self) -> None:
        """Assert step missing assert_type is auto-fixed from value."""
        step = StepConfig(
            step=3,
            action=ActionType.ASSERT,
            value="/dashboard",
            description="Check URL",
        )
        assert step.assert_type == AssertType.URL_CONTAINS
        assert len(step.expected) == 1
        assert step.expected[0].value == "/dashboard"

    def test_assert_no_type_no_value_raises_validation_error(self) -> None:
        """Assert step without type or value should raise ValidationError."""
        with pytest.raises(ValidationError):
            StepConfig(
                step=3,
                action=ActionType.ASSERT,
                description="Welcome page loaded",
            )

    def test_find_and_type_valid(self) -> None:
        step = StepConfig(
            step=4,
            action=ActionType.FIND_AND_TYPE,
            target=TargetSpec(text="Email"),
            value="test@test.com",
            description="Type email",
        )
        assert step.value == "test@test.com"

    def test_select_option_valid(self) -> None:
        step = StepConfig(
            step=4,
            action=ActionType.SELECT_OPTION,
            target=TargetSpec(selector="#grade"),
            value="3학년",
            description="Pick a grade",
        )
        assert step.value == "3학년"

    def test_select_option_without_selector_fails(self) -> None:
        with pytest.raises(ValidationError, match="target.selector"):
            StepConfig(
                step=4,
                action=ActionType.SELECT_OPTION,
                target=TargetSpec(text="Grade"),
                value="3학년",
                description="Text target is not enough for a native select",
            )

    def test_select_option_without_value_fails(self) -> None:
        with pytest.raises(ValidationError, match="requires value"):
            StepConfig(
                step=4,
                action=ActionType.SELECT_OPTION,
                target=TargetSpec(selector="#grade"),
                description="No option to pick",
            )

    def test_wait_step(self) -> None:
        step = StepConfig(
            step=5,
            action=ActionType.WAIT,
            value="2000",
            description="Wait 2 seconds",
        )
        assert step.action == ActionType.WAIT

    def test_optional_step(self) -> None:
        step = StepConfig(
            step=6,
            action=ActionType.SCREENSHOT,
            description="Take screenshot",
            optional=True,
        )
        assert step.optional is True

    def test_step_number_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            StepConfig(
                step=0,
                action=ActionType.SCREENSHOT,
                description="Bad step",
            )


class TestScenario:
    def test_valid_scenario(self) -> None:
        sc = Scenario(
            id="SC-001",
            name="Login test",
            steps=[
                StepConfig(
                    step=1,
                    action=ActionType.NAVIGATE,
                    value="http://localhost",
                    description="Go to site",
                ),
            ],
        )
        assert sc.id == "SC-001"
        assert len(sc.steps) == 1

    def test_invalid_id_pattern(self) -> None:
        with pytest.raises(ValidationError, match="pattern"):
            Scenario(
                id="INVALID",
                name="Bad ID",
                steps=[
                    StepConfig(
                        step=1,
                        action=ActionType.SCREENSHOT,
                        description="x",
                    ),
                ],
            )

    def test_id_with_more_digits(self) -> None:
        sc = Scenario(
            id="SC-1000",
            name="Large ID",
            steps=[
                StepConfig(
                    step=1,
                    action=ActionType.SCREENSHOT,
                    description="x",
                ),
            ],
        )
        assert sc.id == "SC-1000"

    def test_empty_steps_fails(self) -> None:
        with pytest.raises(ValidationError):
            Scenario(id="SC-001", name="Empty", steps=[])

    def test_with_expected_result(self) -> None:
        sc = Scenario(
            id="SC-002",
            name="With assertions",
            steps=[
                StepConfig(
                    step=1,
                    action=ActionType.SCREENSHOT,
                    description="x",
                ),
            ],
            expected_result=[
                ExpectedResult(type=AssertType.TEXT_VISIBLE, value="Welcome"),
            ],
        )
        assert len(sc.expected_result) == 1

    def test_with_variables(self) -> None:
        sc = Scenario(
            id="SC-003",
            name="With vars",
            steps=[
                StepConfig(
                    step=1,
                    action=ActionType.NAVIGATE,
                    value="{{url}}/login",
                    description="Go to login",
                ),
            ],
            variables={"url": "http://localhost:3000"},
        )
        assert sc.variables["url"] == "http://localhost:3000"

    def test_with_tags(self) -> None:
        sc = Scenario(
            id="SC-004",
            name="Tagged",
            tags=["smoke", "login"],
            steps=[
                StepConfig(
                    step=1,
                    action=ActionType.SCREENSHOT,
                    description="x",
                ),
            ],
        )
        assert "smoke" in sc.tags


# ── Result Model Tests ──


class TestExpectLoginRedirect:
    """Step-level mark, with scenario-level inheritance for steps that omit it."""

    @staticmethod
    def _step(num: int, **kwargs: object) -> StepConfig:
        return StepConfig(
            step=num,
            action=ActionType.SCREENSHOT,
            description=f"step {num}",
            **kwargs,  # type: ignore[arg-type]
        )

    def test_default_is_none_not_false(self) -> None:
        """None is what makes 'not written' distinguishable from 'turned off'."""
        assert self._step(1).expect_login_redirect is None

    def test_step_value_survives_yaml(self) -> None:
        assert self._step(1, expect_login_redirect=True).expect_login_redirect is True
        assert self._step(1, expect_login_redirect=False).expect_login_redirect is False

    def test_scenario_level_propagates_to_unset_steps(self) -> None:
        sc = Scenario(
            id="SC-001",
            name="Access control",
            expect_login_redirect=True,
            steps=[self._step(1), self._step(2)],
        )
        assert [s.expect_login_redirect for s in sc.steps] == [True, True]

    def test_scenario_level_does_not_override_explicit_step_false(self) -> None:
        sc = Scenario(
            id="SC-001",
            name="Access control",
            expect_login_redirect=True,
            steps=[self._step(1), self._step(2, expect_login_redirect=False)],
        )
        assert [s.expect_login_redirect for s in sc.steps] == [True, False]

    def test_steps_untouched_when_scenario_flag_off(self) -> None:
        sc = Scenario(
            id="SC-001",
            name="Normal",
            steps=[self._step(1), self._step(2, expect_login_redirect=True)],
        )
        assert sc.expect_login_redirect is False
        assert [s.expect_login_redirect for s in sc.steps] == [None, True]

    def test_propagation_from_raw_dicts(self) -> None:
        """The YAML path builds steps as dicts, not StepConfig objects."""
        sc = Scenario.model_validate(
            {
                "id": "SC-001",
                "name": "Access control",
                "expect_login_redirect": True,
                "steps": [
                    {"step": 1, "action": "navigate", "value": "/", "description": "home"},
                    {
                        "step": 2,
                        "action": "assert_url",
                        "value": "/login",
                        "description": "bounced",
                        "expect_login_redirect": False,
                    },
                ],
            }
        )
        assert [s.expect_login_redirect for s in sc.steps] == [True, False]


class TestMatchResult:
    def test_found(self) -> None:
        mr = MatchResult(found=True, x=100, y=200, confidence=0.92)
        assert mr.found is True
        assert mr.x == 100
        assert mr.method == MatchMethod.TEMPLATE

    def test_not_found(self) -> None:
        mr = MatchResult(found=False)
        assert mr.confidence == 0.0


class TestStepResult:
    def test_passed(self) -> None:
        sr = StepResult(
            step=1,
            action=ActionType.NAVIGATE,
            status=StepStatus.PASSED,
            description="Go to page",
            elapsed_ms=150.0,
        )
        assert sr.status == StepStatus.PASSED
        assert sr.error_message is None

    def test_failed_with_error(self) -> None:
        sr = StepResult(
            step=2,
            action=ActionType.FIND_AND_CLICK,
            status=StepStatus.FAILED,
            description="Click button",
            error_message="Element not found",
        )
        assert sr.error_message == "Element not found"


class TestTestResult:
    def _make_step_result(self, passed: bool) -> StepResult:
        return StepResult(
            step=1,
            action=ActionType.NAVIGATE,
            status=StepStatus.PASSED if passed else StepStatus.FAILED,
            description="test step",
        )

    def test_passed_result(self) -> None:
        tr = TestResult(
            scenario_id="SC-001",
            scenario_name="Login",
            passed=True,
            steps=[self._make_step_result(True)],
            total_steps=1,
            passed_steps=1,
            failed_steps=0,
            duration_ms=500.0,
        )
        assert tr.passed is True


class TestAnalysisResult:
    def test_basic(self) -> None:
        ar = AnalysisResult(
            cause="Button selector changed",
            suggestion="Update selector",
            severity=Severity.CRITICAL,
            related_files=["src/app.py"],
        )
        assert ar.severity == Severity.CRITICAL
        assert len(ar.related_files) == 1


class TestFixResult:
    def test_basic(self) -> None:
        fr = FixResult(
            description="Fix login button selector",
            files_changed=[
                FileChange(
                    path="src/app.py",
                    original="old code",
                    modified="new code",
                ),
            ],
            confidence=0.85,
        )
        assert len(fr.files_changed) == 1
        assert fr.confidence == 0.85


class TestLoopResult:
    def test_success(self) -> None:
        step_result = StepResult(
            step=1,
            action=ActionType.NAVIGATE,
            status=StepStatus.PASSED,
            description="x",
        )
        test_result = TestResult(
            scenario_id="SC-001",
            scenario_name="Login",
            passed=True,
            steps=[step_result],
            total_steps=1,
            passed_steps=1,
            failed_steps=0,
            duration_ms=100.0,
        )
        lr = LoopResult(
            success=True,
            total_iterations=1,
            iterations=[
                LoopIteration(iteration=1, test_result=test_result),
            ],
            reason="all_passed",
            duration_ms=500.0,
        )
        assert lr.success is True
        assert lr.total_iterations == 1


# ── Learning Model Tests ──


class TestLearnedElement:
    def test_create(self) -> None:
        le = LearnedElement(
            scenario_id="SC-001",
            step_number=1,
            target_name="login_button.png",
            screenshot_hash="abc123",
            correct_x=100,
            correct_y=200,
            cropped_image_path=".aat/learned/login_v1.png",
        )
        assert le.id is None
        assert le.confidence == 1.0
        assert le.use_count == 0

    def test_with_id(self) -> None:
        le = LearnedElement(
            id=42,
            scenario_id="SC-001",
            step_number=2,
            target_name="submit.png",
            screenshot_hash="def456",
            correct_x=300,
            correct_y=400,
            cropped_image_path=".aat/learned/submit_v1.png",
            confidence=0.9,
            use_count=5,
        )
        assert le.id == 42
        assert le.use_count == 5


# ── Serialization Tests ──


class TestSerialization:
    def test_config_to_dict(self) -> None:
        cfg = Config()
        d = cfg.model_dump()
        assert d["project_name"] == "aat-project"
        assert d["ai"]["provider"] == "claude"

    def test_config_from_dict(self) -> None:
        data = {"project_name": "my-proj", "max_loops": 5}
        cfg = Config(**data)
        assert cfg.project_name == "my-proj"
        assert cfg.max_loops == 5

    def test_scenario_roundtrip(self) -> None:
        sc = Scenario(
            id="SC-001",
            name="Test",
            steps=[
                StepConfig(
                    step=1,
                    action=ActionType.NAVIGATE,
                    value="http://localhost",
                    description="Go",
                ),
            ],
        )
        d = sc.model_dump()
        sc2 = Scenario(**d)
        assert sc2.id == sc.id
        assert sc2.steps[0].action == ActionType.NAVIGATE

    def test_enum_serialization(self) -> None:
        mr = MatchResult(found=True, method=MatchMethod.OCR)
        d = mr.model_dump()
        assert d["method"] == "ocr"

    def test_target_spec_json(self) -> None:
        t = TargetSpec(image="btn.png", text="Login", confidence=0.9)
        j = t.model_dump_json()
        assert "btn.png" in j
        t2 = TargetSpec.model_validate_json(j)
        assert t2.confidence == 0.9


# ── ApprovalMode Tests ──


class TestApprovalMode:
    def test_all_values(self) -> None:
        assert len(ApprovalMode) == 3
        assert ApprovalMode.MANUAL == "manual"
        assert ApprovalMode.BRANCH == "branch"
        assert ApprovalMode.AUTO == "auto"

    def test_from_string(self) -> None:
        assert ApprovalMode("manual") is ApprovalMode.MANUAL
        assert ApprovalMode("branch") is ApprovalMode.BRANCH
        assert ApprovalMode("auto") is ApprovalMode.AUTO

    def test_invalid_value(self) -> None:
        with pytest.raises(ValueError):
            ApprovalMode("invalid")


class TestConfigApprovalMode:
    def test_default_is_manual(self) -> None:
        cfg = Config()
        assert cfg.approval_mode == ApprovalMode.MANUAL

    def test_set_branch(self) -> None:
        cfg = Config(approval_mode=ApprovalMode.BRANCH)
        assert cfg.approval_mode == ApprovalMode.BRANCH

    def test_set_auto(self) -> None:
        cfg = Config(approval_mode=ApprovalMode.AUTO)
        assert cfg.approval_mode == ApprovalMode.AUTO

    def test_serialization(self) -> None:
        cfg = Config(approval_mode=ApprovalMode.BRANCH)
        d = cfg.model_dump()
        assert d["approval_mode"] == "branch"


class TestLoopIterationBranchFields:
    def test_defaults_none(self) -> None:
        step = StepResult(
            step=1,
            action=ActionType.NAVIGATE,
            status=StepStatus.PASSED,
            description="x",
        )
        tr = TestResult(
            scenario_id="SC-001",
            scenario_name="Test",
            passed=True,
            steps=[step],
            total_steps=1,
            passed_steps=1,
            failed_steps=0,
            duration_ms=100.0,
        )
        it = LoopIteration(iteration=1, test_result=tr)
        assert it.branch_name is None
        assert it.commit_hash is None

    def test_with_branch_info(self) -> None:
        step = StepResult(
            step=1,
            action=ActionType.NAVIGATE,
            status=StepStatus.PASSED,
            description="x",
        )
        tr = TestResult(
            scenario_id="SC-001",
            scenario_name="Test",
            passed=True,
            steps=[step],
            total_steps=1,
            passed_steps=1,
            failed_steps=0,
            duration_ms=100.0,
        )
        it = LoopIteration(
            iteration=1,
            test_result=tr,
            branch_name="aat/fix-001",
            commit_hash="abc1234",
        )
        assert it.branch_name == "aat/fix-001"
        assert it.commit_hash == "abc1234"
