"""Tests for API key CRUD endpoints (POST/GET/DELETE /api/keys)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_free_user_cannot_create_api_key(client: AsyncClient) -> None:
    """Free user gets 403 when trying to create an API key."""
    resp = await client.post("/api/keys", json={"name": "CI key"})
    assert resp.status_code == 403
    assert "pro" in resp.json()["detail"].lower() or "team" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_api_key(pro_client: AsyncClient) -> None:
    """POST /api/keys creates a key with awt_ prefix and 36 chars."""
    resp = await pro_client.post("/api/keys", json={"name": "CI key"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "CI key"
    assert data["key"].startswith("awt_")
    assert len(data["key"]) == 36  # "awt_" + 32 hex chars
    assert data["prefix"] == data["key"][:8]
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_list_api_keys_no_full_key(pro_client: AsyncClient) -> None:
    """GET /api/keys returns prefix but not full key."""
    await pro_client.post("/api/keys", json={"name": "key1"})
    await pro_client.post("/api/keys", json={"name": "key2"})

    resp = await pro_client.get("/api/keys")
    assert resp.status_code == 200
    keys = resp.json()
    assert len(keys) == 2
    for k in keys:
        assert "key" not in k  # Full key must NOT be in list response
        assert "prefix" in k
        assert "name" in k


@pytest.mark.asyncio
async def test_delete_api_key(pro_client: AsyncClient) -> None:
    """DELETE /api/keys/{id} revokes a key."""
    create_resp = await pro_client.post("/api/keys", json={"name": "to-delete"})
    key_id = create_resp.json()["id"]

    del_resp = await pro_client.delete(f"/api/keys/{key_id}")
    assert del_resp.status_code == 204

    # Verify it's gone
    list_resp = await pro_client.get("/api/keys")
    assert len(list_resp.json()) == 0


@pytest.mark.asyncio
async def test_delete_other_user_key_404(pro_client: AsyncClient, db_session) -> None:
    """DELETE /api/keys/{id} returns 404 for another user's key."""
    import hashlib
    from app.models import ApiKey

    # Insert a key owned by a different user
    ak = ApiKey(
        user_id="other-user-id",
        key_hash=hashlib.sha256(b"awt_fake").hexdigest(),
        prefix="awt_fake",
        name="other",
    )
    db_session.add(ak)
    await db_session.commit()
    await db_session.refresh(ak)

    resp = await pro_client.delete(f"/api/keys/{ak.id}")
    assert resp.status_code == 404
