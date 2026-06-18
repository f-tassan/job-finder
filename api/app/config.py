"""Application settings (pydantic-settings).

Loaded from environment / `.env`. Only the fields needed in Phase 0 are
consumed yet; the rest are declared so later phases can read them without
touching infra. See `.env.example` for the full list.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Postgres ---
    postgres_user: str = "jobfinder"
    postgres_password: str = "jobfinder"
    postgres_db: str = "jobfinder"
    postgres_host: str = "db"
    postgres_port: int = 5432

    # --- Redis / Celery ---
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    celery_result_backend: str = "redis://redis:6379/1"

    # --- Web / proxy ---
    domain: str = "localhost"
    public_api_url: str = "/api"

    # --- Auth & seed (Phase 1) ---
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    first_user_email: str | None = None
    first_user_password: str | None = None
    max_users: int = 3

    # --- External services (later phases) ---
    anthropic_api_key: str | None = None
    telegram_bot_token: str | None = None

    @property
    def database_url(self) -> str:
        """SQLAlchemy URL using psycopg3 (works for both sync and async engines)."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
