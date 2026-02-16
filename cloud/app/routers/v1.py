"""Versioned API (v1) — CI/CD friendly endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.middleware import check_rate_limit
from app.models import Test, TestStatus, User
from app.schemas import TestCreate, TestResponse

router = APIRouter(prefix="/api/v1", tags=["v1"])


@router.post("/tests", response_model=TestResponse, status_code=201)
async def create_test_v1(
    body: TestCreate,
    wait: bool = Query(False, description="Wait for completion (synchronous mode)"),
    user: User = Depends(check_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Test:
    """Create a test. With wait=true, poll until DONE/FAILED or timeout (408)."""
    initial_status = (
        TestStatus.GENERATING if body.mode == "review" else TestStatus.QUEUED
    )
    test = Test(
        user_id=user.id,
        target_url=str(body.target_url),
        status=initial_status,
    )
    db.add(test)
    await db.commit()
    await db.refresh(test)

    if not wait:
        return test

    # Synchronous mode: poll until DONE/FAILED
    timeout = settings.api_timeout
    elapsed = 0
    poll_interval = 2
    test_id = test.id

    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

        # Expire cached state so we see latest DB changes (worker commits)
        db.expire_all()
        result = await db.execute(select(Test).where(Test.id == test_id))
        refreshed = result.scalar_one_or_none()
        if refreshed and refreshed.status in (TestStatus.DONE, TestStatus.FAILED):
            return refreshed

    raise HTTPException(
        status_code=408,
        detail=f"Test did not complete within {timeout}s timeout",
    )


@router.get("/tests/{test_id}", response_model=TestResponse)
async def get_test_v1(
    test_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Test:
    """Get test status and results."""
    result = await db.execute(
        select(Test).where(Test.id == test_id, Test.user_id == user.id)
    )
    test = result.scalar_one_or_none()
    if test is None:
        raise HTTPException(status_code=404, detail="Test not found")
    return test
