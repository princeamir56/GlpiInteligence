"""Shared models: query filters, error envelope, alert, generic KPI."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from fastapi import Query
from pydantic import BaseModel, Field


class Severity(str, Enum):
    """French severity levels used across ml_clusters and recommendations."""

    CRITIQUE = "CRITIQUE"
    ELEVE = "ÉLEVÉ"
    MODERE = "MODÉRÉ"
    FAIBLE = "FAIBLE"


class RecoType(str, Enum):
    FORMATION = "FORMATION"
    SURCHARGE = "SURCHARGE"
    CAUSE_RACINE = "CAUSE_RACINE"
    AUTOMATISATION = "AUTOMATISATION"


class CommonFilters(BaseModel):
    """Optional filters accepted by every data endpoint."""

    start_date: Optional[date] = None
    end_date: Optional[date] = None
    limit: int = 50
    entity_id: Optional[int] = None
    category_id: Optional[int] = None


def common_filters(
    start_date: Optional[date] = Query(
        None, description="Inclusive lower bound on ticket `date`."
    ),
    end_date: Optional[date] = Query(
        None, description="Inclusive upper bound on ticket `date`."
    ),
    limit: int = Query(
        50, ge=1, le=500, description="Max rows returned for list-style results."
    ),
    entity_id: Optional[int] = Query(
        None, ge=0, description="Filter to a single site (entities_id)."
    ),
    category_id: Optional[int] = Query(
        None, ge=0, description="Filter to a single ITIL category (itilcategories_id)."
    ),
) -> CommonFilters:
    """FastAPI dependency exposing the shared query params in OpenAPI."""
    return CommonFilters(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        entity_id=entity_id,
        category_id=category_id,
    )


class Kpi(BaseModel):
    key: str
    label: str
    value: Any
    unit: Optional[str] = None


class Alert(BaseModel):
    recommendation_id: str
    severity: Severity
    type: Optional[str] = None
    title: str
    description: Optional[str] = None
    created_at: Optional[datetime] = None


class WsAlert(BaseModel):
    """WebSocket push payload."""

    type: str = "alert"
    severity: str
    title: str
    description: Optional[str] = None
    recommendation_id: str
    timestamp: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
