"""Pydantic schemas for API request/response."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, HttpUrl

from app.models import TestStatus, UserTier


# -- Requests --


class TestCreate(BaseModel):
    """POST /api/tests request body."""

    target_url: HttpUrl


# -- Responses --


class TestResponse(BaseModel):
    """Single test in API responses."""

    id: int
    user_id: str
    target_url: str
    status: TestStatus
    result_json: str | None = None
    scenario_yaml: str | None = None
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


class ErrorResponse(BaseModel):
    """Error response body."""

    detail: str
