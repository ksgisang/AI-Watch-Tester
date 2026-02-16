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

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class UserTier(str, enum.Enum):
    """User subscription tier."""

    FREE = "free"
    PRO = "pro"


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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )
