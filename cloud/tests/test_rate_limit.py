"""Tests for rate limiting middleware."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_free_user_within_limit(client: AsyncClient) -> None:
    """Free user can create tests within monthly limit."""
    for i in range(5):
        resp = await client.post(
            "/api/tests",
            json={"target_url": f"https://test{i}.com"},
        )
        assert resp.status_code == 201

    # Check rate limit headers on last response
    assert resp.headers.get("X-RateLimit-Limit") == "5"
    assert resp.headers.get("X-RateLimit-Remaining") == "0"


@pytest.mark.asyncio
async def test_free_user_exceeds_limit(client: AsyncClient) -> None:
    """Free user gets 429 after exceeding monthly limit."""
    # Use up the 5 free tests
    for i in range(5):
        resp = await client.post(
            "/api/tests",
            json={"target_url": f"https://test{i}.com"},
        )
        assert resp.status_code == 201

    # 6th request should fail
    resp = await client.post(
        "/api/tests",
        json={"target_url": "https://blocked.com"},
    )
    assert resp.status_code == 429
    assert "limit" in resp.json()["detail"].lower()
    assert resp.headers.get("X-RateLimit-Remaining") == "0"


@pytest.mark.asyncio
async def test_pro_user_no_limit(pro_client: AsyncClient) -> None:
    """Pro user has unlimited test creation."""
    for i in range(10):
        resp = await pro_client.post(
            "/api/tests",
            json={"target_url": f"https://pro{i}.com"},
        )
        assert resp.status_code == 201


@pytest.mark.asyncio
async def test_get_requests_not_rate_limited(client: AsyncClient) -> None:
    """GET requests are not affected by rate limiting."""
    # Even after creating 5 tests
    for i in range(5):
        await client.post(
            "/api/tests",
            json={"target_url": f"https://test{i}.com"},
        )

    # GET should still work
    resp = await client.get("/api/tests")
    assert resp.status_code == 200
