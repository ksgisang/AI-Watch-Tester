"""Cloud backend configuration via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Cloud backend settings.

    All values can be overridden via environment variables (prefix: AWT_).
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
    ai_provider: str = "ollama"  # claude, openai, ollama
    ai_api_key: str = ""
    ai_model: str = ""  # auto-select based on provider if empty

    # Daily limit (Pro tier, -1 = unlimited)
    daily_limit_pro: int = 20

    # Sentry (optional — set DSN to enable)
    sentry_dsn: str = ""

    # Playwright (cloud worker)
    playwright_headless: bool = True

    model_config = {"env_prefix": "AWT_", "env_file": ".env", "extra": "ignore"}


settings = Settings()
