"""Recommendation list + acknowledge queries."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas.tabs import Recommendation, RecommendationsResponse


async def list_recommendations(
    session: AsyncSession,
    *,
    user_id: int,
    reco_type: str | None,
    severity: str | None,
    limit: int,
) -> RecommendationsResponse:
    params: dict = {"limit": limit, "uid": user_id}
    clauses = ["(r.expires_at IS NULL OR r.expires_at > NOW())"]
    if reco_type is not None:
        clauses.append("r.type = :rtype")
        params["rtype"] = reco_type
    if severity is not None:
        clauses.append("r.severity = :sev")
        params["sev"] = severity
    where = " AND ".join(clauses)
    rows = (
        await session.execute(
            text(
                f"""
                SELECT r.id, r.type, r.severity, r.title, r.description,
                       r.target_user_id, r.target_group_id, r.target_category_id,
                       r.evidence, r.created_at, r.expires_at,
                       (a.recommendation_id IS NOT NULL) AS acknowledged
                FROM recommendations r
                LEFT JOIN recommendation_acks a
                       ON a.recommendation_id = r.id AND a.user_id = :uid
                WHERE {where}
                ORDER BY CASE r.severity
                    WHEN 'CRITIQUE' THEN 0 WHEN 'ÉLEVÉ' THEN 1
                    WHEN 'MODÉRÉ' THEN 2 ELSE 3 END, r.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        )
    ).all()
    items = [
        Recommendation(
            id=r.id,
            type=r.type,
            severity=r.severity,
            title=r.title,
            description=r.description,
            target_user_id=r.target_user_id,
            target_group_id=r.target_group_id,
            target_category_id=r.target_category_id,
            evidence=r.evidence,
            created_at=r.created_at,
            expires_at=r.expires_at,
            acknowledged=bool(r.acknowledged),
        )
        for r in rows
    ]
    return RecommendationsResponse(items=items)


async def recommendation_exists(session: AsyncSession, reco_id: str) -> bool:
    return (
        await session.execute(
            text("SELECT 1 FROM recommendations WHERE id = :id"), {"id": reco_id}
        )
    ).first() is not None


async def acknowledge(
    session: AsyncSession, reco_id: str, user_id: int
) -> datetime:
    row = (
        await session.execute(
            text(
                """
                INSERT INTO recommendation_acks (recommendation_id, user_id)
                VALUES (:rid, :uid)
                ON CONFLICT (recommendation_id, user_id)
                DO UPDATE SET acknowledged_at = NOW()
                RETURNING acknowledged_at
                """
            ),
            {"rid": reco_id, "uid": user_id},
        )
    ).one()
    await session.commit()
    return row.acknowledged_at
