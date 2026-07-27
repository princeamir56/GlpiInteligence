"""API configuration via pydantic-settings.

All secrets and connection strings come from the environment / `.env` — nothing is
hard-coded. The Postgres URL is reused from the layer-2/3 `POSTGRES_URL` and coerced
to the async `asyncpg` driver so SQLAlchemy 2.x async works out of the box.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _to_asyncpg(url: str) -> str:
    """Coerce a psycopg2/plain Postgres URL to the async `asyncpg` dialect."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- Database (reused from layer 2/3) ----
    postgres_url: str = Field(
        default="postgresql+psycopg2://glpi:glpi@postgres:5432/glpi_dw",
        alias="POSTGRES_URL",
    )
    db_pool_size: int = Field(default=5, alias="API_DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="API_DB_MAX_OVERFLOW")
    db_echo: bool = Field(default=False, alias="API_DB_ECHO")

    # ---- Redis cache (reused from layer 2) ----
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    cache_ttl_overview: int = Field(default=60, alias="API_CACHE_TTL_OVERVIEW")
    cache_ttl_heavy: int = Field(default=300, alias="API_CACHE_TTL_HEAVY")

    # ---- Auth / JWT ----
    jwt_secret: str = Field(default="change-me-in-prod", alias="API_JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", alias="API_JWT_ALGORITHM")
    access_token_ttl_min: int = Field(default=30, alias="API_ACCESS_TOKEN_TTL_MIN")
    refresh_token_ttl_days: int = Field(default=7, alias="API_REFRESH_TOKEN_TTL_DAYS")

    # ---- CORS ----
    allowed_origins: str = Field(
        default="http://localhost:4200", alias="API_ALLOWED_ORIGINS"
    )

    # ---- Rate limiting ----
    rate_limit_anon: str = Field(default="100/minute", alias="API_RATE_LIMIT_ANON")
    rate_limit_auth: str = Field(default="300/minute", alias="API_RATE_LIMIT_AUTH")

    # ---- WebSocket alert broadcaster ----
    alert_poll_seconds: int = Field(default=10, alias="API_ALERT_POLL_SECONDS")

    @field_validator("postgres_url")
    @classmethod
    def _coerce_async(cls, v: str) -> str:
        return _to_asyncpg(v)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
