"""AWT Cloud — FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import engine
from app.models import Base
from app.routers import tests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional: Sentry
# ---------------------------------------------------------------------------
if settings.sentry_dsn:
    try:
        import sentry_sdk  # type: ignore[import-untyped]

        sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.1)
        logger.info("Sentry initialized")
    except ImportError:
        logger.warning("sentry-sdk not installed, skipping Sentry integration")

# ---------------------------------------------------------------------------
# Optional: structlog
# ---------------------------------------------------------------------------
try:
    import structlog  # type: ignore[import-untyped]

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Lifespan: DB init + background worker
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Create DB tables and start background worker on startup."""
    # DB tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Background worker
    from app.worker import worker

    await worker.start()

    yield

    # Shutdown
    await worker.stop()


app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    lifespan=lifespan,
)

# -- CORS (frontend dev server) --
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -- Static: screenshots --
import os
from pathlib import Path

_ss_dir = Path(settings.screenshot_dir)
if _ss_dir.exists():
    app.mount("/screenshots", StaticFiles(directory=str(_ss_dir)), name="screenshots")

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


# -- Worker status --
@app.get("/api/worker/status")
async def worker_status() -> dict[str, object]:
    """Worker status endpoint (no auth required)."""
    from app.worker import worker

    return {
        "running": worker.is_running,
        "active_tests": worker.active_count,
        "max_concurrent": settings.max_concurrent,
    }
