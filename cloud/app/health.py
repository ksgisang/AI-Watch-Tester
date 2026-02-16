"""Enhanced health check — DB, Worker, AI provider status."""

from __future__ import annotations

import time
import logging
from typing import Any

import httpx
from sqlalchemy import text

from app.config import settings
from app.database import async_session

logger = logging.getLogger(__name__)

_start_time = time.monotonic()


async def check_database() -> dict[str, Any]:
    """Check database connectivity."""
    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
        return {"status": "up"}
    except Exception as exc:
        logger.warning("DB health check failed: %s", exc)
        return {"status": "down", "error": str(exc)}


async def check_worker() -> dict[str, Any]:
    """Check background worker status."""
    from app.worker import worker

    if worker.is_running:
        return {
            "status": "up",
            "active_tests": worker.active_count,
            "max_concurrent": settings.max_concurrent,
        }
    return {"status": "down", "error": "Worker not running"}


async def check_ai_provider() -> dict[str, Any]:
    """Check AI provider connectivity."""
    provider = settings.ai_provider

    if provider == "ollama":
        return await _check_ollama()
    elif provider == "claude":
        return _check_api_key("claude", settings.ai_api_key)
    elif provider == "openai":
        return _check_api_key("openai", settings.ai_api_key)
    else:
        return {"status": "unknown", "provider": provider}


async def _check_ollama() -> dict[str, Any]:
    """Ping Ollama API."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                return {
                    "status": "up",
                    "provider": "ollama",
                    "models_available": len(models),
                }
            return {
                "status": "down",
                "provider": "ollama",
                "error": f"HTTP {resp.status_code}",
            }
    except Exception as exc:
        return {"status": "down", "provider": "ollama", "error": str(exc)}


def _check_api_key(provider: str, api_key: str) -> dict[str, Any]:
    """Check if API key is configured (no actual API call)."""
    if api_key:
        return {"status": "up", "provider": provider, "key_configured": True}
    return {
        "status": "degraded",
        "provider": provider,
        "error": "API key not configured",
    }


async def get_health() -> dict[str, Any]:
    """Run all health checks and return aggregated status."""
    db = await check_database()
    wk = await check_worker()
    ai = await check_ai_provider()

    checks = {"database": db, "worker": wk, "ai_provider": ai}

    statuses = [c["status"] for c in checks.values()]
    if all(s == "up" for s in statuses):
        overall = "healthy"
    elif any(s == "down" for s in statuses):
        overall = "down"
    else:
        overall = "degraded"

    return {
        "status": overall,
        "checks": checks,
        "uptime_seconds": round(time.monotonic() - _start_time, 1),
    }
