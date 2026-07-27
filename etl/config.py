"""ETL configuration.

Provides a single `get_glpi_config()` that reuses `glpi_connector.config.GLPIConfig`.
When running under Airflow, GLPI credentials are pulled from Airflow Variables and
injected into the process environment so that `GLPIConfig.from_env()` keeps working
without modification. Outside Airflow, it falls back to the standard `.env` file.

Postgres and Redis URLs are pulled from env vars (set by docker-compose).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from glpi_connector.config import GLPIConfig

logger = logging.getLogger(__name__)

_GLPI_VARS = ("GLPI_BASE_URL", "GLPI_APP_TOKEN", "GLPI_USER_TOKEN")


def _hydrate_from_airflow() -> None:
    """If Airflow is importable, copy GLPI_* Airflow Variables into os.environ."""
    try:
        from airflow.models import Variable  # type: ignore
    except Exception:
        return
    for key in _GLPI_VARS:
        if os.getenv(key):
            continue
        try:
            val = Variable.get(key, default_var=None)
        except Exception:
            val = None
        if val:
            os.environ[key] = val


def get_glpi_config() -> GLPIConfig:
    """Return a `GLPIConfig`, sourcing creds from Airflow Variables if available."""
    _hydrate_from_airflow()
    return GLPIConfig.from_env()


@dataclass(frozen=True)
class ETLConfig:
    postgres_url: str
    redis_url: str
    cache_ttl_live: int = 300       # 5 min
    cache_ttl_aggregate: int = 3600  # 1 h

    @staticmethod
    def from_env() -> "ETLConfig":
        pg = os.getenv("POSTGRES_URL", "postgresql+psycopg2://glpi:glpi@postgres:5432/glpi_dw")
        redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        return ETLConfig(
            postgres_url=pg,
            redis_url=redis_url,
            cache_ttl_live=int(os.getenv("CACHE_TTL_LIVE", "300")),
            cache_ttl_aggregate=int(os.getenv("CACHE_TTL_AGG", "3600")),
        )
