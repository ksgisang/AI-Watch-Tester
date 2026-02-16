"""Tests for Pro user daily limit."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_pro_daily_limit_within(pro_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pro user can create tests within daily limit."""
    from app import config

    monkeypatch.setattr(config.settings, "daily_limit_pro", 3)

    for i in range(3):
        resp = await pro_client.post(
            "/api/tests",
            json={"target_url": f"https://daily{i}.com"},
        )
        assert resp.status_code == 201


@pytest.mark.asyncio
async def test_pro_daily_limit_exceeded(pro_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pro user gets 429 when daily limit is exceeded."""
    from app import config

    monkeypatch.setattr(config.settings, "daily_limit_pro", 2)

    # Use up the 2 daily tests
    for i in range(2):
        resp = await pro_client.post(
            "/api/tests",
            json={"target_url": f"https://daily{i}.com"},
        )
        assert resp.status_code == 201

    # 3rd should fail
    resp = await pro_client.post(
        "/api/tests",
        json={"target_url": "https://blocked.com"},
    )
    assert resp.status_code == 429
    assert "daily" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_pro_daily_limit_disabled(pro_client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pro user is not limited when daily_limit_pro = -1."""
    from app import config

    monkeypatch.setattr(config.settings, "daily_limit_pro", -1)

    for i in range(10):
        resp = await pro_client.post(
            "/api/tests",
            json={"target_url": f"https://unlimited{i}.com"},
        )
        assert resp.status_code == 201


@pytest.mark.asyncio
async def test_free_user_not_affected_by_daily_limit(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Free user's monthly limit is separate from Pro daily limit."""
    from app import config

    monkeypatch.setattr(config.settings, "daily_limit_pro", 1)

    # Free user should still use monthly limit, not daily
    for i in range(5):
        resp = await client.post(
            "/api/tests",
            json={"target_url": f"https://free{i}.com"},
        )
        assert resp.status_code == 201
