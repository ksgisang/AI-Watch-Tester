"""Supabase Auth + API Key — dual authentication."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import ApiKey, User, UserTier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JWKS client — fetches public keys from Supabase for ES256 verification
# ---------------------------------------------------------------------------

_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    """Lazily create and cache a JWKS client for the Supabase project."""
    global _jwks_client  # noqa: PLW0603

    if _jwks_client is not None:
        return _jwks_client

    if not settings.supabase_url:
        raise HTTPException(
            status_code=503,
            detail="Supabase not configured. Set AWT_SUPABASE_URL.",
        )

    jwks_url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    _jwks_client = PyJWKClient(jwks_url, cache_keys=True)
    return _jwks_client


def verify_supabase_token(token: str) -> dict[str, Any]:
    """Verify a Supabase JWT access token and return decoded payload.

    Supabase uses ES256 (ECDSA) JWTs signed with a project-specific key pair.
    The public key is fetched from the JWKS endpoint.

    Raises HTTPException 401/503 on failure.
    """
    # Try ES256 via JWKS first (current Supabase default)
    if settings.supabase_url:
        try:
            client = _get_jwks_client()
            signing_key = client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256"],
                audience="authenticated",
            )
            return payload
        except jwt.ExpiredSignatureError as exc:
            raise HTTPException(
                status_code=401,
                detail="Token expired. Please login again.",
            ) from exc
        except jwt.InvalidTokenError as exc:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid token: {exc}",
            ) from exc
        except Exception as exc:
            # JWKS fetch failure — fall through to HS256 if configured
            logger.warning("JWKS verification failed: %s", exc)

    # Fallback: HS256 with JWT secret (legacy or local dev)
    if settings.supabase_jwt_secret:
        try:
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
            return payload
        except jwt.ExpiredSignatureError as exc:
            raise HTTPException(
                status_code=401,
                detail="Token expired. Please login again.",
            ) from exc
        except jwt.InvalidTokenError as exc:
            raise HTTPException(
                status_code=401,
                detail=f"Invalid token: {exc}",
            ) from exc

    raise HTTPException(
        status_code=503,
        detail="Supabase not configured. Set AWT_SUPABASE_URL or AWT_SUPABASE_JWT_SECRET.",
    )


# ---------------------------------------------------------------------------
# FastAPI dependency: extract current user from Authorization header
# ---------------------------------------------------------------------------


def _extract_bearer_token(request: Request) -> str:
    """Extract Bearer token from Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header. Expected: Bearer <token>",
        )
    return auth_header[7:]


async def _authenticate_api_key(api_key: str, db: AsyncSession) -> User:
    """Verify X-API-Key header → return User + update last_used_at."""
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    result = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    ak = result.scalar_one_or_none()

    if ak is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    # Update last_used_at
    ak.last_used_at = datetime.now(UTC)
    await db.commit()

    # Load user
    user_result = await db.execute(select(User).where(User.id == ak.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="API key owner not found")

    return user


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency: X-API-Key header first, then Bearer JWT."""
    # 1) Try API key
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return await _authenticate_api_key(api_key, db)

    # 2) Fall back to Bearer JWT
    token = _extract_bearer_token(request)
    payload = verify_supabase_token(token)

    uid: str = payload["sub"]
    email: str = payload.get("email", "")

    # Upsert user
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()

    if user is None:
        user = User(id=uid, email=email, tier=UserTier.FREE)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    elif user.email != email:
        user.email = email
        await db.commit()

    return user
