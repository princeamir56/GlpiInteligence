"""Celery task definitions for heavy ETL work.

The Airflow DAG dispatches these via `.delay()` and waits on the AsyncResult,
so the scheduler isn't blocked by long-running pandas/load work.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime
from typing import Any

from celery import Celery

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "glpi_etl",
    broker=REDIS_URL,
    backend=REDIS_URL,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


@celery_app.task(name="etl.transform_tickets")
def transform_tickets_task(raw_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Run TicketTransformer on raw rows. Returns dict with records + KPIs."""
    from .transform import TicketTransformer

    transformer = TicketTransformer()
    df = transformer.transform(raw_rows)
    kpis = TicketTransformer.compute_kpis(df)
    # Serialize datetimes as ISO strings for JSON.
    records = df.assign(
        **{
            c: df[c].dt.strftime("%Y-%m-%d %H:%M:%S").where(df[c].notna(), None)
            for c in ("date", "date_mod", "solvedate", "closedate", "time_to_resolve")
            if c in df.columns
        }
    ).where(df.notna(), None).to_dict(orient="records")
    return {"records": records, "kpis": kpis, "row_count": len(records)}


@celery_app.task(name="etl.load_tickets")
def load_tickets_task(records: list[dict[str, Any]]) -> int:
    import pandas as pd
    from .config import ETLConfig
    from .load import ensure_schema, get_engine, load_tickets, resolve_fk_display_names

    engine = get_engine(ETLConfig.from_env())
    ensure_schema(engine)
    df = pd.DataFrame(records)
    for col in ("date", "date_mod", "solvedate", "closedate", "time_to_resolve"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    # FK columns are BIGINT in the warehouse but GLPI /search returns display
    # names for them (e.g. entities_id = "Root entity > Usine A"). Resolve those
    # strings back to real ids against the dimension tables — coercing them
    # straight to numeric would satisfy the BIGINT type and null out every FK.
    df = resolve_fk_display_names(engine, df)
    return load_tickets(engine, df)


@celery_app.task(name="etl.load_dimensions")
def load_dimensions_task(payload: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    from .config import ETLConfig
    from .load import ensure_schema, get_engine, load_dimension

    engine = get_engine(ETLConfig.from_env())
    ensure_schema(engine)
    result: dict[str, int] = {}
    for table, rows in payload.items():
        result[table] = load_dimension(engine, table, rows)
    return result


@celery_app.task(name="etl.load_kpis")
def load_kpis_task(kpis: dict[str, Any], day_iso: str | None = None) -> str:
    from .config import ETLConfig
    from .load import ensure_schema, get_engine, load_daily_kpis

    day = date.fromisoformat(day_iso) if day_iso else datetime.utcnow().date()
    engine = get_engine(ETLConfig.from_env())
    ensure_schema(engine)
    load_daily_kpis(engine, day, kpis)
    return day.isoformat()
