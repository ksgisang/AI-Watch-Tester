"""Billing endpoints — Lemon Squeezy webhook + subscription info."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.middleware import (
    get_active_count,
    get_concurrent_limit,
    get_monthly_limit,
    get_monthly_used,
)
from app.models import User, UserTier
from app.schemas import BillingResponse, BillingUsage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["billing"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _verify_signature(body: bytes, signature: str) -> bool:
    """Verify Lemon Squeezy webhook HMAC-SHA256 signature."""
    secret = settings.lemon_webhook_secret.encode()
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _resolve_tier(product_name: str) -> UserTier:
    """Determine tier from Lemon Squeezy product name."""
    name_lower = product_name.lower()
    if "team" in name_lower:
        return UserTier.TEAM
    if "pro" in name_lower:
        return UserTier.PRO
    return UserTier.FREE


# ---------------------------------------------------------------------------
# POST /api/webhooks/lemonsqueezy — no auth, signature verified
# ---------------------------------------------------------------------------


@router.post("/api/webhooks/lemonsqueezy", status_code=200)
async def lemon_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Handle Lemon Squeezy subscription webhooks."""
    body = await request.body()
    signature = request.headers.get("X-Signature", "")

    if not settings.lemon_webhook_secret:
        logger.warning("Lemon webhook secret not configured, rejecting webhook")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    if not _verify_signature(body, signature):
        raise HTTPException(status_code=403, detail="Invalid signature")

    import json
    payload = json.loads(body)

    meta = payload.get("meta", {})
    event_name = meta.get("event_name", "")
    custom_data = meta.get("custom_data", {})
    user_id = custom_data.get("user_id")

    if not user_id:
        logger.warning("Webhook missing user_id in custom_data: %s", event_name)
        return {"status": "ignored", "reason": "no user_id"}

    # Find user
    user = await db.get(User, user_id)
    if not user:
        logger.warning("Webhook user not found: %s", user_id)
        return {"status": "ignored", "reason": "user not found"}

    attrs = payload.get("data", {}).get("attributes", {})

    if event_name == "subscription_created":
        product_name = attrs.get("product_name", "")
        user.tier = _resolve_tier(product_name)
        user.lemon_customer_id = str(attrs.get("customer_id", ""))
        user.lemon_subscription_id = str(payload.get("data", {}).get("id", ""))
        if attrs.get("renews_at"):
            from datetime import datetime
            with contextlib.suppress(ValueError, TypeError):
                user.plan_expires_at = datetime.fromisoformat(
                    attrs["renews_at"].replace("Z", "+00:00")
                )
        logger.info("Subscription created: user=%s tier=%s", user_id, user.tier.value)

    elif event_name == "subscription_updated":
        product_name = attrs.get("product_name", "")
        user.tier = _resolve_tier(product_name)
        if attrs.get("renews_at"):
            from datetime import datetime
            with contextlib.suppress(ValueError, TypeError):
                user.plan_expires_at = datetime.fromisoformat(
                    attrs["renews_at"].replace("Z", "+00:00")
                )
        logger.info("Subscription updated: user=%s tier=%s", user_id, user.tier.value)

    elif event_name == "subscription_cancelled":
        # Keep tier until ends_at, then downgrade
        ends_at = attrs.get("ends_at")
        if ends_at:
            from datetime import datetime
            try:
                user.plan_expires_at = datetime.fromisoformat(ends_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                user.tier = UserTier.FREE
                user.plan_expires_at = None
        else:
            user.tier = UserTier.FREE
            user.plan_expires_at = None
        logger.info("Subscription cancelled: user=%s ends_at=%s", user_id, ends_at)

    elif event_name == "subscription_payment_success":
        if attrs.get("renews_at"):
            from datetime import datetime
            with contextlib.suppress(ValueError, TypeError):
                user.plan_expires_at = datetime.fromisoformat(
                    attrs["renews_at"].replace("Z", "+00:00")
                )
        logger.info("Payment success: user=%s", user_id)

    elif event_name == "subscription_payment_failed":
        logger.warning("Payment failed: user=%s", user_id)

    else:
        logger.info("Unhandled webhook event: %s", event_name)

    await db.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# GET /api/billing/me — authenticated
# ---------------------------------------------------------------------------


@router.get("/api/billing/me", response_model=BillingResponse)
async def billing_me(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BillingResponse:
    """Current user's billing info + usage stats."""
    monthly_used = await get_monthly_used(user.id, db)
    active = await get_active_count(user.id, db)

    return BillingResponse(
        tier=user.tier,
        lemon_customer_id=user.lemon_customer_id,
        lemon_subscription_id=user.lemon_subscription_id,
        plan_expires_at=user.plan_expires_at,
        usage=BillingUsage(
            monthly_used=monthly_used,
            monthly_limit=get_monthly_limit(user.tier),
            active_count=active,
            concurrent_limit=get_concurrent_limit(user.tier),
        ),
    )


# ---------------------------------------------------------------------------
# GET /api/billing/portal — authenticated, returns Lemon Squeezy customer portal URL
# ---------------------------------------------------------------------------


@router.get("/api/billing/portal")
async def billing_portal(
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Return Lemon Squeezy customer portal URL."""
    if not user.lemon_customer_id:
        raise HTTPException(status_code=404, detail="No subscription found")

    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.lemonsqueezy.com/v1/customers/{user.lemon_customer_id}",
            headers={
                "Authorization": f"Bearer {settings.lemon_api_key}",
                "Accept": "application/vnd.api+json",
            },
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to fetch customer portal")

    data = resp.json()
    portal_url = (
        data.get("data", {}).get("attributes", {}).get("urls", {}).get("customer_portal", "")
    )
    if not portal_url:
        raise HTTPException(status_code=404, detail="Portal URL not available")

    return {"url": portal_url}
