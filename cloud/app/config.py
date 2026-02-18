"""Cloud backend configuration via environment variables."""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Cloud backend settings.

    All values can be overridden via environment variables (prefix: AWT_).
    AI fields also accept AWT_SERVICE_AI_* aliases for Render compatibility.
    """

    # App
    app_name: str = "AWT Cloud"
    debug: bool = False

    # Database — SQLite for dev, Supabase PostgreSQL for prod
    # SQLite:     sqlite+aiosqlite:///./awt_cloud.db
    # PostgreSQL: postgresql+asyncpg://postgres.[ref]:[password]@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres
    database_url: str = "sqlite+aiosqlite:///./awt_cloud.db"

    # Supabase
    supabase_url: str = ""          # https://<project-ref>.supabase.co
    supabase_anon_key: str = ""     # public anon key (for client-side auth)
    supabase_jwt_secret: str = ""   # JWT secret (Settings > API > JWT Secret)

    # Rate limits (monthly POST /api/tests)
    rate_limit_free: int = 5
    rate_limit_pro: int = -1  # -1 = unlimited

    # Worker
    max_concurrent: int = 2
    worker_poll_interval: float = 2.0  # seconds

    # AI provider for scenario generation
    # Accepts AWT_AI_PROVIDER or AWT_SERVICE_AI_PROVIDER (Render compatibility)
    ai_provider: str = Field(
        default="ollama",
        validation_alias=AliasChoices("AWT_AI_PROVIDER", "AWT_SERVICE_AI_PROVIDER"),
    )
    ai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("AWT_AI_API_KEY", "AWT_SERVICE_AI_KEY"),
    )
    ai_model: str = Field(
        default="",
        validation_alias=AliasChoices("AWT_AI_MODEL", "AWT_SERVICE_AI_MODEL"),
    )

    # Daily limit (Pro tier, -1 = unlimited)
    daily_limit_pro: int = 20

    # CORS — comma-separated origins, or "*" for all (dev default)
    cors_origins: str = "*"

    # Sentry (optional — set DSN to enable)
    sentry_dsn: str = ""

    # API (v1 wait mode timeout in seconds)
    api_timeout: int = 300

    # Playwright (cloud worker)
    playwright_headless: bool = True

    # Screenshots (file-based, not base64 in DB)
    screenshot_dir: str = "cloud/screenshots"

    # Uploads (document files for AI context)
    upload_dir: str = "cloud/uploads"
    upload_max_bytes: int = 10 * 1024 * 1024  # 10MB

    model_config = {"env_prefix": "AWT_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
