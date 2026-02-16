"""Rate limiting middleware — monthly POST /api/tests quota."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import Test, User, UserTier


async def check_rate_limit(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Check monthly POST /api/tests quota.

    Only applies to POST requests on the tests endpoint.
    Returns the user if within limit, raises 429 if exceeded.

    Adds X-RateLimit-* headers via request.state for the response middleware.
    """
    now = datetime.now(timezone.utc)

    # -- Daily limit for Pro users --
    if user.tier == UserTier.PRO and settings.daily_limit_pro > 0:
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        daily_q = (
            select(func.count())
            .select_from(Test)
            .where(Test.user_id == user.id, Test.created_at >= today_start)
        )
        daily_used = (await db.execute(daily_q)).scalar() or 0
        if daily_used >= settings.daily_limit_pro:
            raise HTTPException(
                status_code=429,
                detail=f"Daily test limit reached ({settings.daily_limit_pro}). Try again tomorrow.",
                headers={
                    "X-RateLimit-Limit": str(settings.daily_limit_pro),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": _next_day_iso(now),
                },
            )

    # Determine limit based on tier
    if user.tier == UserTier.PRO:
        limit = settings.rate_limit_pro
    else:
        limit = settings.rate_limit_free

    # Unlimited (-1)
    if limit < 0:
        request.state.rate_limit = -1
        request.state.rate_remaining = -1
        return user

    # Count this month's test creations
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    count_q = (
        select(func.count())
        .select_from(Test)
        .where(Test.user_id == user.id, Test.created_at >= month_start)
    )
    used = (await db.execute(count_q)).scalar() or 0

    # Store for response headers (account for the current request)
    remaining = max(0, limit - used - 1)
    request.state.rate_limit = limit
    request.state.rate_remaining = remaining

    if used >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Monthly test limit reached ({limit}). Upgrade to Pro for unlimited tests.",
            headers={
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": _next_month_iso(now),
            },
        )

    return user


def _next_month_iso(now: datetime) -> str:
    """Return ISO timestamp of the first day of next month."""
    if now.month == 12:
        reset = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        reset = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return reset.isoformat()


def _next_day_iso(now: datetime) -> str:
    """Return ISO timestamp of the start of next day (UTC)."""
    from datetime import timedelta

    reset = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return reset.isoformat()
