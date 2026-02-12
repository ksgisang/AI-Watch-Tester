"""Tests for the FastAPI dashboard app."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi")

if TYPE_CHECKING:
    from pathlib import Path

from fastapi.testclient import TestClient

from aat.dashboard.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create a test client with a temporary config."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("project_name: test-project\n", encoding="utf-8")
    app = create_app(config_path=config_path)
    return TestClient(app)


class TestDashboardApp:
    """FastAPI dashboard app test suite."""

    def test_index_serves_html(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "AAT Dashboard" in response.text

    def test_get_config(self, client: TestClient) -> None:
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert "engine" in data
        assert "ai" in data

    def test_config_masks_api_key(self, client: TestClient) -> None:
        response = client.get("/api/config")
        data = response.json()
        assert data["ai"]["api_key"] == ""

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
