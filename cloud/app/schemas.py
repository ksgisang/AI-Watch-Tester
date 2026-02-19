"""Pydantic schemas for API request/response."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, HttpUrl

from app.models import TestStatus, UserTier


# -- Scenario Conversion --


class ConvertScenarioRequest(BaseModel):
    """POST /api/scenarios/convert request body."""

    target_url: str
    user_prompt: str
    language: Literal["ko", "en"] = "en"


class ConvertScenarioResponse(BaseModel):
    """POST /api/scenarios/convert response body."""

    scenario_yaml: str
    scenarios_count: int
    steps_total: int


# -- Requests --


class TestCreate(BaseModel):
    """POST /api/tests request body."""

    target_url: HttpUrl
    mode: Literal["review", "auto"] = "review"


class ScenarioUpdate(BaseModel):
    """PUT /api/tests/{id}/scenarios request body."""

    scenario_yaml: str


# -- Responses --


class TestResponse(BaseModel):
    """Single test in API responses."""

    id: int
    user_id: str
    target_url: str
    status: TestStatus
    result_json: str | None = None
    scenario_yaml: str | None = None
    doc_text: str | None = None
    error_message: str | None = None
    steps_total: int = 0
    steps_completed: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TestListResponse(BaseModel):
    """GET /api/tests response."""

    tests: list[TestResponse]
    total: int
    page: int
    page_size: int


class UserResponse(BaseModel):
    """Current user info."""

    id: str
    email: str
    tier: UserTier

    model_config = {"from_attributes": True}


class UploadResponse(BaseModel):
    """POST /api/tests/{id}/upload response."""

    filename: str
    size: int
    extracted_chars: int


class ErrorResponse(BaseModel):
    """Error response body."""

    detail: str


# -- API Keys --


class BillingUsage(BaseModel):
    """Usage stats for billing."""

    monthly_used: int
    monthly_limit: int
    active_count: int
    concurrent_limit: int


class BillingResponse(BaseModel):
    """GET /api/billing/me response."""

    tier: UserTier
    lemon_customer_id: str | None = None
    lemon_subscription_id: str | None = None
    plan_expires_at: datetime | None = None
    usage: BillingUsage


class ApiKeyCreate(BaseModel):
    """POST /api/keys request body."""

    name: str


class ApiKeyResponse(BaseModel):
    """API key in list responses (no full key)."""

    id: int
    prefix: str
    name: str
    created_at: datetime
    last_used_at: datetime | None = None

    model_config = {"from_attributes": True}


class ApiKeyCreated(BaseModel):
    """POST /api/keys response (full key shown once)."""

    id: int
    key: str
    prefix: str
    name: str
    created_at: datetime
