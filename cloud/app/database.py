"""Database setup — async SQLAlchemy with SQLite/PostgreSQL."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    # SQLite needs check_same_thread=False
    connect_args={"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {},
)

async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an async DB session."""
    async with async_session() as session:
        yield session
