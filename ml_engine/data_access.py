"""Read helpers for layer-2 data. Kept separate from load.py (which writes).

Reuses layer-2's SQLAlchemy engine builder so there are no new credentials.
Airflow tasks are the only place these run; the model modules never import this.
"""
from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .config import MLConfig

logger = logging.getLogger(__name__)


def get_engine(config: MLConfig | None = None) -> Engine:
    from sqlalchemy import create_engine

    cfg = config or MLConfig.from_env()
    return create_engine(cfg.postgres_url, future=True)


def read_tickets(config: MLConfig | None = None, *, engine: Engine | None = None) -> pd.DataFrame:
    """Load the full `dim_tickets_enriched` table as a DataFrame."""
    eng = engine or get_engine(config)
    df = pd.read_sql(text("SELECT * FROM dim_tickets_enriched"), eng)
    logger.info("read_tickets: %d rows from dim_tickets_enriched", len(df))
    return df


def count_recent_tickets(
    config: MLConfig | None = None, *, engine: Engine | None = None, hours: int = 24
) -> int:
    """Rows whose `date_mod` is within the last `hours` — data-freshness check."""
    eng = engine or get_engine(config)
    sql = text(
        "SELECT COUNT(*) FROM dim_tickets_enriched "
        "WHERE date_mod >= NOW() - (:hours || ' hours')::interval"
    )
    with eng.connect() as conn:
        n = conn.execute(sql, {"hours": hours}).scalar_one()
    logger.info("count_recent_tickets: %d rows modified in last %dh", n, hours)
    return int(n)
