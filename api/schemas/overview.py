"""Overview tab (Vue d'ensemble) response models."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from .common import Alert, Kpi


class OverviewKpis(BaseModel):
    total_tickets: int
    resolved_pct: float
    sla_global_pct: float
    repetitive_count: int
    active_sites_count: int
    top_category: Optional[str] = None


class NamedCount(BaseModel):
    id: Optional[int] = None
    name: str
    count: int


class TechnicianSla(BaseModel):
    technician_id: int
    name: str
    sla_pct: float
    total: int


class OverviewCharts(BaseModel):
    top_sites: list[NamedCount]
    top_categories: list[NamedCount]
    top_requesters: list[NamedCount]
    sla_by_technician: list[TechnicianSla]


class OverviewResponse(BaseModel):
    kpis: OverviewKpis
    charts: OverviewCharts
    alerts: list[Alert]
