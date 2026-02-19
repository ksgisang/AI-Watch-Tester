"""Shared fixtures for cloud backend tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import get_current_user
from app.database import get_db
from app.models import Base, User, UserTier

# ---------------------------------------------------------------------------
# In-memory SQLite for tests
# ---------------------------------------------------------------------------

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a fresh DB session with tables created."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with test_session_factory() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ---------------------------------------------------------------------------
# Mock user (skip real Supabase auth)
# ---------------------------------------------------------------------------

_MOCK_USER = User(id="test-uid-001", email="test@example.com", tier=UserTier.FREE)
_MOCK_PRO_USER = User(id="pro-uid-001", email="pro@example.com", tier=UserTier.PRO)


@pytest.fixture(autouse=True)
def _high_concurrent_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default high concurrent limit for all tests (test concurrent separately)."""
    from app import config

    monkeypatch.setattr(config.settings, "concurrent_limit_free", 100)
    monkeypatch.setattr(config.settings, "concurrent_limit_pro", 100)
    monkeypatch.setattr(config.settings, "concurrent_limit_team", 100)


def _make_mock_user_dep(user: User):
    """Create a dependency override that returns a fixed user."""
    async def _override() -> User:
        return user
    return _override


# ---------------------------------------------------------------------------
# Async HTTP client with app
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Async test client with DB and auth overrides (Free user)."""
    from app.main import app

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    # Ensure user exists in DB
    db_session.add(User(id="test-uid-001", email="test@example.com", tier=UserTier.FREE))
    await db_session.commit()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _make_mock_user_dep(_MOCK_USER)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def pro_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Async test client with Pro user."""
    from app.main import app

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    db_session.add(User(id="pro-uid-001", email="pro@example.com", tier=UserTier.PRO))
    await db_session.commit()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _make_mock_user_dep(_MOCK_PRO_USER)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
