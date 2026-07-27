"""ML-engine configuration.

Reuses layer-2's Postgres access (the `POSTGRES_URL` env var consumed by
`etl.config.ETLConfig`) so there are no new credentials to manage. When running
under Airflow, values can be supplied as Airflow Variables and are hydrated into
`os.environ` here, mirroring `etl.config`.

Nothing in this module imports Airflow at module import time.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Airflow Variables we opportunistically copy into the environment.
_ML_VARS = (
    "POSTGRES_URL",
    "MLFLOW_TRACKING_URI",
    "MLFLOW_ARTIFACT_ROOT",
    "ML_MODEL_CACHE_DIR",
    "ML_COLD_START_MIN_ROWS",
)

# Sensible defaults ---------------------------------------------------------
DEFAULT_POSTGRES_URL = "postgresql+psycopg2://glpi:glpi@postgres:5432/glpi_dw"
# A DATABASE backend is required for the MLflow *model registry* (stages /
# Production). A plain file store (`file:./mlruns`) silently cannot register
# models, so we default to SQLite, which needs no extra service.
DEFAULT_TRACKING_URI = "sqlite:///mlflow.db"
DEFAULT_ARTIFACT_ROOT = "./mlartifacts"
DEFAULT_CACHE_DIR = "./.model_cache"
DEFAULT_EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_SPACY_MODEL = "fr_core_news_sm"

RANDOM_STATE = 42               # pinned everywhere it is supported
COLD_START_MIN_ROWS = 100       # below this we skip training / fall back


def _hydrate_from_airflow() -> None:
    """Copy ML_* Airflow Variables into os.environ — but only when Airflow is
    ALREADY imported (i.e. we're really inside a worker/scheduler).

    We deliberately do NOT trigger a fresh Airflow import here: a partial import
    leaves Airflow's SQLAlchemy ORM half-registered, which then breaks MLflow's
    SQLite store (`configure_mappers()` fails). Outside Airflow the vars come
    from the environment / .env, so there is nothing to hydrate.
    """
    import sys

    if "airflow" not in sys.modules:
        return
    try:
        from airflow.models import Variable  # type: ignore
    except Exception:
        return
    for key in _ML_VARS:
        if os.getenv(key):
            continue
        try:
            val = Variable.get(key, default_var=None)
        except Exception:
            val = None
        if val:
            os.environ[key] = val


@dataclass(frozen=True)
class MLConfig:
    postgres_url: str
    tracking_uri: str
    artifact_root: str
    model_cache_dir: str
    embedding_model: str
    spacy_model: str
    cold_start_min_rows: int
    random_state: int
    # forecasting / clustering knobs
    top_n_categories: int = 10
    forecast_horizon_hours: int = 72
    sla_horizon_hours: int = 48
    kmeans_k: int = 10
    dbscan_eps: float = 0.5
    dbscan_min_samples: int = 5
    experiment_name: str = "glpi_ml_engine"
    registry_stage: str = "Production"
    extra: dict = field(default_factory=dict)

    @staticmethod
    def from_env() -> "MLConfig":
        _hydrate_from_airflow()
        return MLConfig(
            postgres_url=os.getenv("POSTGRES_URL", DEFAULT_POSTGRES_URL),
            tracking_uri=os.getenv("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI),
            artifact_root=os.getenv("MLFLOW_ARTIFACT_ROOT", DEFAULT_ARTIFACT_ROOT),
            model_cache_dir=os.getenv("ML_MODEL_CACHE_DIR", DEFAULT_CACHE_DIR),
            embedding_model=os.getenv("ML_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
            spacy_model=os.getenv("ML_SPACY_MODEL", DEFAULT_SPACY_MODEL),
            cold_start_min_rows=int(
                os.getenv("ML_COLD_START_MIN_ROWS", str(COLD_START_MIN_ROWS))
            ),
            random_state=int(os.getenv("ML_RANDOM_STATE", str(RANDOM_STATE))),
            top_n_categories=int(os.getenv("ML_TOP_N_CATEGORIES", "10")),
            kmeans_k=int(os.getenv("ML_KMEANS_K", "10")),
        )
