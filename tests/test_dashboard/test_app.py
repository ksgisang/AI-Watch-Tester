"""Tests for the FastAPI dashboard app."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi")

if TYPE_CHECKING:
    from pathlib import Path

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from aat.dashboard.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create a test client with a temporary config."""
    config_path = tmp_path / "config.yaml"
    config_text = "project_name: test-project\nai:\n  api_key: test-key-12345\n"
    config_path.write_text(config_text, encoding="utf-8")
    app = create_app(config_path=config_path)
    return TestClient(app)


class TestDashboardApp:
    """FastAPI dashboard app test suite."""

    def test_index_serves_html(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "AAT" in response.text

    def test_get_config(self, client: TestClient) -> None:
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert "engine" in data
        assert "ai" in data

    def test_config_masks_api_key(self, client: TestClient) -> None:
        response = client.get("/api/config")
        data = response.json()
        assert data["ai"]["api_key"] == "test-key..."

    def test_list_scenarios_empty(self, client: TestClient) -> None:
        response = client.get("/api/scenarios")
        assert response.status_code == 200
        data = response.json()
        assert "scenarios" in data

    def test_stop_when_nothing_running(self, client: TestClient) -> None:
        response = client.post("/api/stop")
        assert response.status_code == 200
        assert response.json()["status"] == "stopped"

    def test_get_status(self, client: TestClient) -> None:
        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert "running" in data
        assert "ws_clients" in data
        assert "server_running" in data

    def test_get_logs(self, client: TestClient) -> None:
        response = client.get("/api/logs")
        assert response.status_code == 200
        data = response.json()
        assert "logs" in data
        assert isinstance(data["logs"], list)

    def test_screenshot_not_found(self, client: TestClient) -> None:
        response = client.get("/api/screenshots/nonexistent.png")
        assert response.status_code == 404

    def test_update_config(self, client: TestClient) -> None:
        response = client.put(
            "/api/config",
            json={"project_name": "updated-project"},
        )
        assert response.status_code == 200

    def test_update_config_invalid_json(self, client: TestClient) -> None:
        response = client.put(
            "/api/config",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 400

    def test_websocket_connection(self, client: TestClient) -> None:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"

    def test_websocket_prompt_response(self, client: TestClient) -> None:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "prompt_response", "response": "approve"})
            ws.send_json({"type": "ping"})
            data = ws.receive_json()
            assert data["type"] == "pong"


