"""API Key CRUD endpoints (JWT auth only)."""

from __future__ import annotations

import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import ApiKey, User
from app.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyResponse

router = APIRouter(prefix="/api/keys", tags=["keys"])


@router.post("", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(
    body: ApiKeyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate a new API key. Full key is returned once only."""
    raw_key = "awt_" + secrets.token_hex(16)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    prefix = raw_key[:8]  # awt_xxxx

    ak = ApiKey(
        user_id=user.id,
        key_hash=key_hash,
        prefix=prefix,
        name=body.name,
    )
    db.add(ak)
    await db.commit()
    await db.refresh(ak)

    return {
        "id": ak.id,
        "key": raw_key,
        "prefix": prefix,
        "name": ak.name,
        "created_at": ak.created_at,
    }


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ApiKey]:
    """List current user's API keys (prefix only, no full key)."""
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == user.id)
        .order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


@router.delete("/{key_id}", status_code=204)
async def delete_api_key(
    key_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke an API key (owner only)."""
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
    )
    ak = result.scalar_one_or_none()
    if ak is None:
        raise HTTPException(status_code=404, detail="API key not found")

    await db.delete(ak)
    await db.commit()
