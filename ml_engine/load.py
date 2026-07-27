"""Upsert ML results into the `ml_*` tables + `recommendations`.

Mirrors layer-2's staging-table + INSERT ... ON CONFLICT pattern (etl/load.py).
JSON/JSONB columns are serialised to strings and cast in the INSERT so psycopg2
stores real JSONB, not text.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# columns that must be cast to jsonb on insert
_JSON_COLUMNS = {"features_snapshot", "sample_titles", "top_keywords", "evidence"}


def ensure_schema(engine: Engine, schema_sql: str | None = None) -> None:
    ddl = schema_sql if schema_sql is not None else SCHEMA_PATH.read_text(encoding="utf-8")
    with engine.begin() as conn:
        for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
            conn.execute(text(stmt))


def _jsonify(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    df = df.copy()
    for col in columns:
        if col in df.columns:
            df[col] = df[col].map(
                lambda v: None if v is None else json.dumps(v, default=str, ensure_ascii=False)
            )
    return df


def upsert(
    engine: Engine,
    df: pd.DataFrame,
    *,
    target: str,
    columns: Sequence[str],
    pk: Sequence[str],
) -> int:
    """Stage `df` then INSERT ... ON CONFLICT(pk) DO UPDATE. JSON columns are
    cast to jsonb. Returns rows upserted."""
    cols = [c for c in columns if c in df.columns]
    if df.empty or not cols:
        logger.info("ml.load: nothing to upsert into %s", target)
        return 0

    json_cols = [c for c in cols if c in _JSON_COLUMNS]
    payload = _jsonify(df[cols], json_cols)

    staging = f"_stg_{target}"
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {staging}"))
        payload.head(0).to_sql(staging, conn, index=False)
        payload.to_sql(staging, conn, if_exists="append", index=False)

        select_cols = ", ".join(
            f"CAST({c} AS JSONB) AS {c}" if c in json_cols else c for c in cols
        )
        col_list = ", ".join(cols)
        pk_list = ", ".join(pk)
        update_set = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c not in pk)
        sql = (
            f"INSERT INTO {target} ({col_list}) "
            f"SELECT {select_cols} FROM {staging} WHERE true "
            f"ON CONFLICT ({pk_list}) DO UPDATE SET {update_set}, computed_at=NOW()"
            if _has_computed_at(target)
            else f"INSERT INTO {target} ({col_list}) "
            f"SELECT {select_cols} FROM {staging} WHERE true "
            f"ON CONFLICT ({pk_list}) DO UPDATE SET {update_set}"
        )
        conn.execute(text(sql))
        conn.execute(text(f"DROP TABLE {staging}"))

    logger.info("ml.load: upserted %d rows into %s", len(payload), target)
    return len(payload)


def _has_computed_at(target: str) -> bool:
    return target in {"ml_user_profiles", "ml_forecasts", "ml_sla_risk", "ml_clusters"}


# ---- convenience wrappers per table --------------------------------------- #
def load_user_profiles(engine: Engine, df: pd.DataFrame, *, model_version: str = "") -> int:
    return upsert(
        engine, df, target="ml_user_profiles",
        columns=["user_id", "profile", "confidence", "features_snapshot"],
        pk=["user_id"],
    )


def load_forecasts(engine: Engine, df: pd.DataFrame, *, model_version: str = "") -> int:
    df = df.assign(model_version=model_version) if not df.empty else df
    return upsert(
        engine, df, target="ml_forecasts",
        columns=["category_id", "forecast_date", "predicted_count", "lower_bound",
                 "upper_bound", "confidence", "model_version"],
        pk=["category_id", "forecast_date"],
    )


def load_sla_risk(engine: Engine, df: pd.DataFrame, *, model_version: str = "") -> int:
    df = df.assign(model_version=model_version) if not df.empty else df
    return upsert(
        engine, df, target="ml_sla_risk",
        columns=["technician_id", "risk_score", "next_48h_prediction", "confidence", "model_version"],
        pk=["technician_id"],
    )


def load_clusters(engine: Engine, df: pd.DataFrame) -> int:
    return upsert(
        engine, df, target="ml_clusters",
        columns=["cluster_id", "algorithm", "sample_titles", "ticket_count",
                 "top_keywords", "severity", "neg_ratio", "first_seen", "last_seen"],
        pk=["algorithm", "cluster_id"],
    )


def load_recommendations(engine: Engine, df: pd.DataFrame) -> int:
    return upsert(
        engine, df, target="recommendations",
        columns=["id", "type", "target_user_id", "target_group_id", "target_category_id",
                 "severity", "title", "description", "evidence", "created_at", "expires_at"],
        pk=["id"],
    )
