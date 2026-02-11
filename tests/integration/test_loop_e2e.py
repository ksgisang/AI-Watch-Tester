"""Integration tests — full pipeline E2E with mocked externals.

Tests the complete flow: init → validate → run → loop,
using the real CLI (CliRunner) and real components where possible,
mocking only external dependencies (Playwright, Claude API).
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml
from typer.testing import CliRunner

from aat.cli.main import app
from aat.core.config import save_config
from aat.core.loop import DevQALoop
from aat.core.models import (
    ActionType,
    AnalysisResult,
    Config,
    FixResult,
    MatchMethod,
    MatchResult,
    Scenario,
    Severity,
    StepConfig,
    StepResult,
    StepStatus,
    TargetSpec,
)
from aat.core.scenario_loader import load_scenario, load_scenarios
from aat.engine.comparator import Comparator
from aat.engine.executor import StepExecutor
from aat.engine.humanizer import Humanizer
from aat.engine.waiter import Waiter
from aat.learning.store import LearnedStore

runner = CliRunner()

# ── Fixtures ─────────────────────────────────────────────────────────────────

SAMPLE_SCENARIO_YAML = {
    "id": "SC-001",
    "name": "Login Test",
    "description": "Test login flow",
    "tags": ["smoke"],
    "steps": [
        {
            "step": 1,
            "action": "navigate",
            "value": "http://localhost:8080/login",
            "description": "Go to login page",
        },
        {
            "step": 2,
            "action": "find_and_click",
            "target": {"text": "Login"},
            "description": "Click login button",
        },
        {
            "step": 3,
            "action": "find_and_type",
            "target": {"text": "Username"},
            "value": "admin",
            "description": "Type username",
        },
    ],
}


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    """Create a temporary project directory with config and scenario."""
    proj = tmp_path / "test_project"
    proj.mkdir()

    # Config
    config = Config(project_name="e2e-test", url="http://localhost:8080")
    save_config(config, proj / "aat.config.yaml")

    # Scenarios dir
    scenario_dir = proj / "scenarios"
    scenario_dir.mkdir()
    with open(scenario_dir / "login.yaml", "w") as f:
        yaml.safe_dump(SAMPLE_SCENARIO_YAML, f, default_flow_style=False)

    return proj


@pytest.fixture()
def bad_scenario_dir(tmp_path: Path) -> Path:
    """Create a project dir with an invalid scenario."""
    proj = tmp_path / "bad_project"
    proj.mkdir()
    scenario_dir = proj / "scenarios"
    scenario_dir.mkdir()

    # Invalid: missing required fields
    bad = {"id": "SC-001", "name": "Bad"}  # no steps
    with open(scenario_dir / "bad.yaml", "w") as f:
        yaml.safe_dump(bad, f)

    return proj


# ── CLI init E2E ─────────────────────────────────────────────────────────────


class TestInitE2E:
    def test_init_creates_structure(self, tmp_path: Path) -> None:
        """aat init should create .aat/, scenarios/, and config file."""
        result = runner.invoke(
            app,
            ["init", "--name", "my-project", "--url", "http://example.com"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "initialized successfully" in result.output

    def test_init_idempotent(self, tmp_path: Path) -> None:
        """Running init twice should not fail."""
        runner.invoke(app, ["init", "--name", "p1"])
        result = runner.invoke(app, ["init", "--name", "p1"])
        assert result.exit_code == 0


# ── CLI validate E2E ─────────────────────────────────────────────────────────


class TestValidateE2E:
    def test_validate_valid_scenario(self, project_dir: Path) -> None:
        scenario_file = project_dir / "scenarios" / "login.yaml"
        result = runner.invoke(app, ["validate", str(scenario_file)])
        assert result.exit_code == 0
        assert "OK" in result.output

    def test_validate_directory(self, project_dir: Path) -> None:
        scenario_dir = project_dir / "scenarios"
        result = runner.invoke(app, ["validate", str(scenario_dir)])
        assert result.exit_code == 0
        assert "1 OK" in result.output

    def test_validate_invalid_scenario(self, bad_scenario_dir: Path) -> None:
        scenario_dir = bad_scenario_dir / "scenarios"
        result = runner.invoke(app, ["validate", str(scenario_dir)])
        assert result.exit_code == 1
        assert "ERROR" in result.output

    def test_validate_nonexistent_path(self) -> None:
        result = runner.invoke(app, ["validate", "/nonexistent/path"])
        assert result.exit_code == 1

    def test_validate_empty_dir(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(app, ["validate", str(empty)])
        assert result.exit_code == 1


# ── Scenario loading E2E ─────────────────────────────────────────────────────


class TestScenarioLoading:
    def test_load_single_scenario(self, project_dir: Path) -> None:
        path = project_dir / "scenarios" / "login.yaml"
        scenario = load_scenario(path)
        assert scenario.id == "SC-001"
        assert len(scenario.steps) == 3

    def test_load_directory(self, project_dir: Path) -> None:
        path = project_dir / "scenarios"
        scenarios = load_scenarios(path)
        assert len(scenarios) == 1
        assert scenarios[0].name == "Login Test"

    def test_variable_substitution(self, tmp_path: Path) -> None:
        scenario_data = {
            "id": "SC-002",
            "name": "Var Test",
            "variables": {"base_url": "http://test.com"},
            "steps": [
                {
                    "step": 1,
                    "action": "navigate",
                    "value": "{{base_url}}/login",
                    "description": "Navigate with variable",
                },
            ],
        }
        path = tmp_path / "var_scenario.yaml"
        with open(path, "w") as f:
            yaml.safe_dump(scenario_data, f)

        scenario = load_scenario(path)
        assert scenario.steps[0].value == "http://test.com/login"

    def test_env_variable_substitution(self, tmp_path: Path) -> None:
        scenario_data = {
            "id": "SC-003",
            "name": "Env Test",
            "steps": [
                {
                    "step": 1,
                    "action": "navigate",
                    "value": "{{env.AAT_TEST_URL}}",
                    "description": "Navigate with env var",
                },
            ],
        }
        path = tmp_path / "env_scenario.yaml"
        with open(path, "w") as f:
            yaml.safe_dump(scenario_data, f)

        os.environ["AAT_TEST_URL"] = "http://env-test.com"
        try:
            scenario = load_scenario(path)
            assert scenario.steps[0].value == "http://env-test.com"
        finally:
            del os.environ["AAT_TEST_URL"]


# ── StepExecutor E2E ─────────────────────────────────────────────────────────


class TestStepExecutorE2E:
    """Test StepExecutor with mock engine/matcher but real comparator/waiter."""

    @pytest.fixture()
    def mock_engine(self) -> AsyncMock:
        engine = AsyncMock()
        engine.screenshot = AsyncMock(return_value=b"\x89PNG_fake_screenshot")
        engine.click = AsyncMock()
        engine.type_text = AsyncMock()
        engine.navigate = AsyncMock()
        engine.press_key = AsyncMock()
        engine.go_back = AsyncMock()
        engine.refresh = AsyncMock()
        engine.current_url = AsyncMock(return_value="http://example.com/page")
        engine.page_text = AsyncMock(return_value="Hello World")
        engine.mouse_position = (0, 0)
        engine.move_mouse = AsyncMock()
        engine.find_text_position = AsyncMock(return_value=(1, 1))
        return engine

    @pytest.fixture()
    def mock_matcher(self) -> AsyncMock:
        matcher = AsyncMock()
        matcher.find = AsyncMock(
            return_value=MatchResult(
                found=True, x=100, y=200, confidence=0.95, method=MatchMethod.TEMPLATE
            )
        )
        return matcher

    @pytest.fixture()
    def executor(
        self, mock_engine: AsyncMock, mock_matcher: AsyncMock, tmp_path: Path
    ) -> StepExecutor:
        humanizer = Humanizer()
        waiter = Waiter()
        comparator = Comparator()
        return StepExecutor(
            mock_engine, mock_matcher, humanizer, waiter, comparator, tmp_path
        )

    async def test_navigate_step(
        self, executor: StepExecutor, mock_engine: AsyncMock
    ) -> None:
        step = StepConfig(
            step=1,
            action=ActionType.NAVIGATE,
            value="http://example.com",
            description="Navigate",
        )
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        mock_engine.navigate.assert_called_once_with("http://example.com")

    async def test_find_and_click_step(
        self, executor: StepExecutor, mock_engine: AsyncMock
    ) -> None:
        step = StepConfig(
            step=2,
            action=ActionType.FIND_AND_CLICK,
            target=TargetSpec(text="Login"),
            description="Click login",
        )
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED
        assert result.match_result is not None
        assert result.match_result.found is True

    async def test_find_and_type_step(
        self, executor: StepExecutor, mock_engine: AsyncMock
    ) -> None:
        step = StepConfig(
            step=3,
            action=ActionType.FIND_AND_TYPE,
            target=TargetSpec(text="Username"),
            value="admin",
            description="Type username",
        )
        result = await executor.execute_step(step)
        assert result.status == StepStatus.PASSED

    async def test_match_failure(
        self, executor: StepExecutor, mock_engine: AsyncMock, mock_matcher: AsyncMock
    ) -> None:
        mock_engine.find_text_position = AsyncMock(return_value=None)
        mock_matcher.find = AsyncMock(return_value=None)
        step = StepConfig(
            step=4,
            action=ActionType.FIND_AND_CLICK,
            target=TargetSpec(text="Nonexistent"),
            description="Click something missing",
        )
        result = await executor.execute_step(step)
        assert result.status in (StepStatus.FAILED, StepStatus.ERROR)

    async def test_multi_step_sequence(
        self, executor: StepExecutor, mock_engine: AsyncMock
    ) -> None:
        """Execute a sequence of steps like a real scenario."""
        steps = [
            StepConfig(
                step=1,
                action=ActionType.NAVIGATE,
                value="http://example.com",
                description="Navigate",
            ),
            StepConfig(
                step=2,
                action=ActionType.FIND_AND_CLICK,
                target=TargetSpec(text="Button"),
                description="Click button",
            ),
            StepConfig(
                step=3,
                action=ActionType.FIND_AND_TYPE,
                target=TargetSpec(text="Input"),
                value="hello",
                description="Type text",
            ),
            StepConfig(
                step=4,
                action=ActionType.SCREENSHOT,
                description="Take screenshot",
            ),
        ]
        results = []
        for step in steps:
            result = await executor.execute_step(step)
            results.append(result)

        assert all(r.status == StepStatus.PASSED for r in results)
        assert len(results) == 4


# ── DevQA Loop E2E ───────────────────────────────────────────────────────────


class TestDevQALoopE2E:
    """Test the full DevQA Loop with mocked external services."""

    def _make_passing_executor(self) -> AsyncMock:
        executor = AsyncMock()
        executor.execute_step = AsyncMock(
            return_value=StepResult(
                step=1,
                action=ActionType.NAVIGATE,
                status=StepStatus.PASSED,
                description="Navigate",
                elapsed_ms=50.0,
            )
        )
        return executor

    def _make_failing_executor(self, fail_count: int = 1) -> AsyncMock:
        """Create an executor that fails N times then succeeds."""
        call_count = 0

        async def _execute_step(step: StepConfig) -> StepResult:
            nonlocal call_count
            call_count += 1
            if call_count <= fail_count:
                return StepResult(
                    step=step.step,
                    action=step.action,
                    status=StepStatus.FAILED,
                    description=step.description,
                    error_message="Element not found",
                    elapsed_ms=100.0,
                )
            return StepResult(
                step=step.step,
                action=step.action,
                status=StepStatus.PASSED,
                description=step.description,
                elapsed_ms=50.0,
            )

        executor = AsyncMock()
        executor.execute_step = AsyncMock(side_effect=_execute_step)
        return executor

    def _make_mock_adapter(self) -> AsyncMock:
        adapter = AsyncMock()
        adapter.analyze_failure = AsyncMock(
            return_value=AnalysisResult(
                cause="Button not found",
                suggestion="Update selector",
                severity=Severity.WARNING,
            )
        )
        adapter.generate_fix = AsyncMock(
            return_value=FixResult(
                description="Updated selector",
                files_changed=[],
                confidence=0.8,
            )
        )
        return adapter

    def _make_mock_reporter(self) -> AsyncMock:
        reporter = AsyncMock()
        reporter.generate = AsyncMock(return_value=Path("reports/report.md"))
        return reporter

    def _make_scenarios(self) -> list[Scenario]:
        return [
            Scenario(
                id="SC-001",
                name="Login Test",
                steps=[
                    StepConfig(
                        step=1,
                        action=ActionType.NAVIGATE,
                        value="http://localhost/login",
                        description="Navigate",
                    ),
                ],
            )
        ]

    async def test_loop_all_pass_first_iteration(self) -> None:
        """If all tests pass on first run, loop ends with success."""
        config = Config(max_loops=3)
        engine = AsyncMock()
        executor = self._make_passing_executor()
        adapter = self._make_mock_adapter()
        reporter = self._make_mock_reporter()

        loop = DevQALoop(
            config=config,
            executor=executor,
            adapter=adapter,
            reporter=reporter,
            engine=engine,
        )
        result = await loop.run(self._make_scenarios())

        assert result.success is True
        assert result.total_iterations == 1
        adapter.analyze_failure.assert_not_called()

    async def test_loop_fail_then_pass(self) -> None:
        """Fail on first, pass on second iteration."""
        config = Config(max_loops=5)
        engine = AsyncMock()
        # Fail first step (iteration 1), then pass (iteration 2)
        executor = self._make_failing_executor(fail_count=1)
        adapter = self._make_mock_adapter()
        reporter = self._make_mock_reporter()

        loop = DevQALoop(
            config=config,
            executor=executor,
            adapter=adapter,
            reporter=reporter,
            engine=engine,
            approval_callback=lambda _: True,  # Auto-approve
        )
        result = await loop.run(self._make_scenarios())

        assert result.success is True
        assert result.total_iterations == 2
        adapter.analyze_failure.assert_called_once()

    async def test_loop_user_denies_fix(self) -> None:
        """If user denies the fix, loop stops."""
        config = Config(max_loops=5)
        engine = AsyncMock()
        executor = self._make_failing_executor(fail_count=999)
        adapter = self._make_mock_adapter()
        reporter = self._make_mock_reporter()

        loop = DevQALoop(
            config=config,
            executor=executor,
            adapter=adapter,
            reporter=reporter,
            engine=engine,
            approval_callback=lambda _: False,  # Deny fix
        )
        result = await loop.run(self._make_scenarios())

        assert result.success is False
        assert result.reason == "user denied fix"
        assert result.total_iterations == 1

    async def test_loop_max_iterations(self) -> None:
        """Loop should stop after max_loops iterations."""
        config = Config(max_loops=2)
        engine = AsyncMock()
        executor = self._make_failing_executor(fail_count=999)
        adapter = self._make_mock_adapter()
        reporter = self._make_mock_reporter()

        loop = DevQALoop(
            config=config,
            executor=executor,
            adapter=adapter,
            reporter=reporter,
            engine=engine,
            approval_callback=lambda _: True,
        )
        result = await loop.run(self._make_scenarios())

        assert result.success is False
        assert result.total_iterations == 2
        assert result.reason == "max loops exceeded"


# ── LearnedStore E2E ─────────────────────────────────────────────────────────


class TestLearnedStoreE2E:
    """Test LearnedStore CRUD + export/import as a workflow."""

    def test_full_workflow(self, tmp_path: Path) -> None:
        """save → find → increment → export → import to new DB."""
        from datetime import datetime

        from aat.core.models import LearnedElement

        store = LearnedStore(tmp_path / "test.db")
        try:
            # Save
            elem = LearnedElement(
                scenario_id="SC-001",
                step_number=1,
                target_name="login_btn",
                screenshot_hash="abcdef123456",
                correct_x=100,
                correct_y=200,
                cropped_image_path="/tmp/crop.png",
                confidence=0.95,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            saved = store.save(elem)
            assert saved.id is not None

            # Find by target
            found = store.find_by_target("SC-001", 1, "login_btn")
            assert found is not None
            assert found.correct_x == 100

            # Find by hash
            by_hash = store.find_by_hash("abcdef123456")
            assert len(by_hash) == 1

            # Increment use count
            store.increment_use_count(saved.id)
            store.increment_use_count(saved.id)
            updated = store.find_by_target("SC-001", 1, "login_btn")
            assert updated is not None
            assert updated.use_count == 2

            # Export
            export_path = tmp_path / "export.json"
            store.export_json(export_path)
            assert export_path.exists()

            # Import into a new store
            store2 = LearnedStore(tmp_path / "test2.db")
            try:
                count = store2.import_json(export_path)
                assert count == 1
                all_elems = store2.list_all()
                assert len(all_elems) == 1
                assert all_elems[0].target_name == "login_btn"
            finally:
                store2.close()

        finally:
            store.close()


# ── Error scenarios ──────────────────────────────────────────────────────────


class TestErrorScenarios:
    def test_invalid_yaml_syntax(self, tmp_path: Path) -> None:
        """Invalid YAML should fail validation."""
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text("{{invalid yaml\n  no: [good", encoding="utf-8")
        result = runner.invoke(app, ["validate", str(bad_file)])
        assert result.exit_code == 1

    def test_missing_required_fields(self, tmp_path: Path) -> None:
        """YAML missing required fields should fail."""
        incomplete = tmp_path / "incomplete.yaml"
        data = {"id": "SC-001", "name": "No Steps"}
        with open(incomplete, "w") as f:
            yaml.safe_dump(data, f)
        result = runner.invoke(app, ["validate", str(incomplete)])
        assert result.exit_code == 1

    def test_invalid_scenario_id_format(self, tmp_path: Path) -> None:
        """Scenario ID must match SC-NNN pattern."""
        bad_id = tmp_path / "bad_id.yaml"
        data = {
            "id": "INVALID",
            "name": "Bad ID",
            "steps": [
                {"step": 1, "action": "navigate", "value": "http://x.com", "description": "Nav"}
            ],
        }
        with open(bad_id, "w") as f:
            yaml.safe_dump(data, f)
        result = runner.invoke(app, ["validate", str(bad_id)])
        assert result.exit_code == 1

    def test_step_action_requires_target(self, tmp_path: Path) -> None:
        """find_and_click without target should fail."""
        no_target = tmp_path / "no_target.yaml"
        data = {
            "id": "SC-001",
            "name": "No Target",
            "steps": [
                {"step": 1, "action": "find_and_click", "description": "Click without target"}
            ],
        }
        with open(no_target, "w") as f:
            yaml.safe_dump(data, f)
        result = runner.invoke(app, ["validate", str(no_target)])
        assert result.exit_code == 1

    def test_run_nonexistent_scenarios(self) -> None:
        """aat run with nonexistent path should fail."""
        result = runner.invoke(app, ["run", "/nonexistent/scenarios"])
        assert result.exit_code == 1

    def test_generate_without_file(self) -> None:
        """aat generate without --from should fail."""
        result = runner.invoke(app, ["generate"])
        assert result.exit_code == 1


# ── Config E2E ───────────────────────────────────────────────────────────────


class TestConfigE2E:
    def test_config_show(self, project_dir: Path) -> None:
        result = runner.invoke(
            app, ["config", "show", "--config", str(project_dir / "aat.config.yaml")]
        )
        assert result.exit_code == 0
        assert "e2e-test" in result.output

    def test_config_roundtrip(self, tmp_path: Path) -> None:
        """Save config, load it back, verify values."""
        config = Config(
            project_name="roundtrip-test",
            url="http://test.example.com",
            max_loops=5,
        )
        path = tmp_path / "config.yaml"
        save_config(config, path)

        from aat.core.config import load_config

        loaded = load_config(config_path=path)
        assert loaded.project_name == "roundtrip-test"
        assert loaded.url == "http://test.example.com"
        assert loaded.max_loops == 5


# ── MarkdownParser E2E ───────────────────────────────────────────────────────


class TestMarkdownParserE2E:
    async def test_parse_markdown_with_images(self, tmp_path: Path) -> None:
        """Parse markdown that references images."""
        from aat.parsers.markdown_parser import MarkdownParser

        # Create a small test image (1x1 PNG)
        img_data = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        img_path = tmp_path / "screenshot.png"
        img_path.write_bytes(img_data)

        md_path = tmp_path / "spec.md"
        md_path.write_text(
            "# Test Spec\n\nClick the login button.\n\n"
            "![screenshot](screenshot.png)\n\nDone.\n",
            encoding="utf-8",
        )

        parser = MarkdownParser()
        text, images = await parser.parse(md_path)

        assert "Test Spec" in text
        assert "login button" in text
        assert len(images) == 1
        assert images[0] == img_data

    async def test_parse_txt_no_images(self, tmp_path: Path) -> None:
        """Parsing .txt skips image extraction."""
        from aat.parsers.markdown_parser import MarkdownParser

        txt_path = tmp_path / "spec.txt"
        txt_path.write_text("Plain text spec content.", encoding="utf-8")

        parser = MarkdownParser()
        text, images = await parser.parse(txt_path)

        assert text == "Plain text spec content."
        assert images == []
