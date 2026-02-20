"""Tests for X-API-Key header authentication."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from app.database import get_db
from app.models import ApiKey, User, UserTier
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest_asyncio.fixture
async def auth_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Client WITHOUT auth override — tests real auth flow."""
    from app.main import app

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    # Create user + API key in test DB
    user = User(id="apikey-uid-001", email="apikey@example.com", tier=UserTier.FREE)
    db_session.add(user)

    raw_key = "awt_testkey1234567890abcdef"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    ak = ApiKey(
        user_id="apikey-uid-001",
        key_hash=key_hash,
        prefix="awt_test",
        name="test key",
    )
    db_session.add(ak)
    await db_session.commit()

    app.dependency_overrides[get_db] = _override_db
    # NOTE: no get_current_user override — real auth path

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_key_valid(auth_client: AsyncClient) -> None:
    """X-API-Key with valid key returns 200."""
    resp = await auth_client.get(
        "/api/tests",
        headers={"X-API-Key": "awt_testkey1234567890abcdef"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_key_invalid(auth_client: AsyncClient) -> None:
    """X-API-Key with invalid key returns 401."""
    resp = await auth_client.get(
        "/api/tests",
        headers={"X-API-Key": "awt_wrongkey"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_no_auth_header(auth_client: AsyncClient) -> None:
    """No auth header at all returns 401."""
    resp = await auth_client.get("/api/tests")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_api_key_updates_last_used(
    auth_client: AsyncClient, db_session: AsyncSession
) -> None:
    """Using API key updates last_used_at timestamp."""
    from sqlalchemy import select

    # Before: last_used_at should be None
    result = await db_session.execute(
        select(ApiKey).where(ApiKey.prefix == "awt_test")
    )
    ak = result.scalar_one()
    assert ak.last_used_at is None

    # Make a request
    await auth_client.get(
        "/api/tests",
        headers={"X-API-Key": "awt_testkey1234567890abcdef"},
    )

    # After: last_used_at should be set
    await db_session.refresh(ak)
    assert ak.last_used_at is not None
