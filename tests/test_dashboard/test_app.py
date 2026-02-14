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
        assert "subprocess" in data
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
        yaml_content = b"id: SC-002\nname: Test2\nsteps:\n  - action: navigate\n    url: http://x\n"
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
