"""Shared WHERE-clause builders and SQL fragments for dim_tickets_enriched.

GLPI conventions used here:
- ticket `type`: 1 = incident, 2 = request.
- ticket `status`: 5 = solved, 6 = closed (everything else is "open").
- `is_resolved` boolean is precomputed by layer 2.
- `time_to_resolve` is an SLA DEADLINE timestamp (not a duration): an SLA is met
  when the ticket was solved on/before that deadline.
"""
from __future__ import annotations

from typing import Any

from ..schemas.common import CommonFilters

# A ticket meets SLA if solved and (no deadline OR solved on/before the deadline).
SLA_MET_EXPR = (
    "(solvedate IS NOT NULL AND "
    "(time_to_resolve IS NULL OR solvedate <= time_to_resolve))"
)
IS_OPEN_EXPR = "(is_resolved IS NOT TRUE)"

def user_name_expr(id_col: str) -> str:
    """Display name for a LEFT JOINed dim_users row `u`.

    `id_col` is the *fact-side* id column (e.g. "t.user_assign"). The final
    fallback must use it rather than `u.id`: when the join misses — a ticket
    referencing a user absent from dim_users — every `u.*` column is NULL, so
    a `u.id` fallback yields NULL and trips the non-optional `name` field in
    the response schema (a 500 on the whole endpoint).
    """
    return (
        "COALESCE(NULLIF(TRIM(COALESCE(u.realname,'')||' '||COALESCE(u.firstname,'')), ''), "
        f"u.name, 'user #'||{id_col}::text, 'Inconnu')"
    )


def ticket_filters(
    f: CommonFilters, *, prefix: str = ""
) -> tuple[str, dict[str, Any]]:
    """Build an AND-joined WHERE fragment (no leading WHERE/AND) + bound params.

    `prefix` is an optional table alias qualifier, e.g. "t." -> "t.date".
    """
    col = lambda c: f"{prefix}{c}"  # noqa: E731
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if f.start_date is not None:
        clauses.append(f"{col('date')} >= :start_date")
        params["start_date"] = f.start_date
    if f.end_date is not None:
        # inclusive upper bound on the day
        clauses.append(f"{col('date')} < (:end_date::date + INTERVAL '1 day')")
        params["end_date"] = f.end_date
    if f.entity_id is not None:
        clauses.append(f"{col('entities_id')} = :entity_id")
        params["entity_id"] = f.entity_id
    if f.category_id is not None:
        clauses.append(f"{col('itilcategories_id')} = :category_id")
        params["category_id"] = f.category_id
    sql = " AND ".join(clauses) if clauses else "TRUE"
    return sql, params


def where(f: CommonFilters, *, prefix: str = "") -> tuple[str, dict[str, Any]]:
    frag, params = ticket_filters(f, prefix=prefix)
    return f"WHERE {frag}", params


def cache_key(name: str, f: CommonFilters) -> str:
    return (
        f"{name}:{f.start_date}:{f.end_date}:{f.limit}:{f.entity_id}:{f.category_id}"
    )
