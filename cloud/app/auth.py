"""Supabase Auth — JWT verification and user dependency."""

from __future__ import annotations

import logging
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User, UserTier

logger = logging.getLogger(__name__)


def verify_supabase_token(token: str) -> dict[str, Any]:
    """Verify a Supabase JWT access token and return decoded payload.

    Supabase issues standard JWTs signed with the project's JWT secret (HS256).
    The payload contains: sub (user ID), email, role, exp, etc.

    Raises HTTPException 401/503 on failure.
    """
    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=503,
            detail="Supabase not configured. Set AWT_SUPABASE_JWT_SECRET.",
        )

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


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency: verify Supabase JWT → return or create User record.

    Supabase JWT payload example:
        {
            "sub": "uuid-user-id",
            "email": "user@example.com",
            "role": "authenticated",
            "aud": "authenticated",
            ...
        }
    """
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
