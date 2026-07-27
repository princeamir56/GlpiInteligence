"""Feature engineering — pure pandas, zero Airflow/DB imports.

Each public function takes the raw `dim_tickets_enriched` DataFrame (same column
names layer 2 writes) and returns a feature DataFrame for one model. Keeping the
feature code here (not inside the model modules) lets the retrain DAG, tests and
notebooks build features identically.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# GLPI status/priority conventions (mirrors etl.transform).
RESOLVED_STATUSES = (5, 6)
HIGH_PRIORITY_LEVELS = (5, 6)
INCIDENT_TYPE = 1   # GLPI: 1 = incident, 2 = request
REQUEST_TYPE = 2
REPETITIVE_MIN = 3  # a normalized title seen >= 3 times counts as repetitive


def dataframe_hash(df: pd.DataFrame) -> str:
    """Stable hash of a DataFrame's contents — logged to MLflow for repro."""
    try:
        row_hashes = pd.util.hash_pandas_object(df, index=True).values
        return hashlib.sha256(row_hashes.tobytes()).hexdigest()
    except Exception:  # pragma: no cover - defensive
        return hashlib.sha256(df.to_csv(index=True).encode("utf-8")).hexdigest()


def _months_active(dates: pd.Series) -> float:
    valid = pd.to_datetime(dates, errors="coerce").dropna()
    if valid.empty:
        return 1.0
    span_days = (valid.max() - valid.min()).total_seconds() / 86400.0
    return max(span_days / 30.0, 1.0)  # at least one month to avoid div/0


# --------------------------------------------------------------------------- #
# 3.1  User classification features
# --------------------------------------------------------------------------- #
USER_FEATURE_COLUMNS: tuple[str, ...] = (
    "total_tickets",
    "incidents_count",
    "requests_count",
    "resolved_count",
    "open_count",
    "high_priority_count",
    "repetitive_count",
    "avg_resolution_days",
    "tickets_per_month",
)


def build_user_features(tickets: pd.DataFrame) -> pd.DataFrame:
    """One row per requester with the 9 behaviour features.

    Index is `user_id` (from `user_requester`). Empty input -> empty frame with
    the right columns so downstream code never KeyErrors.
    """
    cols = ["user_id", *USER_FEATURE_COLUMNS]
    if tickets is None or tickets.empty or "user_requester" not in tickets.columns:
        return pd.DataFrame(columns=cols).set_index("user_id")

    df = tickets.copy()
    df = df[df["user_requester"].notna()]
    if df.empty:
        return pd.DataFrame(columns=cols).set_index("user_id")

    status = pd.to_numeric(df.get("status"), errors="coerce")
    ttype = pd.to_numeric(df.get("type"), errors="coerce")
    prio = pd.to_numeric(df.get("priority"), errors="coerce")
    df = df.assign(
        _resolved=status.isin(RESOLVED_STATUSES),
        _incident=(ttype == INCIDENT_TYPE),
        _request=(ttype == REQUEST_TYPE),
        _high=prio.isin(HIGH_PRIORITY_LEVELS),
        _resdays=pd.to_numeric(df.get("resolution_days"), errors="coerce"),
    )

    rows = []
    for user_id, g in df.groupby("user_requester"):
        total = len(g)
        # repetitive: titles this user raised >= REPETITIVE_MIN times
        norm = g.get("name_normalized")
        if norm is not None:
            vc = norm[norm.astype(bool)].value_counts()
            repetitive = int(vc[vc >= REPETITIVE_MIN].sum())
        else:
            repetitive = 0
        avg_res = g.loc[g["_resolved"], "_resdays"].mean()
        rows.append(
            {
                "user_id": int(user_id),
                "total_tickets": int(total),
                "incidents_count": int(g["_incident"].sum()),
                "requests_count": int(g["_request"].sum()),
                "resolved_count": int(g["_resolved"].sum()),
                "open_count": int((~g["_resolved"]).sum()),
                "high_priority_count": int(g["_high"].sum()),
                "repetitive_count": repetitive,
                "avg_resolution_days": float(avg_res) if pd.notna(avg_res) else 0.0,
                "tickets_per_month": round(total / _months_active(g.get("date")), 3),
            }
        )
    out = pd.DataFrame(rows, columns=cols).set_index("user_id")
    logger.info("build_user_features: %d users", len(out))
    return out


# --------------------------------------------------------------------------- #
# 3.2a  Volume forecasting features (daily counts per category)
# --------------------------------------------------------------------------- #
def build_daily_category_counts(
    tickets: pd.DataFrame, top_n: int = 10
) -> dict[int, pd.DataFrame]:
    """Return {category_id: DataFrame[ds, y]} of daily counts for the top-N
    categories by volume. `ds`/`y` are the column names Prophet expects."""
    if tickets is None or tickets.empty or "date" not in tickets.columns:
        return {}
    df = tickets.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "itilcategories_id"])
    if df.empty:
        return {}
    df["itilcategories_id"] = pd.to_numeric(
        df["itilcategories_id"], errors="coerce"
    ).astype("Int64")
    df = df.dropna(subset=["itilcategories_id"])
    top = df["itilcategories_id"].value_counts().head(top_n).index.tolist()

    result: dict[int, pd.DataFrame] = {}
    for cat in top:
        sub = df[df["itilcategories_id"] == cat]
        daily = (
            sub.set_index("date")
            .resample("D")
            .size()
            .rename("y")
            .reset_index()
            .rename(columns={"date": "ds"})
        )
        result[int(cat)] = daily
    logger.info("build_daily_category_counts: %d categories", len(result))
    return result


