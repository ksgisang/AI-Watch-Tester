"""Rate limiting middleware — monthly POST /api/tests quota + concurrent limit."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import Test, TestStatus, User, UserTier

logger = logging.getLogger(__name__)

# -- Tier-based limits lookup (read from settings at call time for testability) --


def get_monthly_limit(tier: UserTier) -> int:
    limits = {
        UserTier.FREE: settings.rate_limit_free,
        UserTier.PRO: settings.rate_limit_pro,
        UserTier.TEAM: settings.rate_limit_team,
    }
    return limits.get(tier, settings.rate_limit_free)


def get_concurrent_limit(tier: UserTier) -> int:
    limits = {
        UserTier.FREE: settings.concurrent_limit_free,
        UserTier.PRO: settings.concurrent_limit_pro,
        UserTier.TEAM: settings.concurrent_limit_team,
    }
    return limits.get(tier, settings.concurrent_limit_free)


async def get_monthly_used(user_id: str, db: AsyncSession) -> int:
    """Count tests created this month by the user."""
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    q = (
        select(func.count())
        .select_from(Test)
        .where(Test.user_id == user_id, Test.created_at >= month_start)
    )
    return (await db.execute(q)).scalar() or 0


async def get_active_count(user_id: str, db: AsyncSession) -> int:
    """Count currently active (generating/queued/running) tests for the user."""
    q = (
        select(func.count())
        .select_from(Test)
        .where(
            Test.user_id == user_id,
            Test.status.in_([TestStatus.GENERATING, TestStatus.QUEUED, TestStatus.RUNNING]),
        )
    )
    return (await db.execute(q)).scalar() or 0


async def check_rate_limit(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Check monthly POST /api/tests quota + concurrent execution limit.

    Returns the user if within limits, raises 429 if exceeded.
    Adds X-RateLimit-* headers via request.state for the response middleware.
    """
    now = datetime.now(UTC)
    limit = get_monthly_limit(user.tier)

    # -- Monthly limit --
    used = await get_monthly_used(user.id, db)

    remaining = max(0, limit - used - 1)
    request.state.rate_limit = limit
    request.state.rate_remaining = remaining

    if used >= limit:
        upgrade_hint = (
            " Upgrade at /pricing for more tests."
            if user.tier == UserTier.FREE
            else ""
        )
        raise HTTPException(
            status_code=429,
            detail=f"Monthly test limit reached ({limit}).{upgrade_hint}",
            headers={
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": _next_month_iso(now),
            },
        )

    # -- Auto-clean stuck tests for this user (before concurrent check) --
    stuck_cutoff = datetime.now(UTC) - timedelta(
        minutes=settings.stuck_timeout_minutes
    )
    stuck_q = (
        select(Test).where(
            Test.user_id == user.id,
            Test.status.in_(
                [TestStatus.GENERATING, TestStatus.QUEUED, TestStatus.RUNNING]
            ),
            Test.updated_at < stuck_cutoff,
        )
    )
    stuck_result = await db.execute(stuck_q)
    stuck_tests = list(stuck_result.scalars().all())
    for t in stuck_tests:
        t.status = TestStatus.FAILED
        t.error_message = (
            f"Auto-cleaned: test stuck > {settings.stuck_timeout_minutes} min"
        )
        t.updated_at = datetime.now(UTC)
        logger.warning("Auto-cleaned stuck test %d for user %s", t.id, user.id)
    if stuck_tests:
        await db.commit()

    # -- Concurrent limit (per-user) --
    concurrent_limit = get_concurrent_limit(user.tier)
    active = await get_active_count(user.id, db)

    if active >= concurrent_limit:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Concurrent test limit reached ({concurrent_limit})."
                " Wait for running tests to finish."
            ),
        )

    # -- Global server capacity check --
    global_running_q = (
        select(func.count())
        .select_from(Test)
        .where(Test.status == TestStatus.RUNNING)
    )
    global_running = (await db.execute(global_running_q)).scalar() or 0
    if global_running >= settings.max_concurrent:
        raise HTTPException(
            status_code=429,
            detail="Server is busy. Please try again shortly.",
        )

    return user


def _next_month_iso(now: datetime) -> str:
    """Return ISO timestamp of the first day of next month."""
    if now.month == 12:
        reset = now.replace(
            year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    else:
        reset = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return reset.isoformat()
