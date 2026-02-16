"""Tests for versioned API (POST/GET /api/v1/tests)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Test, TestStatus


@pytest.mark.asyncio
async def test_v1_create_test(client: AsyncClient) -> None:
    """POST /api/v1/tests creates a test (201)."""
    resp = await client.post(
        "/api/v1/tests",
        json={"target_url": "https://example.com", "mode": "auto"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "queued"
    assert data["target_url"] == "https://example.com/"


@pytest.mark.asyncio
async def test_v1_get_test(client: AsyncClient) -> None:
    """GET /api/v1/tests/{id} returns test status."""
    create_resp = await client.post(
        "/api/v1/tests",
        json={"target_url": "https://example.com", "mode": "auto"},
    )
    test_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/tests/{test_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == test_id


@pytest.mark.asyncio
async def test_v1_get_test_not_found(client: AsyncClient) -> None:
    """GET /api/v1/tests/{id} returns 404 for nonexistent test."""
    resp = await client.get("/api/v1/tests/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_v1_wait_timeout(client: AsyncClient, monkeypatch) -> None:
    """POST /api/v1/tests?wait=true returns 408 on timeout."""
    from app import config

    # Set very short timeout for test
    monkeypatch.setattr(config.settings, "api_timeout", 1)

    resp = await client.post(
        "/api/v1/tests?wait=true",
        json={"target_url": "https://example.com", "mode": "auto"},
    )
    assert resp.status_code == 408
    assert "timeout" in resp.json()["detail"].lower()
