"""Response models for the per-tab endpoints (demandeurs, services, sites,
repetitifs, techniciens, categories) and the prediction / recommendation lists."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel

from .common import RecoType, Severity


# ---- /api/demandeurs ----
class Requester(BaseModel):
    rank: int
    user_id: int
    name: str
    total: int
    incidents: int
    requests: int
    open: int
    repetitive: int
    high_priority: int
    tickets_per_month: float
    profile: Optional[str] = None  # from ml_user_profiles


class DemandeursResponse(BaseModel):
    items: list[Requester]


# ---- /api/services ----
class ServiceRow(BaseModel):
    service_id: Optional[int] = None
    service: str
    total: int
    high_priority: int
    open: int
    criticality: str  # derived: CRITIQUE / ÉLEVÉ / MODÉRÉ / FAIBLE
    incidents: int = 0
    requests: int = 0
    sla_pct: float = 0.0
    avg_resolution_days: Optional[float] = None


class ServicesResponse(BaseModel):
    items: list[ServiceRow]


# ---- /api/sites ----
class SiteRow(BaseModel):
    entity_id: Optional[int] = None
    name: str
    total: int
    resolved: int
    open: int
    part_pct: float  # share of overall ticket volume
    sla_pct: float = 0.0
    avg_resolution_days: Optional[float] = None


class SitesResponse(BaseModel):
    total_tickets: int
    items: list[SiteRow]


# ---- /api/repetitifs ----
class RepetitiveCluster(BaseModel):
    cluster_id: int
    algorithm: str
    severity: Optional[Severity] = None
    ticket_count: int
    top_keywords: list[str]
    sample_titles: list[str]
    neg_ratio: Optional[float] = None
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None


class RepetitifsResponse(BaseModel):
    items: list[RepetitiveCluster]


# ---- /api/techniciens ----
class TechnicianRow(BaseModel):
    technician_id: int
    name: str
    total: int
    resolved: int
    sla_pct: float
    avg_resolution_days: Optional[float] = None
    risk_score: Optional[float] = None       # from ml_sla_risk
    next_48h_prediction: Optional[int] = None
    risk_confidence: Optional[str] = None


class TechniciensResponse(BaseModel):
    items: list[TechnicianRow]


# ---- /api/categories ----
class CategoryRow(BaseModel):
    # NULL when the ticket carries no category in GLPI — a real state, not an error.
    category_id: Optional[int] = None
    name: str
    total: int
    resolved: int
    resolution_rate: float
    avg_resolution_days: Optional[float] = None
    incidents: int = 0
    requests: int = 0
    open: int = 0
    sla_pct: float = 0.0


class CategoriesResponse(BaseModel):
    items: list[CategoryRow]


# ---- /api/predictions/volume ----
class VolumeForecast(BaseModel):
    category_id: int
    category_name: Optional[str] = None
    forecast_date: date
    predicted_count: float
    lower_bound: Optional[float] = None
    upper_bound: Optional[float] = None
    confidence: Optional[str] = None


class VolumeForecastResponse(BaseModel):
    horizon_days: int
    items: list[VolumeForecast]


# ---- /api/predictions/sla_risk ----
class SlaRisk(BaseModel):
    technician_id: int
    name: Optional[str] = None
    risk_score: Optional[float] = None
    next_48h_prediction: Optional[int] = None
    confidence: Optional[str] = None


class SlaRiskResponse(BaseModel):
    items: list[SlaRisk]


# ---- /api/recommendations ----
class Recommendation(BaseModel):
    id: str
    type: RecoType
    severity: Optional[Severity] = None
    title: str
    description: Optional[str] = None
    target_user_id: Optional[int] = None
    target_group_id: Optional[int] = None
    target_category_id: Optional[int] = None
    evidence: Optional[dict] = None
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    acknowledged: bool = False


class RecommendationsResponse(BaseModel):
    items: list[Recommendation]


class AckResponse(BaseModel):
    recommendation_id: str
    acknowledged_at: datetime
    user_id: int
