"""Tests for POST/GET /api/tests endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_test(client: AsyncClient) -> None:
    """POST /api/tests creates a queued test."""
    resp = await client.post(
        "/api/tests",
        json={"target_url": "https://example.com"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["target_url"] == "https://example.com/"
    assert data["status"] == "queued"
    assert data["user_id"] == "test-uid-001"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_test_invalid_url(client: AsyncClient) -> None:
    """POST /api/tests with invalid URL returns 422."""
    resp = await client.post(
        "/api/tests",
        json={"target_url": "not-a-url"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_test_no_body(client: AsyncClient) -> None:
    """POST /api/tests with no body returns 422."""
    resp = await client.post("/api/tests")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_tests_empty(client: AsyncClient) -> None:
    """GET /api/tests returns empty list initially."""
    resp = await client.get("/api/tests")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tests"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_tests_after_create(client: AsyncClient) -> None:
    """GET /api/tests returns created tests."""
    await client.post("/api/tests", json={"target_url": "https://a.com"})
    await client.post("/api/tests", json={"target_url": "https://b.com"})

    resp = await client.get("/api/tests")
    data = resp.json()
    assert data["total"] == 2
    assert len(data["tests"]) == 2
    # Newest first
    assert data["tests"][0]["target_url"] == "https://b.com/"


@pytest.mark.asyncio
async def test_list_tests_pagination(client: AsyncClient) -> None:
    """GET /api/tests supports pagination."""
    for i in range(3):
        await client.post("/api/tests", json={"target_url": f"https://{i}.com"})

    resp = await client.get("/api/tests", params={"page": 1, "page_size": 2})
    data = resp.json()
    assert data["total"] == 3
    assert len(data["tests"]) == 2
    assert data["page"] == 1

    resp2 = await client.get("/api/tests", params={"page": 2, "page_size": 2})
    data2 = resp2.json()
    assert len(data2["tests"]) == 1


@pytest.mark.asyncio
async def test_get_test_by_id(client: AsyncClient) -> None:
    """GET /api/tests/{id} returns a single test."""
    create_resp = await client.post(
        "/api/tests",
        json={"target_url": "https://example.com"},
    )
    test_id = create_resp.json()["id"]

    resp = await client.get(f"/api/tests/{test_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == test_id


@pytest.mark.asyncio
async def test_get_test_not_found(client: AsyncClient) -> None:
    """GET /api/tests/{id} returns 404 for nonexistent test."""
    resp = await client.get("/api/tests/99999")
    assert resp.status_code == 404
