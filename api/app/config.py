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

    # --- File storage (docker volume; per-user subpaths) ---
    files_dir: str = "/data/files"

    # --- Auth & seed (Phase 1) ---
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    # Fernet key (urlsafe-b64, 32 bytes) used to encrypt portal credentials at
    # rest. Generate with: python -c "from cryptography.fernet import Fernet;
    # print(Fernet.generate_key().decode())". If unset, a key is derived from
    # jwt_secret (works, but rotate both together).
    credentials_key: str | None = None
    first_user_email: str | None = None
    first_user_password: str | None = None
    first_user_name: str = "Admin"
    max_users: int = 3

    # --- Discovery / relevance (Phase 2) ---
    match_threshold: float = 0.25  # min cosine to be a candidate (recall)
    auto_track_threshold: float = 0.55  # auto-create a `discovered` application
    rerank_top_k: int = 40  # top cosine candidates to LLM re-rank per user
    discovery_interval_minutes: int = 360  # Celery Beat cadence
    # Max per-job Telegram messages (with action buttons) per user per discovery
    # run; anything beyond is summarized so the chat isn't flooded.
    telegram_jobs_per_run: int = 8
    # Max liveness (still-posted?) HTTP checks per discovery run. Bounds the
    # extra runtime the removed-job pruning adds; discovered-column jobs are
    # checked first, then the ranked feed.
    liveness_check_cap: int = 60

    # --- Document generation toggles ---
    # Temporarily off: the tailored-CV output quality isn't good enough yet, so
    # the Generate/Regenerate CV buttons are hidden and CV requests are refused
    # everywhere. Cover letters are unaffected. Flip back to True to re-enable.
    cv_generation_enabled: bool = False

    # --- LinkedIn discovery hardening (avoid rate-limit / blocking) ---
    # Comma-separated proxy URLs (e.g. "http://user:pass@host:port,http://..."),
    # rotated per request. Empty = direct connection.
    linkedin_proxies: str = ""
    linkedin_min_delay: float = 3.0   # min seconds between LinkedIn requests
    linkedin_max_delay: float = 7.0   # max seconds between LinkedIn requests
    linkedin_max_requests: int = 120  # hard cap on LinkedIn requests per run
    linkedin_max_retries: int = 3     # retries on 429/999/403 (with backoff)
    linkedin_backoff_base: float = 20.0  # base backoff seconds (x attempt)

    # IMAP (email_alerts connector + submission-confirmation watcher). Both are
    # no-ops unless these are set.
    imap_host: str | None = None
    imap_user: str | None = None
    imap_password: str | None = None
    imap_folder: str = "INBOX"
    # How often the watcher scans the inbox for "application received" emails to
    # auto-mark applications as submitted.
    email_watch_interval_minutes: int = 30

    # --- LLM provider (CV parsing + tailoring) ---
    # This deployment uses OpenAI. "openai" forces the OpenAI path; "auto" would
    # pick OpenAI when OPENAI_API_KEY is set, else Anthropic; "anthropic" forces
    # Claude. With no key configured the app still works (deterministic fallback).
    llm_provider: str = "openai"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    # Tailoring is deliberately on the cheap model: generation happens per job on
    # a Telegram button tap, so cost-per-document matters more than max polish.
    openai_tailor_model: str = "gpt-4o-mini"
    openai_parse_model: str = "gpt-4o-mini"

    # --- Telegram bot (notifications + the primary action surface) ---
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
