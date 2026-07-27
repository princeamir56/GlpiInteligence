"""Query builders for the per-tab endpoints."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas.tabs import (
    CategoriesResponse,
    CategoryRow,
    DemandeursResponse,
    RepetitifsResponse,
    RepetitiveCluster,
    Requester,
    ServiceRow,
    ServicesResponse,
    SiteRow,
    SitesResponse,
    TechnicianRow,
    TechniciensResponse,
)
from .shared import IS_OPEN_EXPR, SLA_MET_EXPR, USER_NAME_EXPR, ticket_filters


def _criticality(high_ratio: float) -> str:
    if high_ratio >= 0.5:
        return "CRITIQUE"
    if high_ratio >= 0.25:
        return "ÉLEVÉ"
    if high_ratio >= 0.1:
        return "MODÉRÉ"
    return "FAIBLE"


async def get_demandeurs(session: AsyncSession, f) -> DemandeursResponse:
    frag, params = ticket_filters(f, prefix="t.")
    params = {**params, "limit": f.limit}
    rows = (
        await session.execute(
            text(
                f"""
                SELECT t.user_requester AS uid, {USER_NAME_EXPR} AS name,
                       COUNT(*) AS total,
                       SUM(CASE WHEN t.type = 1 THEN 1 ELSE 0 END) AS incidents,
                       SUM(CASE WHEN t.type = 2 THEN 1 ELSE 0 END) AS requests,
                       SUM(CASE WHEN {IS_OPEN_EXPR} THEN 1 ELSE 0 END) AS open,
                       SUM(CASE WHEN t.is_high_priority THEN 1 ELSE 0 END) AS high_priority,
                       MIN(t.date) AS first_date, MAX(t.date) AS last_date,
                       p.profile AS profile
                FROM dim_tickets_enriched t
                LEFT JOIN dim_users u ON u.id = t.user_requester
                LEFT JOIN ml_user_profiles p ON p.user_id = t.user_requester
                WHERE {frag} AND t.user_requester IS NOT NULL
                GROUP BY t.user_requester, u.realname, u.firstname, u.name, u.id, p.profile
                ORDER BY total DESC
                LIMIT :limit
                """
            ),
            params,
        )
    ).all()

    items: list[Requester] = []
    for i, r in enumerate(rows, start=1):
        months = 1.0
        if r.first_date and r.last_date:
            days = (r.last_date - r.first_date).days
            months = max(days / 30.0, 1.0)
        items.append(
            Requester(
                rank=i,
                user_id=r.uid,
                name=r.name,
                total=int(r.total),
                incidents=int(r.incidents or 0),
                requests=int(r.requests or 0),
                open=int(r.open or 0),
                repetitive=0,  # per-user repetitive count not tracked in ml_clusters
                high_priority=int(r.high_priority or 0),
                tickets_per_month=round(int(r.total) / months, 2),
                profile=r.profile,
            )
        )
    return DemandeursResponse(items=items)


async def get_services(session: AsyncSession, f) -> ServicesResponse:
    """Group by the requester group (groups_id_requester) as the "service"."""
    frag, params = ticket_filters(f, prefix="t.")
    params = {**params, "limit": f.limit}
    rows = (
        await session.execute(
            text(
                f"""
                SELECT t.groups_id_requester AS gid,
                       COALESCE(g.completename, g.name, 'Sans service') AS service,
                       COUNT(*) AS total,
                       SUM(CASE WHEN t.is_high_priority THEN 1 ELSE 0 END) AS high_priority,
                       SUM(CASE WHEN {IS_OPEN_EXPR} THEN 1 ELSE 0 END) AS open,
                       SUM(CASE WHEN t.type = 1 THEN 1 ELSE 0 END) AS incidents,
                       SUM(CASE WHEN t.type = 2 THEN 1 ELSE 0 END) AS requests,
                       AVG(CASE WHEN {SLA_MET_EXPR} THEN 1.0 ELSE 0.0 END) AS sla_pct,
                       AVG(t.resolution_days) AS avg_days
                FROM dim_tickets_enriched t
                LEFT JOIN dim_groups g ON g.id = t.groups_id_requester
                WHERE {frag}
                GROUP BY t.groups_id_requester, g.completename, g.name
                ORDER BY total DESC
                LIMIT :limit
                """
            ),
            params,
        )
    ).all()
    items = []
    for r in rows:
        total = int(r.total)
        hp = int(r.high_priority or 0)
        items.append(
            ServiceRow(
                service_id=r.gid,
                service=r.service,
                total=total,
                high_priority=hp,
                open=int(r.open or 0),
                criticality=_criticality(hp / total if total else 0.0),
                incidents=int(r.incidents or 0),
                requests=int(r.requests or 0),
                sla_pct=round(float(r.sla_pct) * 100, 1),
                avg_resolution_days=round(float(r.avg_days), 2) if r.avg_days is not None else None,
            )
        )
    return ServicesResponse(items=items)


async def get_sites(session: AsyncSession, f) -> SitesResponse:
    frag, params = ticket_filters(f, prefix="t.")
    grand_total = int(
        (
            await session.execute(
                text(
                    f"SELECT COUNT(*) FROM dim_tickets_enriched t WHERE {frag}"
                ),
                params,
            )
        ).scalar()
        or 0
    )
    params = {**params, "limit": f.limit}
    rows = (
        await session.execute(
            text(
                f"""
                SELECT t.entities_id AS eid,
                       COALESCE(e.name, 'Site #'||t.entities_id::text) AS name,
                       COUNT(*) AS total,
                       SUM(CASE WHEN t.is_resolved THEN 1 ELSE 0 END) AS resolved,
                       SUM(CASE WHEN {IS_OPEN_EXPR} THEN 1 ELSE 0 END) AS open,
                       AVG(CASE WHEN {SLA_MET_EXPR} THEN 1.0 ELSE 0.0 END) AS sla_pct,
                       AVG(t.resolution_days) AS avg_days
                FROM dim_tickets_enriched t
                LEFT JOIN dim_entities e ON e.id = t.entities_id
                WHERE {frag}
                GROUP BY t.entities_id, e.name
                ORDER BY total DESC
                LIMIT :limit
                """
            ),
            params,
        )
    ).all()
    items = [
        SiteRow(
            entity_id=r.eid,
            name=r.name,
            total=int(r.total),
            resolved=int(r.resolved or 0),
            open=int(r.open or 0),
            part_pct=round(100.0 * int(r.total) / grand_total, 1) if grand_total else 0.0,
            sla_pct=round(float(r.sla_pct) * 100, 1),
            avg_resolution_days=round(float(r.avg_days), 2) if r.avg_days is not None else None,
        )
        for r in rows
    ]
    return SitesResponse(total_tickets=grand_total, items=items)


async def get_repetitifs(session: AsyncSession, f) -> RepetitifsResponse:
    """Repetitive clusters from ml_clusters, ordered by severity then volume."""
    rows = (
        await session.execute(
            text(
                """
                SELECT cluster_id, algorithm, severity, ticket_count,
                       top_keywords, sample_titles, neg_ratio, first_seen, last_seen
                FROM ml_clusters
                ORDER BY CASE severity
                    WHEN 'CRITIQUE' THEN 0 WHEN 'ÉLEVÉ' THEN 1
                    WHEN 'MODÉRÉ' THEN 2 ELSE 3 END,
                    ticket_count DESC
                LIMIT :limit
                """
            ),
            {"limit": f.limit},
        )
    ).all()
    items = [
        RepetitiveCluster(
            cluster_id=r.cluster_id,
            algorithm=r.algorithm,
            severity=r.severity,
            ticket_count=int(r.ticket_count or 0),
            top_keywords=list(r.top_keywords or []),
            sample_titles=list(r.sample_titles or []),
            neg_ratio=r.neg_ratio,
            first_seen=r.first_seen,
            last_seen=r.last_seen,
        )
        for r in rows
    ]
    return RepetitifsResponse(items=items)


async def get_techniciens(session: AsyncSession, f) -> TechniciensResponse:
    frag, params = ticket_filters(f, prefix="t.")
    params = {**params, "limit": f.limit}
    rows = (
        await session.execute(
            text(
                f"""
                SELECT t.user_assign AS tid, {USER_NAME_EXPR} AS name,
                       COUNT(*) AS total,
                       SUM(CASE WHEN t.is_resolved THEN 1 ELSE 0 END) AS resolved,
                       AVG(CASE WHEN {SLA_MET_EXPR} THEN 1.0 ELSE 0.0 END) AS sla_pct,
                       AVG(t.resolution_days) AS avg_days,
                       r.risk_score AS risk_score,
                       r.next_48h_prediction AS next48,
                       r.confidence AS risk_conf
                FROM dim_tickets_enriched t
                LEFT JOIN dim_users u ON u.id = t.user_assign
                LEFT JOIN ml_sla_risk r ON r.technician_id = t.user_assign
                WHERE {frag} AND t.user_assign IS NOT NULL
                GROUP BY t.user_assign, u.realname, u.firstname, u.name, u.id,
                         r.risk_score, r.next_48h_prediction, r.confidence
                ORDER BY total DESC
                LIMIT :limit
                """
            ),
            params,
        )
    ).all()
    items = [
        TechnicianRow(
            technician_id=r.tid,
            name=r.name,
            total=int(r.total),
            resolved=int(r.resolved or 0),
            sla_pct=round(float(r.sla_pct) * 100, 1),
            avg_resolution_days=round(float(r.avg_days), 2) if r.avg_days is not None else None,
            risk_score=r.risk_score,
            next_48h_prediction=r.next48,
            risk_confidence=r.risk_conf,
        )
        for r in rows
    ]
    return TechniciensResponse(items=items)


async def get_categories(session: AsyncSession, f) -> CategoriesResponse:
    frag, params = ticket_filters(f, prefix="t.")
    params = {**params, "limit": f.limit}
    rows = (
        await session.execute(
            text(
                f"""
                SELECT t.itilcategories_id AS cid,
                       COALESCE(c.name, 'Cat #'||t.itilcategories_id::text) AS name,
                       COUNT(*) AS total,
                       SUM(CASE WHEN t.is_resolved THEN 1 ELSE 0 END) AS resolved,
                       AVG(t.resolution_days) AS avg_days,
                       SUM(CASE WHEN t.type = 1 THEN 1 ELSE 0 END) AS incidents,
                       SUM(CASE WHEN t.type = 2 THEN 1 ELSE 0 END) AS requests,
                       SUM(CASE WHEN {IS_OPEN_EXPR} THEN 1 ELSE 0 END) AS open,
                       AVG(CASE WHEN {SLA_MET_EXPR} THEN 1.0 ELSE 0.0 END) AS sla_pct
                FROM dim_tickets_enriched t
                LEFT JOIN dim_categories c ON c.id = t.itilcategories_id
                WHERE {frag}
                GROUP BY t.itilcategories_id, c.name
                ORDER BY total DESC
                LIMIT :limit
                """
            ),
            params,
        )
    ).all()
    items = []
    for r in rows:
        total = int(r.total)
        resolved = int(r.resolved or 0)
        items.append(
            CategoryRow(
                category_id=r.cid,
                name=r.name,
                total=total,
                resolved=resolved,
                resolution_rate=round(100.0 * resolved / total, 1) if total else 0.0,
                avg_resolution_days=round(float(r.avg_days), 2) if r.avg_days is not None else None,
                incidents=int(r.incidents or 0),
                requests=int(r.requests or 0),
                open=int(r.open or 0),
                sla_pct=round(float(r.sla_pct) * 100, 1),
            )
        )
    return CategoriesResponse(items=items)
