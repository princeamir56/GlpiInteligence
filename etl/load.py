"""PostgreSQL loaders with idempotent upserts via staging tables."""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import ETLConfig

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Columns persisted to dim_tickets_enriched (order doesn't matter, names do).
TICKET_COLUMNS = (
    "id", "name", "content", "status", "type", "priority", "itilcategories_id",
    "date", "date_mod", "solvedate", "closedate", "time_to_resolve",
    "user_requester", "user_assign", "entities_id", "groups_id_requester",
    "urgency", "impact", "is_resolved", "is_high_priority",
    "resolution_days", "name_normalized",
)

DIM_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "dim_users":      ("id", "name", "realname", "firstname", "is_active", "entities_id", "groups_id"),
    "dim_entities":   ("id", "name", "completename", "entities_id", "level"),
    "dim_categories": ("id", "name", "completename", "itilcategories_id"),
    "dim_groups":     ("id", "name", "completename", "groups_id", "entities_id"),
}


def get_engine(config: ETLConfig | None = None) -> Engine:
    cfg = config or ETLConfig.from_env()
    return create_engine(cfg.postgres_url, future=True)


def ensure_schema(engine: Engine, schema_sql: str | None = None) -> None:
    """Create warehouse tables if they don't already exist."""
    ddl = schema_sql if schema_sql is not None else SCHEMA_PATH.read_text(encoding="utf-8")
    with engine.begin() as conn:
        # Execute each statement separately for engines (sqlite) that can't take batches.
        for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
            conn.execute(text(stmt))


def _upsert_via_staging(
    engine: Engine,
    df: pd.DataFrame,
    *,
    target: str,
    columns: Iterable[str],
    pk: str = "id",
) -> int:
    """Stage df then INSERT ... ON CONFLICT (pk) DO UPDATE. Returns row count."""
    cols = [c for c in columns if c in df.columns]
    if df.empty or not cols:
        logger.info("load: nothing to upsert into %s", target)
        return 0

    staging = f"_stg_{target}"
    payload = df[cols].copy()

    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {staging}"))
        payload.head(0).to_sql(staging, conn, index=False)  # create with column types from pandas
        payload.to_sql(staging, conn, if_exists="append", index=False)

        col_list = ", ".join(cols)
        update_set = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != pk)
        sql = (
            f"INSERT INTO {target} ({col_list}) "
            f"SELECT {col_list} FROM {staging} WHERE true "
            f"ON CONFLICT ({pk}) DO UPDATE SET {update_set}"
        )
        conn.execute(text(sql))
        conn.execute(text(f"DROP TABLE {staging}"))

    logger.info("load: upserted %d rows into %s", len(payload), target)
    return len(payload)


def load_tickets(engine: Engine, df: pd.DataFrame) -> int:
    return _upsert_via_staging(engine, df, target="dim_tickets_enriched", columns=TICKET_COLUMNS)


def load_dimension(engine: Engine, table: str, rows: list[dict]) -> int:
    if table not in DIM_TABLE_COLUMNS:
        raise ValueError(f"unknown dimension table: {table}")
    df = pd.DataFrame(rows)
    return _upsert_via_staging(engine, df, target=table, columns=DIM_TABLE_COLUMNS[table])


def load_daily_kpis(engine: Engine, day: date, kpis: dict) -> None:
    payload = {
        "date": day,
        "total_tickets": int(kpis.get("total_tickets", 0)),
        "resolved_pct": float(kpis.get("resolved_pct", 0.0)),
        "high_priority_count": int(kpis.get("high_priority_count", 0)),
        "avg_resolution_days": float(kpis.get("avg_resolution_days", 0.0)),
    }
    sql = text(
        """
        INSERT INTO fact_kpis_daily
            (date, total_tickets, resolved_pct, high_priority_count, avg_resolution_days)
        VALUES
            (:date, :total_tickets, :resolved_pct, :high_priority_count, :avg_resolution_days)
        ON CONFLICT (date) DO UPDATE SET
            total_tickets       = EXCLUDED.total_tickets,
            resolved_pct        = EXCLUDED.resolved_pct,
            high_priority_count = EXCLUDED.high_priority_count,
            avg_resolution_days = EXCLUDED.avg_resolution_days,
            computed_at         = NOW()
        """
    )
    with engine.begin() as conn:
        conn.execute(sql, payload)
    logger.info("load: KPI upserted for %s", day)
