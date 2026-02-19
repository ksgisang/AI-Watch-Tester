"""Tests for 3-tier rate limits and concurrent limits."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_pro_user_within_monthly_limit(
    pro_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pro user can create tests within monthly limit."""
    from app import config

    monkeypatch.setattr(config.settings, "rate_limit_pro", 3)

    for i in range(3):
        resp = await pro_client.post(
            "/api/tests",
            json={"target_url": f"https://pro{i}.com"},
        )
        assert resp.status_code == 201


@pytest.mark.asyncio
async def test_pro_user_exceeds_monthly_limit(
    pro_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pro user gets 429 when monthly limit is exceeded."""
    from app import config

    monkeypatch.setattr(config.settings, "rate_limit_pro", 2)

    for i in range(2):
        resp = await pro_client.post(
            "/api/tests",
            json={"target_url": f"https://pro{i}.com"},
        )
        assert resp.status_code == 201

    resp = await pro_client.post(
        "/api/tests",
        json={"target_url": "https://blocked.com"},
    )
    assert resp.status_code == 429
    assert "limit" in resp.json()["detail"].lower()
