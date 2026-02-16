"""AWT Cloud — FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request, Response

from app.config import settings
from app.database import engine
from app.models import Base
from app.routers import tests


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Create DB tables on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

# -- Routers --
app.include_router(tests.router)


# -- Rate limit response headers --
@app.middleware("http")
async def add_rate_limit_headers(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
    """Inject X-RateLimit-* headers into responses."""
    response: Response = await call_next(request)

    if hasattr(request.state, "rate_limit"):
        limit = request.state.rate_limit
        remaining = request.state.rate_remaining
        if limit >= 0:
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)

    return response


# -- Health check --
@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint (no auth required)."""
    return {"status": "ok"}
