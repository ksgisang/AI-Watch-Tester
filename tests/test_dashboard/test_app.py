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
