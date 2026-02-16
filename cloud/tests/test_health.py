"""Health check endpoint tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_health() -> None:
    """GET /health returns ok without auth."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
