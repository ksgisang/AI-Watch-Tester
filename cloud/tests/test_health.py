"""Health check endpoint tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_health_simple() -> None:
    """GET /health returns ok without auth."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_detailed() -> None:
    """GET /api/health returns detailed status."""
    from app.main import app

    mock_result = {
        "status": "healthy",
        "checks": {
            "database": {"status": "up"},
            "worker": {"status": "up", "active_tests": 0, "max_concurrent": 2},
            "ai_provider": {"status": "up", "provider": "ollama", "models_available": 3},
        },
        "uptime_seconds": 42.0,
    }

    with patch("app.health.get_health", new_callable=AsyncMock, return_value=mock_result):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "checks" in data
    assert "uptime_seconds" in data
    assert data["checks"]["database"]["status"] == "up"
    assert data["checks"]["worker"]["status"] == "up"
    assert data["checks"]["ai_provider"]["status"] == "up"
