"""Tests for new model fields (Gate 2-B schema additions)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_test_has_new_fields(client: AsyncClient) -> None:
    """POST /api/tests response includes Gate 2-B fields."""
    resp = await client.post(
        "/api/tests",
        json={"target_url": "https://example.com"},
    )
    assert resp.status_code == 201
    data = resp.json()

    # New fields should be present with default values
    assert data["scenario_yaml"] is None
    assert data["error_message"] is None
    assert data["steps_total"] == 0
    assert data["steps_completed"] == 0


@pytest.mark.asyncio
async def test_get_test_has_new_fields(client: AsyncClient) -> None:
    """GET /api/tests/{id} response includes Gate 2-B fields."""
    create_resp = await client.post(
        "/api/tests",
        json={"target_url": "https://example.com"},
    )
    test_id = create_resp.json()["id"]

    resp = await client.get(f"/api/tests/{test_id}")
    assert resp.status_code == 200
    data = resp.json()

    assert "scenario_yaml" in data
    assert "error_message" in data
    assert "steps_total" in data
    assert "steps_completed" in data


@pytest.mark.asyncio
async def test_list_tests_has_new_fields(client: AsyncClient) -> None:
    """GET /api/tests list items include Gate 2-B fields."""
    await client.post(
        "/api/tests",
        json={"target_url": "https://example.com"},
    )

    resp = await client.get("/api/tests")
    assert resp.status_code == 200
    tests = resp.json()["tests"]
    assert len(tests) == 1

    test = tests[0]
    assert "scenario_yaml" in test
    assert "error_message" in test
    assert "steps_total" in test
    assert "steps_completed" in test