# --------------------------------------------------------------------------- #
# 3.2b  SLA-risk features (one row per technician)
# --------------------------------------------------------------------------- #
SLA_FEATURE_COLUMNS: tuple[str, ...] = (
    "current_open_tickets",
    "tickets_last_7_days",
    "avg_resolution_days_last_30_days",
    "high_priority_ratio",
    "historical_sla_pct",
)


def _sla_violation_flag(g: pd.DataFrame) -> pd.Series:
    """A resolved ticket violated SLA if it was solved/closed after its
    `time_to_resolve` deadline (a TIMESTAMP in layer 2). Unresolved & past
    deadline also counts as a violation."""
    ttr = pd.to_datetime(g.get("time_to_resolve"), errors="coerce")
    solved = pd.to_datetime(g.get("solvedate"), errors="coerce")
    closed = pd.to_datetime(g.get("closedate"), errors="coerce")
    done = solved.fillna(closed)
    violated = (done.notna() & (done > ttr)) | (done.isna() & ttr.notna())
    return violated.fillna(False)


def build_sla_features(
    tickets: pd.DataFrame, *, now: pd.Timestamp | None = None
) -> pd.DataFrame:
    """One row per technician (`user_assign`) with SLA features + `sla_violation`
    label (was there a violation among their recent tickets)."""
    cols = ["technician_id", *SLA_FEATURE_COLUMNS, "sla_violation"]
    if tickets is None or tickets.empty or "user_assign" not in tickets.columns:
        return pd.DataFrame(columns=cols).set_index("technician_id")

    now = now or pd.Timestamp.utcnow().tz_localize(None)
    df = tickets.copy()
    df = df[df["user_assign"].notna()]
    if df.empty:
        return pd.DataFrame(columns=cols).set_index("technician_id")

    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    status = pd.to_numeric(df.get("status"), errors="coerce")
    prio = pd.to_numeric(df.get("priority"), errors="coerce")
    df = df.assign(
        _resolved=status.isin(RESOLVED_STATUSES),
        _high=prio.isin(HIGH_PRIORITY_LEVELS),
        _resdays=pd.to_numeric(df.get("resolution_days"), errors="coerce"),
        _violated=_sla_violation_flag(df),
    )
    d7 = now - pd.Timedelta(days=7)
    d30 = now - pd.Timedelta(days=30)

    rows = []
    for tech, g in df.groupby("user_assign"):
        total = len(g)
        last7 = int((g["date"] >= d7).sum())
        recent30 = g[g["date"] >= d30]
        avg30 = recent30.loc[recent30["_resolved"], "_resdays"].mean()
        resolved = g[g["_resolved"]]
        # historical SLA pct = share of resolved tickets that met the deadline
        if len(resolved):
            sla_pct = float((~resolved["_violated"]).mean() * 100.0)
        else:
            sla_pct = 100.0
        rows.append(
            {
                "technician_id": int(tech),
                "current_open_tickets": int((~g["_resolved"]).sum()),
                "tickets_last_7_days": last7,
                "avg_resolution_days_last_30_days": float(avg30)
                if pd.notna(avg30)
                else 0.0,
                "high_priority_ratio": round(g["_high"].mean(), 4) if total else 0.0,
                "historical_sla_pct": round(sla_pct, 2),
                "sla_violation": int(g["_violated"].any()),
            }
        )
    out = pd.DataFrame(rows, columns=cols).set_index("technician_id")
    logger.info("build_sla_features: %d technicians", len(out))
    return out


# --------------------------------------------------------------------------- #
# 3.3  NLP corpus (text per ticket for clustering)
# --------------------------------------------------------------------------- #
def build_text_corpus(
    tickets: pd.DataFrame, *, min_chars: int = 3
) -> pd.DataFrame:
    """DataFrame[id, itilcategories_id, date, text] where text = name + content.

    NOTE: follow-up content is not persisted by layer 2 yet (see project spec /
    mismatch #2). When a `dim_followups` table is added, concatenate its
    `content` here keyed by ticket id.
    """
    cols = ["id", "itilcategories_id", "date", "text"]
    if tickets is None or tickets.empty:
        return pd.DataFrame(columns=cols)
    df = tickets.copy()
    name = df.get("name", "").fillna("") if "name" in df else ""
    content = df.get("content", "").fillna("") if "content" in df else ""
    df["text"] = (name.astype(str) + ". " + content.astype(str)).str.strip()
    df = df[df["text"].str.len() >= min_chars]
    keep = [c for c in cols if c in df.columns or c == "text"]
    for c in cols:
        if c not in df.columns:
            df[c] = pd.NA
    logger.info("build_text_corpus: %d documents", len(df))
    return df[cols].reset_index(drop=True)


def select_features(df: pd.DataFrame, columns: Sequence[str]) -> np.ndarray:
    """Return a numeric matrix for the given feature columns (NaN -> 0)."""
    mat = df.reindex(columns=list(columns)).apply(
        pd.to_numeric, errors="coerce"
    )
    return mat.fillna(0.0).to_numpy(dtype=float)
