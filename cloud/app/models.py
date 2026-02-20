"""SQLAlchemy ORM models for cloud backend."""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class TestStatus(str, enum.Enum):
    """Test execution status."""

    GENERATING = "generating"
    REVIEW = "review"
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class UserTier(str, enum.Enum):
    """User subscription tier."""

    FREE = "free"
    PRO = "pro"
    TEAM = "team"


class Test(Base):
    """A test run record."""

    __tablename__ = "tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[TestStatus] = mapped_column(
        Enum(TestStatus), default=TestStatus.QUEUED, nullable=False
    )
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    scenario_yaml: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps_total: Mapped[int] = mapped_column(Integer, default=0)
    steps_completed: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )


class User(Base):
    """User profile (synced from Supabase Auth)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # Supabase user UUID
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    tier: Mapped[UserTier] = mapped_column(
        Enum(UserTier), default=UserTier.FREE, nullable=False
    )
    lemon_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lemon_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )


class ScanStatus(str, enum.Enum):
    """Smart Scan status."""

    SCANNING = "scanning"
    COMPLETED = "completed"
    PLANNING = "planning"
    PLANNED = "planned"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Scan(Base):
    """A site scan record for Smart Scan."""

    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus), default=ScanStatus.SCANNING, nullable=False
    )
    max_pages: Mapped[int] = mapped_column(Integer, default=5)
    max_depth: Mapped[int] = mapped_column(Integer, default=2)
    # JSON text columns (SQLite compatible)
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    pages_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    broken_links_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_features: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    observations_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ApiKey(Base):
    """API key for CI/CD authentication (X-API-Key header)."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    prefix: Mapped[str] = mapped_column(String(12), nullable=False)  # awt_xxxx (UI display)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
