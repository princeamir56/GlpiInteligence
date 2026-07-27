"""Pure-pandas transformations for the GLPI ticket pipeline.

This module has zero Airflow / Celery / DB imports so it is unit-testable in isolation.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Map of raw extractor field -> warehouse column name. The extractor in layer 1
# emits some columns with a leading underscore (private GLPI search options);
# we normalize them here without touching layer 1.
RAW_TO_CANONICAL: dict[str, str] = {
    "id": "id",
    "name": "name",
    "content": "content",
    "status": "status",
    "type": "type",
    "priority": "priority",
    "itilcategories_id": "itilcategories_id",
    "date": "date",
    "date_mod": "date_mod",
    "solvedate": "solvedate",
    "closedate": "closedate",
    "time_to_resolve": "time_to_resolve",
    "_users_id_requester": "user_requester",
    "_users_id_assign": "user_assign",
    "entities_id": "entities_id",
    "_groups_id_requester": "groups_id_requester",
    "urgency": "urgency",
    "impact": "impact",
}

DATE_COLUMNS = ("date", "date_mod", "solvedate", "closedate", "time_to_resolve")
RESOLVED_STATUSES = (5, 6)         # GLPI: 5=solved, 6=closed
HIGH_PRIORITY_LEVELS = (5, 6)      # GLPI: 5=very high, 6=major

_PREFIX_RE = re.compile(r"^\s*(?:tr|re|fwd|fw)\s*:\s*", flags=re.IGNORECASE)


def normalize_title(title: Any) -> str:
    """Lowercase, strip leading reply/forward prefixes. Empty/None -> ''."""
    if title is None or (isinstance(title, float) and np.isnan(title)):
        return ""
    s = str(title).strip().lower()
    # strip repeated prefixes like "re: tr: hello"
    while True:
        new = _PREFIX_RE.sub("", s, count=1)
        if new == s:
            break
        s = new
    return s.strip()


class TicketTransformer:
    """Transform a list of raw GLPI ticket dicts into a clean DataFrame + KPIs."""

    def __init__(self, raw_to_canonical: dict[str, str] | None = None) -> None:
        self.mapping = raw_to_canonical or RAW_TO_CANONICAL

    # ------------------------------------------------------------------ steps
    def to_dataframe(self, rows: Iterable[dict[str, Any]]) -> pd.DataFrame:
        df = pd.DataFrame(list(rows))
        if df.empty:
            return pd.DataFrame(columns=list(self.mapping.values()))
        # rename only known columns; drop the rest to keep the schema stable
        present = {k: v for k, v in self.mapping.items() if k in df.columns}
        df = df.rename(columns=present)
        for canonical in self.mapping.values():
            if canonical not in df.columns:
                df[canonical] = pd.NA
        return df[list(self.mapping.values())]

    def parse_dates(self, df: pd.DataFrame) -> pd.DataFrame:
        for col in DATE_COLUMNS:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce", utc=False)
        return df

    def add_derived(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            df["is_resolved"] = pd.Series(dtype="boolean")
            df["is_high_priority"] = pd.Series(dtype="boolean")
            df["resolution_days"] = pd.Series(dtype="float64")
            df["name_normalized"] = pd.Series(dtype="object")
            return df

        status_num = pd.to_numeric(df["status"], errors="coerce")
        priority_num = pd.to_numeric(df["priority"], errors="coerce")
        df["is_resolved"] = status_num.isin(RESOLVED_STATUSES)
        df["is_high_priority"] = priority_num.isin(HIGH_PRIORITY_LEVELS)

        delta = df["solvedate"] - df["date"]
        df["resolution_days"] = delta.dt.total_seconds() / 86400.0

        df["name_normalized"] = df["name"].map(normalize_title)
        return df

    def transform(self, rows: Iterable[dict[str, Any]]) -> pd.DataFrame:
        df = self.to_dataframe(rows)
        df = self.parse_dates(df)
        df = self.add_derived(df)
        logger.info("TicketTransformer: %d rows transformed", len(df))
        return df

    # ---------------------------------------------------------------- KPIs
    @staticmethod
    def compute_kpis(df: pd.DataFrame) -> dict[str, float | int]:
        total = int(len(df))
        if total == 0:
            return {
                "total_tickets": 0,
                "resolved_pct": 0.0,
                "high_priority_count": 0,
                "avg_resolution_days": 0.0,
            }
        resolved_pct = float(df["is_resolved"].fillna(False).mean() * 100.0)
        high_priority_count = int(df["is_high_priority"].fillna(False).sum())
        avg_res = df.loc[df["is_resolved"] == True, "resolution_days"].mean()  # noqa: E712
        avg_resolution_days = float(avg_res) if pd.notna(avg_res) else 0.0
        return {
            "total_tickets": total,
            "resolved_pct": round(resolved_pct, 2),
            "high_priority_count": high_priority_count,
            "avg_resolution_days": round(avg_resolution_days, 2),
        }
