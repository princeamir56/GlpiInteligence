"""PostgreSQL loaders with idempotent upserts via staging tables."""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import ETLConfig
from .transform import flatten_glpi_value

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


# FK column -> (dimension table, candidate name columns to index).
# `dim_users` has no completename; its display form is assembled from
# realname/firstname, so it is handled separately in _lookup_map.
FK_RESOLUTION: dict[str, str] = {
    "itilcategories_id": "dim_categories",
    "entities_id": "dim_entities",
    "groups_id_requester": "dim_groups",
    "user_requester": "dim_users",
    "user_assign": "dim_users",
}

_WS_RE = re.compile(r"\s+")


def _norm(value: object) -> str | None:
    """Casefold + collapse whitespace so 'Root entity  >  Usine A' matches."""
    if value is None:
        return None
    s = _WS_RE.sub(" ", str(value)).strip()
    if not s or s.lower() in ("nan", "none", "<na>"):
        return None
    # GLPI renders tree paths with ' > '; normalize the separator spacing.
    s = " > ".join(p.strip() for p in s.split(">"))
    return s.casefold()


def _lookup_map(engine: Engine, table: str) -> dict[str, int]:
    """Build {normalized display name -> id} for a dimension table.

    Several spellings are indexed per row (name, completename, and for users
    both 'realname firstname' and 'firstname realname') because which one GLPI
    renders depends on the instance's display preferences. The leaf name is
    also indexed for tree dimensions so 'Usine A' resolves as well as the full
    path. First writer wins, so more specific keys are inserted first.
    """
    if table == "dim_users":
        cols = "id, name, realname, firstname"
    elif table == "dim_categories":
        cols = "id, name, completename"
    else:
        cols = "id, name, completename"

    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT {cols} FROM {table}")).mappings().all()

    out: dict[str, int] = {}

    def put(key: object, ident: int) -> None:
        k = _norm(key)
        if k and k not in out:
            out[k] = ident

    for r in rows:
        ident = int(r["id"])
        if table == "dim_users":
            realname, firstname = r.get("realname") or "", r.get("firstname") or ""
            put(f"{realname} {firstname}", ident)
            put(f"{firstname} {realname}", ident)
            put(r.get("name"), ident)
        else:
            put(r.get("completename"), ident)
            put(r.get("name"), ident)
            # leaf of a 'A > B > C' path
            comp = r.get("completename")
            if comp and ">" in str(comp):
                put(str(comp).split(">")[-1], ident)
    return out


def resolve_fk_display_names(engine: Engine, df: pd.DataFrame) -> pd.DataFrame:
    """Fill NA FK ids from their preserved ``<col>_display`` strings.

    GLPI ``/search`` returns display names (not ids) for dropdown-backed
    columns, so a plain ``to_numeric`` coercion nulls every one of them. Here
    the display string is matched back against the already-loaded dimension
    tables. Rows that still cannot be matched stay NA and are counted in the
    log so the miss rate is visible rather than silent.
    """
    for col, table in FK_RESOLUTION.items():
        display_col = f"{col}_display"
        if col not in df.columns or display_col not in df.columns:
            continue

        missing = df[col].isna() & df[display_col].notna()
        if not missing.any():
            continue

        try:
            mapping = _lookup_map(engine, table)
        except Exception:
            logger.warning("resolve_fk: cannot read %s, skipping %s", table, col, exc_info=True)
            continue
        if not mapping:
            logger.warning(
                "resolve_fk: %s is empty — load dimensions before tickets; "
                "%d %s values left unresolved", table, int(missing.sum()), col,
            )
            continue

        resolved = df.loc[missing, display_col].map(lambda v: mapping.get(_norm(v)))
        df.loc[missing, col] = resolved.astype("Int64")

        hits = int(resolved.notna().sum())
        total = int(missing.sum())
        logger.info(
            "resolve_fk: %s -> %s resolved %d/%d (%d unmatched)",
            col, table, hits, total, total - hits,
        )
        if hits < total:
            sample = sorted(
                {str(v) for v in df.loc[missing & df[col].isna(), display_col].head(5)}
            )
            logger.warning("resolve_fk: unmatched %s samples: %s", col, sample)

    for col in FK_RESOLUTION:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    return df


def load_tickets(engine: Engine, df: pd.DataFrame) -> int:
    return _upsert_via_staging(engine, df, target="dim_tickets_enriched", columns=TICKET_COLUMNS)


# Target warehouse types per dimension column. pandas infers the staging table's
# types from the DataFrame, so without this GLPI's 0/1 integers land in a BIGINT
# staging column and the INSERT into a BOOLEAN column fails with DatatypeMismatch
# ("column is_active is of type boolean but expression is of type bigint").
DIM_COLUMN_CASTS: dict[str, dict[str, str]] = {
    "dim_users":      {"id": "int", "is_active": "bool", "entities_id": "int",
                       "name": "str", "realname": "str", "firstname": "str",
                       "groups_id": "str"},
    "dim_entities":   {"id": "int", "entities_id": "int", "level": "int",
                       "name": "str", "completename": "str"},
    "dim_categories": {"id": "int", "itilcategories_id": "int",
                       "name": "str", "completename": "str"},
    "dim_groups":     {"id": "int", "groups_id": "int", "entities_id": "int",
                       "name": "str", "completename": "str"},
}

_TRUEISH = {"1", "true", "t", "yes", "y", "on"}
_FALSEISH = {"0", "false", "f", "no", "n", "off", "", "none", "nan"}


def _to_bool(value: object) -> object:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return pd.NA
    if isinstance(value, bool):
        return value
    s = str(value).strip().casefold()
    if s in _TRUEISH:
        return True
    if s in _FALSEISH:
        return False
    return pd.NA


def _coerce_dim_types(table: str, df: pd.DataFrame) -> pd.DataFrame:
    casts = DIM_COLUMN_CASTS.get(table, {})
    for col, kind in casts.items():
        if col not in df.columns:
            continue
        if kind == "bool":
            df[col] = df[col].map(_to_bool).astype("boolean")
        elif kind == "int":
            df[col] = pd.to_numeric(
                df[col].map(flatten_glpi_value), errors="coerce"
            ).astype("Int64")
        else:  # str — GLPI sometimes returns lists/dicts for these
            df[col] = df[col].map(
                lambda v: None if v is None else str(flatten_glpi_value(v))
                if not isinstance(v, (list, dict)) else str(v)
            ).astype("string")
    return df


def load_dimension(engine: Engine, table: str, rows: list[dict]) -> int:
    if table not in DIM_TABLE_COLUMNS:
        raise ValueError(f"unknown dimension table: {table}")
    df = pd.DataFrame(rows)
    df = _coerce_dim_types(table, df)
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