class TestServerControl:
    """Server control endpoint tests."""

    def test_server_status_initially_idle(self, client: TestClient) -> None:
        response = client.get("/api/server/status")
        assert response.status_code == 200
        data = response.json()
        assert data["running"] is False
        assert data["status"] == "idle"
        assert data["pid"] is None

    def test_server_start_no_command(self, client: TestClient) -> None:
        response = client.post("/api/server/start", json={"command": ""})
        assert response.status_code == 400
        assert "No command" in response.json()["error"]

    def test_server_start_invalid_json(self, client: TestClient) -> None:
        response = client.post(
            "/api/server/start",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 400

    def test_server_stop_when_not_running(self, client: TestClient) -> None:
        response = client.post("/api/server/stop")
        assert response.status_code == 200
        assert response.json()["status"] == "not_running"

    def test_server_logs_empty(self, client: TestClient) -> None:
        response = client.get("/api/server/logs")
        assert response.status_code == 200
        data = response.json()
        assert "lines" in data
        assert isinstance(data["lines"], list)


class TestPortExtraction:
    """Test _extract_port helper."""

    def test_extract_port_flag(self) -> None:
        from aat.dashboard.app import _extract_port

        assert _extract_port("npm run dev --port 3000") == 3000

    def test_extract_port_short_flag(self) -> None:
        from aat.dashboard.app import _extract_port

        assert _extract_port("python -m http.server -p 8080") == 8080

    def test_extract_port_colon(self) -> None:
        from aat.dashboard.app import _extract_port

        assert _extract_port("uvicorn app:main --host 0.0.0.0:8000") == 8000

    def test_extract_port_env(self) -> None:
        from aat.dashboard.app import _extract_port

        assert _extract_port("PORT=5000 flask run") == 5000

    def test_extract_port_none(self) -> None:
        from aat.dashboard.app import _extract_port

        assert _extract_port("ls -la") is None


class TestDocuments:
    """Document upload/list endpoint tests."""

    def test_list_documents_empty(self, client: TestClient) -> None:
        response = client.get("/api/documents")
        assert response.status_code == 200
        data = response.json()
        assert "documents" in data
        assert isinstance(data["documents"], list)

    def test_upload_no_files(self, client: TestClient) -> None:
        response = client.post("/api/documents/upload", files=[])
        assert response.status_code == 400

    def test_upload_single_file(self, client: TestClient) -> None:
        response = client.post(
            "/api/documents/upload",
            files=[("files", ("test.md", b"# Hello\n", "text/markdown"))],
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "test.md" in data["uploaded"]
        assert data["count"] == 1
        assert "contents" in data
        assert data["contents"]["test.md"] == "# Hello\n"

    def test_upload_multiple_files(self, client: TestClient) -> None:
        response = client.post(
            "/api/documents/upload",
            files=[
                ("files", ("a.md", b"# A\n", "text/markdown")),
                ("files", ("b.txt", b"hello\n", "text/plain")),
            ],
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        assert data["contents"]["a.md"] == "# A\n"
        assert data["contents"]["b.txt"] == "hello\n"

    def test_upload_then_list(self, client: TestClient) -> None:
        client.post(
            "/api/documents/upload",
            files=[("files", ("doc.md", b"content\n", "text/markdown"))],
        )
        response = client.get("/api/documents")
        assert response.status_code == 200
        data = response.json()
        names = [d["name"] for d in data["documents"]]
        assert "doc.md" in names


class TestScenarioManagement:
    """Scenario management endpoint tests."""

    def test_list_scenarios_with_custom_path(self, client: TestClient) -> None:
        """Custom path query param is accepted (may return empty if dir missing)."""
        response = client.get("/api/scenarios?path=custom/nonexistent")
        assert response.status_code == 200
        data = response.json()
        assert "scenarios" in data
        assert data["scenarios"] == []

    def test_upload_scenario_yaml(self, tmp_path: Path, client: TestClient) -> None:
        """Upload a .yaml scenario file succeeds."""
        yaml_content = b"id: SC-001\nname: Test\nsteps:\n  - action: navigate\n    url: http://x\n"
        response = client.post(
            "/api/scenarios/upload",
            files=[("file", ("test_scenario.yaml", yaml_content, "application/yaml"))],
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["uploaded"] == "test_scenario.yaml"

    def test_upload_scenario_yml(self, client: TestClient) -> None:
        """Upload a .yml scenario file succeeds."""
        yaml_content = (
            b"id: SC-002\nname: Test2\nsteps:\n  - action: navigate\n    url: http://x\n"
        )
        response = client.post(
            "/api/scenarios/upload",
            files=[("file", ("test.yml", yaml_content, "application/yaml"))],
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_upload_scenario_non_yaml_rejected(self, client: TestClient) -> None:
        """Non-YAML file upload is rejected."""
        response = client.post(
            "/api/scenarios/upload",
            files=[("file", ("test.txt", b"not yaml", "text/plain"))],
        )
        assert response.status_code == 400
        assert "Only .yaml/.yml" in response.json()["error"]

    def test_upload_scenario_no_file(self, client: TestClient) -> None:
        """Upload with no file returns error."""
        response = client.post("/api/scenarios/upload", files=[])
        assert response.status_code == 400

    def test_start_run_with_scenario_ids(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /api/run accepts scenario_ids parameter."""
        import aat.dashboard.app as app_mod

        async def _noop_run(*_args: object, **_kwargs: object) -> None:
            pass

        monkeypatch.setattr(app_mod, "_execute_run", _noop_run)

        response = client.post(
            "/api/run",
            json={"scenario_ids": ["SC-001", "SC-002"]},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "started"
        # Clean up
        client.post("/api/stop")

    def test_start_loop_with_scenario_ids(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /api/loop accepts scenario_ids parameter."""
        import aat.dashboard.app as app_mod

        async def _noop_loop(*_args: object, **_kwargs: object) -> None:
            pass

        monkeypatch.setattr(app_mod, "_execute_loop", _noop_loop)

        response = client.post(
            "/api/loop",
            json={"approval_mode": "manual", "scenario_ids": ["SC-001"]},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "started"
        # Clean up
        client.post("/api/stop")


class TestScenarioGeneration:
    """Test AI scenario generation endpoint."""

    def test_generate_empty_document(self, client: TestClient) -> None:
        response = client.post(
            "/api/scenarios/generate",
            json={"document_text": ""},
        )
        assert response.status_code == 400
        assert "비어있습니다" in response.json()["error"]

    def test_generate_no_document(self, client: TestClient) -> None:
        response = client.post(
            "/api/scenarios/generate",
            json={},
        )
        assert response.status_code == 400
        assert "비어있습니다" in response.json()["error"]

    def test_generate_success(self, client: TestClient) -> None:
        from aat.core.models import Scenario, StepConfig

        mock_scenario = Scenario(
            id="SC-001",
            name="Test Login",
            description="Login test",
            tags=["auth"],
            steps=[
                StepConfig(
                    step=1,
                    action="navigate",
                    value="{{url}}/login",
                    description="Go to login",
                ),
            ],
        )

        mock_adapter = MagicMock()
        mock_adapter.generate_scenarios = AsyncMock(return_value=[mock_scenario])

        mock_registry = {"claude": MagicMock(return_value=mock_adapter)}

        with patch("aat.adapters.ADAPTER_REGISTRY", mock_registry):
            response = client.post(
                "/api/scenarios/generate",
                json={"document_text": "Login page with email and password"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["count"] == 1
        assert len(data["files"]) == 1
        assert data["scenarios"][0]["id"] == "SC-001"
        assert data["scenarios"][0]["steps_count"] == 1
        assert "scenarios_path" in data

    def test_generate_ai_failure(self, client: TestClient) -> None:
        mock_adapter_cls = MagicMock()
        mock_adapter_cls.return_value.generate_scenarios = AsyncMock(
            side_effect=Exception("API error"),
        )
        mock_registry = {"claude": mock_adapter_cls}

        with patch("aat.adapters.ADAPTER_REGISTRY", mock_registry):
            response = client.post(
                "/api/scenarios/generate",
                json={"document_text": "Some spec document"},
            )

        assert response.status_code == 500
        assert "생성 실패" in response.json()["error"]


class TestScenarioGuidance:
    """Tests for _get_scenario_guidance helper."""

    def test_missing_step_field(self) -> None:
        from aat.dashboard.app import _get_scenario_guidance

        result = _get_scenario_guidance("step\nField required")
        assert "step" in result
        assert "번호" in result

    def test_invalid_action_name(self) -> None:
        from aat.dashboard.app import _get_scenario_guidance

        result = _get_scenario_guidance("Input should be 'click' action invalid")
        assert "find_and_click" in result

    def test_target_role_hint(self) -> None:
        from aat.dashboard.app import _get_scenario_guidance

        result = _get_scenario_guidance("target field: role not allowed")
        assert "text" in result

    def test_assert_hint(self) -> None:
        from aat.dashboard.app import _get_scenario_guidance

        result = _get_scenario_guidance("assert_type field required, expected missing")
        assert "assert_type" in result
        assert "expected" in result

    def test_fallback_hint(self) -> None:
        from aat.dashboard.app import _get_scenario_guidance

        result = _get_scenario_guidance("some unknown error")
        assert "형식" in result


class TestOneClick:
    """One-click test endpoint tests."""

    def test_oneclick_no_url(self, client: TestClient) -> None:
        """POST /api/oneclick with empty URL returns error."""
        response = client.post("/api/oneclick", json={"url": ""})
        assert response.status_code == 400
        assert "URL is required" in response.json()["error"]

    def test_oneclick_no_body(self, client: TestClient) -> None:
        """POST /api/oneclick with no body returns error."""
        response = client.post(
            "/api/oneclick",
            content=b"",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 400

    def test_oneclick_starts_successfully(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /api/oneclick with valid URL starts execution."""
        import aat.dashboard.app as app_mod

        async def _noop_oneclick(*_args: object, **_kwargs: object) -> None:
            pass

        monkeypatch.setattr(app_mod, "_execute_oneclick", _noop_oneclick)

        response = client.post(
            "/api/oneclick",
            json={"url": "https://example.com"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "started"
        assert data["url"] == "https://example.com"
        # Clean up
        client.post("/api/stop")

    def test_oneclick_conflict_when_running(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """POST /api/oneclick returns 409 if test already running."""
        import aat.dashboard.app as app_mod

        # Simulate a running task with a mock that reports not done
        fake_task = MagicMock()
        fake_task.done.return_value = False
        monkeypatch.setattr(app_mod, "_run_task", fake_task)

        response = client.post("/api/oneclick", json={"url": "https://other.com"})
        assert response.status_code == 409


class TestAutoDetectAI:
    """AI provider auto-detection tests."""

    def test_auto_detect_anthropic_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Auto-detects ANTHROPIC_API_KEY from env."""
        from aat.core.models import Config
        from aat.dashboard.app import _auto_detect_ai

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test123")
        config = Config()
        result = _auto_detect_ai(config)
        assert result.ai.provider == "claude"
        assert result.ai.api_key == "sk-ant-test123"

    def test_auto_detect_openai_key(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Auto-detects OPENAI_API_KEY from env."""
        from aat.core.models import Config
        from aat.dashboard.app import _auto_detect_ai

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test123")
        config = Config()
        result = _auto_detect_ai(config)
        assert result.ai.provider == "openai"
        assert result.ai.api_key == "sk-openai-test123"

    def test_auto_detect_skips_when_key_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Does not override if API key already set."""
        from aat.core.models import Config
        from aat.dashboard.app import _auto_detect_ai

        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test123")
        config = Config()
        config.ai.api_key = "existing-key"
        config.ai.provider = "claude"
        result = _auto_detect_ai(config)
        assert result.ai.provider == "claude"
        assert result.ai.api_key == "existing-key"

    def test_auto_detect_ollama(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Auto-detects OLLAMA_HOST from env."""
        from aat.core.models import Config
        from aat.dashboard.app import _auto_detect_ai

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
        config = Config()
        result = _auto_detect_ai(config)
        assert result.ai.provider == "ollama"
        assert result.ai.model == "codellama:7b"


class TestBuildVariables:
    """Test _build_variables helper with url_override."""

    def test_url_override(self, client: TestClient) -> None:
        """url_override takes precedence over config URL."""
        from aat.dashboard.app import _build_variables

        variables = _build_variables(url_override="https://override.com")
        assert variables["url"] == "https://override.com"

    def test_url_from_config(self, client: TestClient) -> None:
        """Falls back to config URL when no override."""
        from aat.dashboard.app import _build_variables

        variables = _build_variables()
        assert "project_name" in variables


class TestTheDashboardSaysWhatTheTerminalSays:
    """Two registers reading one set of facts, not two accounts of one run.

    A browser and a terminal driving the same loop reported it differently.
    The terminal named the files that were written, the proposed changes
    validation refused, and how to undo them (AAT-122); the browser said
    "Loop ended after 3 iteration(s)". The terminal stopped counting a pass
    that came after the scenario broke (AAT-123); the browser went on
    counting it.

    The payload is assembled by a function rather than inline in the
    WebSocket handler so that these can be read without a browser, an
    engine or an AI adapter.
    """

    @staticmethod
    def _result(
        statuses: list[str],
        *,
        success: bool = False,
        applied: list[str] | None = None,
        iterations: int = 1,
    ) -> object:
        from aat.core.models import LoopIteration, LoopResult, StepResult, TestResult

        steps = [
            StepResult(
                step=i + 1,
                action="find_and_click",
                description=f"Step {i + 1}",
                status=status,
                elapsed_ms=1,
            )
            for i, status in enumerate(statuses)
        ]
        test_result = TestResult(
            scenario_id="SC-901",
            scenario_name="signup",
            passed=success,
            steps=steps,
            total_steps=len(steps),
            passed_steps=sum(1 for s in steps if s.status.value == "passed"),
            failed_steps=sum(1 for s in steps if s.status.value == "failed"),
            duration_ms=10.0,
        )
        return LoopResult(
            success=success,
            total_iterations=iterations,
            iterations=[
                LoopIteration(
                    iteration=n + 1,
                    test_result=test_result,
                    applied_paths=list(applied or []),
                )
                for n in range(iterations)
            ],
            reason="max loops exceeded",
            duration_ms=20.0,
        )

    def test_unverified_steps_reach_the_browser(self) -> None:
        from aat.dashboard.app import _loop_tally

        result = self._result(["passed", "failed", "unverified", "unverified"])

        assert _loop_tally(result) == {"passed": 1, "failed": 1, "unverified": 2}

    def test_the_tally_describes_the_attempt_the_run_ended_on(self) -> None:
        from aat.core.models import StepResult, TestResult
        from aat.dashboard.app import _loop_tally

        result = self._result(["failed"], iterations=2)
        # The second attempt went green; the first is how it got there.
        result.iterations[-1].test_result = TestResult(
            scenario_id="SC-901",
            scenario_name="signup",
            passed=True,
            steps=[
                StepResult(
                    step=1,
                    action="find_and_click",
                    description="Step 1",
                    status="passed",
                    elapsed_ms=1,
                )
            ],
            total_steps=1,
            passed_steps=1,
            failed_steps=0,
            duration_ms=10.0,
        )

        assert _loop_tally(result) == {"passed": 1}

    def test_a_loop_with_no_iterations_tallies_nothing(self) -> None:
        from aat.core.models import LoopResult
        from aat.dashboard.app import _loop_tally

        empty = LoopResult(success=False, total_iterations=0, iterations=[], duration_ms=0.0)

        assert _loop_tally(empty) == {}

    def test_the_tally_is_actually_in_the_message(self) -> None:
        """Counting correctly and sending the count are two repairs.

        Found by mutation: replacing the payload's tally with an empty
        dict left every test above green, because they all call
        `_loop_tally` themselves. That proves the counter counts; it says
        nothing about the browser ever being told -- and being told is the
        entire B-4 item, since the terminal already knew.
        """
        from aat.core.models import ApprovalMode
        from aat.dashboard.app import _loop_complete_payload

        payload = _loop_complete_payload(
            self._result(["passed", "failed", "unverified"]),
            ApprovalMode.AUTO,
            "reports",
        )

        assert payload["tally"] == {"passed": 1, "failed": 1, "unverified": 1}, (
            "the page is being handed a different set of facts from the terminal"
        )

    def test_the_plain_verdict_is_sent(self) -> None:
        from aat.core.models import ApprovalMode
        from aat.dashboard.app import _loop_complete_payload

        payload = _loop_complete_payload(
            self._result(["failed"], applied=["src/app.py"]),
            ApprovalMode.AUTO,
            "reports",
        )
        plain = "\n".join(payload["verdict"]["plain"])

        assert "a person needs to look at this" in plain
        assert "src/app.py" in plain
        # The undo line is the part that is dangerous to get wrong, and the
        # one a terminal user had and a browser user did not.
        assert "git checkout --" in plain

    def test_the_developer_register_is_sent_alongside_it(self) -> None:
        from aat.core.models import ApprovalMode
        from aat.dashboard.app import _loop_complete_payload

        payload = _loop_complete_payload(
            self._result(["failed"], iterations=3),
            ApprovalMode.MANUAL,
            "reports",
        )
        developer = "\n".join(payload["verdict"]["developer"])

        assert "after 3 iteration(s)" in developer
        assert "mode=manual" in developer

    def test_the_undo_line_is_the_one_for_this_mode(self) -> None:
        from aat.core.models import ApprovalMode
        from aat.dashboard.app import _loop_complete_payload

        # `branch` leaves the edits on a branch, not in the working copy, so
        # `git checkout -- <path>` there would throw away the user's own
        # uncommitted work and change nothing AWT wrote.
        payload = _loop_complete_payload(
            self._result(["failed"], applied=["src/app.py"]),
            ApprovalMode.BRANCH,
            "reports",
        )
        plain = "\n".join(payload["verdict"]["plain"])

        assert "git checkout --" not in plain

    def test_the_old_fields_are_still_there(self) -> None:
        # Additive: whatever the page already reads must keep arriving.
        from aat.core.models import ApprovalMode
        from aat.dashboard.app import _loop_complete_payload

        payload = _loop_complete_payload(self._result(["failed"]), ApprovalMode.AUTO, "reports")

        assert payload["type"] == "loop_complete"
        assert payload["success"] is False
        assert payload["iterations"] == 1
        assert payload["reason"] == "max loops exceeded"
        assert payload["duration_ms"] == 20.0


class TestTheDashboardRunnerAppliesTheSharedRule:
    """The browser's own runner never demoted a post-failure pass.

    ``_execute_loop`` goes through ``core.loop``, which applies the rule;
    ``_execute_run`` and the one-click path call the executor directly and
    did not, so the dashboard kept reporting the inflated tally that AAT-123
    removed from the terminal. These read the source: both paths need a
    browser and an engine to run, and the defect was an omission, so the
    call site is what gets checked.
    """

    @staticmethod
    def _source() -> str:
        from pathlib import Path

        import aat.dashboard.app as mod

        return Path(mod.__file__).read_text(encoding="utf-8")

    def test_every_executor_call_in_the_dashboard_is_demoted(self) -> None:
        source = self._source()
        direct_calls = source.count("await executor.execute_step(")

        assert direct_calls == 2
        assert source.count("demote_if_flow_broken(raw, broke_at)") == direct_calls

    def test_nothing_counts_statuses_by_hand(self) -> None:
        # A hand-rolled `if passed: n += 1 else: m += 1` is how UNVERIFIED
        # disappeared from this file in the first place.
        source = self._source()

        assert "passed_count += 1" not in source
        assert "failed_count += 1" not in source
        assert source.count("tally_statuses(") >= 2
