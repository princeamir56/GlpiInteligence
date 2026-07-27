"""Overview tab aggregate queries."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas.common import Alert
from ..schemas.overview import (
    NamedCount,
    OverviewCharts,
    OverviewKpis,
    OverviewResponse,
    TechnicianSla,
)
from .shared import IS_OPEN_EXPR, SLA_MET_EXPR, USER_NAME_EXPR, ticket_filters


async def _scalar(session: AsyncSession, sql: str, params: dict):
    return (await session.execute(text(sql), params)).scalar()


async def get_overview(session: AsyncSession, f) -> OverviewResponse:
    frag, params = ticket_filters(f)

    # ---- KPI aggregates in one pass ----
    kpi_row = (
        await session.execute(
            text(
                f"""
                SELECT
                    COUNT(*)                                             AS total,
                    COALESCE(AVG(CASE WHEN is_resolved THEN 1.0 ELSE 0.0 END),0) AS resolved_pct,
                    COALESCE(AVG(CASE WHEN {SLA_MET_EXPR} THEN 1.0 ELSE 0.0 END),0) AS sla_pct,
                    COUNT(DISTINCT entities_id)                          AS active_sites
                FROM dim_tickets_enriched
                WHERE {frag}
                """
            ),
            params,
        )
    ).one()

    repetitive = (
        await _scalar(
            session,
            "SELECT COALESCE(SUM(ticket_count),0) FROM ml_clusters",
            {},
        )
        or 0
    )

    # ---- top sites ----
    top_sites = [
        NamedCount(id=r.entities_id, name=r.name or f"Site #{r.entities_id}", count=r.c)
        for r in (
            await session.execute(
                text(
                    f"""
                    SELECT t.entities_id, e.name, COUNT(*) AS c
                    FROM dim_tickets_enriched t
                    LEFT JOIN dim_entities e ON e.id = t.entities_id
                    WHERE {ticket_filters(f, prefix='t.')[0]}
                    GROUP BY t.entities_id, e.name
                    ORDER BY c DESC LIMIT 10
                    """
                ),
                ticket_filters(f, prefix="t.")[1],
            )
        ).all()
    ]

    # ---- top categories (donut) ----
    top_categories = [
        NamedCount(
            id=r.itilcategories_id,
            name=r.name or f"Cat #{r.itilcategories_id}",
            count=r.c,
        )
        for r in (
            await session.execute(
                text(
                    f"""
                    SELECT t.itilcategories_id, c.name, COUNT(*) AS c
                    FROM dim_tickets_enriched t
                    LEFT JOIN dim_categories c ON c.id = t.itilcategories_id
                    WHERE {ticket_filters(f, prefix='t.')[0]}
                    GROUP BY t.itilcategories_id, c.name
                    ORDER BY c DESC LIMIT 8
                    """
                ),
                ticket_filters(f, prefix="t.")[1],
            )
        ).all()
    ]

    top_cat_name = top_categories[0].name if top_categories else None

    # ---- top requesters ----
    top_requesters = [
        NamedCount(id=r.uid, name=r.name, count=r.c)
        for r in (
            await session.execute(
                text(
                    f"""
                    SELECT t.user_requester AS uid, {USER_NAME_EXPR} AS name, COUNT(*) AS c
                    FROM dim_tickets_enriched t
                    LEFT JOIN dim_users u ON u.id = t.user_requester
                    WHERE {ticket_filters(f, prefix='t.')[0]} AND t.user_requester IS NOT NULL
                    GROUP BY t.user_requester, u.realname, u.firstname, u.name, u.id
                    ORDER BY c DESC LIMIT 10
                    """
                ),
                ticket_filters(f, prefix="t.")[1],
            )
        ).all()
    ]

    # ---- SLA per technician ----
    sla_by_tech = [
        TechnicianSla(
            technician_id=r.tid,
            name=r.name,
            sla_pct=round(float(r.sla_pct) * 100, 1),
            total=r.total,
        )
        for r in (
            await session.execute(
                text(
                    f"""
                    SELECT t.user_assign AS tid, {USER_NAME_EXPR} AS name,
                           COUNT(*) AS total,
                           AVG(CASE WHEN {SLA_MET_EXPR} THEN 1.0 ELSE 0.0 END) AS sla_pct
                    FROM dim_tickets_enriched t
                    LEFT JOIN dim_users u ON u.id = t.user_assign
                    WHERE {ticket_filters(f, prefix='t.')[0]} AND t.user_assign IS NOT NULL
                    GROUP BY t.user_assign, u.realname, u.firstname, u.name, u.id
                    ORDER BY total DESC LIMIT 15
                    """
                ),
                ticket_filters(f, prefix="t.")[1],
            )
        ).all()
    ]

    # ---- top 4 critical ML alerts ----
    alerts = [
        Alert(
            recommendation_id=r.id,
            severity=r.severity,
            type=r.type,
            title=r.title,
            description=r.description,
            created_at=r.created_at,
        )
        for r in (
            await session.execute(
                text(
                    """
                    SELECT id, severity, type, title, description, created_at
                    FROM recommendations
                    WHERE (expires_at IS NULL OR expires_at > NOW())
                    ORDER BY CASE severity
                        WHEN 'CRITIQUE' THEN 0 WHEN 'ÉLEVÉ' THEN 1
                        WHEN 'MODÉRÉ' THEN 2 ELSE 3 END, created_at DESC
                    LIMIT 4
                    """
                )
            )
        ).all()
    ]

    return OverviewResponse(
        kpis=OverviewKpis(
            total_tickets=int(kpi_row.total),
            resolved_pct=round(float(kpi_row.resolved_pct) * 100, 1),
            sla_global_pct=round(float(kpi_row.sla_pct) * 100, 1),
            repetitive_count=int(repetitive),
            active_sites_count=int(kpi_row.active_sites),
            top_category=top_cat_name,
        ),
        charts=OverviewCharts(
            top_sites=top_sites,
            top_categories=top_categories,
            top_requesters=top_requesters,
            sla_by_technician=sla_by_tech,
        ),
        alerts=alerts,
    )
