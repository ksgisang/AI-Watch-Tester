"""Tests for Supabase JWT auth middleware."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

# Shared test secret (matches AWT_SUPABASE_JWT_SECRET in tests)
TEST_JWT_SECRET = "test-jwt-secret-for-unit-tests"


def _make_token(
    sub: str = "test-uid-001",
    email: str = "test@example.com",
    expired: bool = False,
) -> str:
    """Create a valid Supabase-style JWT for testing."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "email": email,
        "role": "authenticated",
        "aud": "authenticated",
        "iat": now,
        "exp": now + (timedelta(hours=-1) if expired else timedelta(hours=1)),
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


@pytest.mark.asyncio
async def test_missing_auth_header() -> None:
    """Request without Authorization header returns 401."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/tests")

    assert resp.status_code == 401
    assert "Authorization" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_non_bearer_auth() -> None:
    """Request with non-Bearer auth returns 401."""
    from app.main import app

    app.dependency_overrides.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/api/tests",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_no_jwt_secret_returns_503() -> None:
    """If JWT secret is not configured, returns 503."""
    from app.main import app

    app.dependency_overrides.clear()

    with patch("app.auth.settings") as mock_settings:
        mock_settings.supabase_jwt_secret = ""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(
                "/api/tests",
                headers={"Authorization": f"Bearer {_make_token()}"},
            )

    assert resp.status_code == 503
    assert "Supabase" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_token_returns_401() -> None:
    """Invalid JWT returns 401."""
    from app.main import app

    app.dependency_overrides.clear()

    with patch("app.auth.settings") as mock_settings:
        mock_settings.supabase_jwt_secret = TEST_JWT_SECRET
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(
                "/api/tests",
                headers={"Authorization": "Bearer not.a.valid.jwt"},
            )

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_returns_401() -> None:
    """Expired JWT returns 401 with expiry message."""
    from app.main import app

    app.dependency_overrides.clear()

    with patch("app.auth.settings") as mock_settings:
        mock_settings.supabase_jwt_secret = TEST_JWT_SECRET
        token = _make_token(expired=True)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(
                "/api/tests",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert resp.status_code == 401
    assert "expired" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_wrong_secret_returns_401() -> None:
    """JWT signed with wrong secret returns 401."""
    from app.main import app

    app.dependency_overrides.clear()

    # Token signed with different secret
    wrong_token = jwt.encode(
        {
            "sub": "user-1",
            "email": "a@b.com",
            "aud": "authenticated",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        "wrong-secret",
        algorithm="HS256",
    )

    with patch("app.auth.settings") as mock_settings:
        mock_settings.supabase_jwt_secret = TEST_JWT_SECRET
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(
                "/api/tests",
                headers={"Authorization": f"Bearer {wrong_token}"},
            )

    assert resp.status_code == 401
