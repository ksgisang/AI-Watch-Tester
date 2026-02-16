"""Test CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.middleware import check_rate_limit
from app.models import Test, TestStatus, User
from app.schemas import TestCreate, TestListResponse, TestResponse

router = APIRouter(prefix="/api/tests", tags=["tests"])


@router.post("", response_model=TestResponse, status_code=201)
async def create_test(
    body: TestCreate,
    user: User = Depends(check_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> Test:
    """Create a new test (status=queued).

    The test is saved to DB but not executed yet (stub).
    Actual execution will be implemented in a later gate.
    """
    test = Test(
        user_id=user.id,
        target_url=str(body.target_url),
        status=TestStatus.QUEUED,
    )
    db.add(test)
    await db.commit()
    await db.refresh(test)
    return test


@router.get("", response_model=TestListResponse)
async def list_tests(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
) -> dict:
    """List current user's tests (newest first, paginated)."""
    # Total count
    count_q = select(func.count()).select_from(Test).where(Test.user_id == user.id)
    total = (await db.execute(count_q)).scalar() or 0

    # Paginated results
    offset = (page - 1) * page_size
    query = (
        select(Test)
        .where(Test.user_id == user.id)
        .order_by(Test.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(query)
    tests = list(result.scalars().all())

    return {
        "tests": tests,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{test_id}", response_model=TestResponse)
async def get_test(
    test_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Test:
    """Get a single test by ID (must belong to current user)."""
    query = select(Test).where(Test.id == test_id, Test.user_id == user.id)
    result = await db.execute(query)
    test = result.scalar_one_or_none()

    if test is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Test not found")

    return test
