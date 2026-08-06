"""Prediction queries from ml_forecasts and ml_sla_risk."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas.tabs import (
    SlaRisk,
    SlaRiskResponse,
    VolumeForecast,
    VolumeForecastResponse,
)
from .shared import user_name_expr

# ml_forecasts is daily; "next 72h" == the next 3 forecast_dates from today.
VOLUME_HORIZON_DAYS = 3


async def get_volume_forecast(session: AsyncSession, f) -> VolumeForecastResponse:
    params: dict = {"horizon": VOLUME_HORIZON_DAYS}
    cat_clause = ""
    if f.category_id is not None:
        cat_clause = "AND fc.category_id = :category_id"
        params["category_id"] = f.category_id
    rows = (
        await session.execute(
            text(
                f"""
                SELECT fc.category_id, c.name AS category_name, fc.forecast_date,
                       fc.predicted_count, fc.lower_bound, fc.upper_bound, fc.confidence
                FROM ml_forecasts fc
                LEFT JOIN dim_categories c ON c.id = fc.category_id
                WHERE fc.forecast_date >= CURRENT_DATE
                  -- make_interval takes an int directly. Building the interval
                  -- by concatenation (:horizon || ' days') makes asyncpg infer
                  -- the parameter as text and reject the int bind.
                  AND fc.forecast_date < CURRENT_DATE + make_interval(days => :horizon)
                  {cat_clause}
                ORDER BY fc.category_id, fc.forecast_date
                """
            ),
            params,
        )
    ).all()
    items = [
        VolumeForecast(
            category_id=r.category_id,
            category_name=r.category_name,
            forecast_date=r.forecast_date,
            predicted_count=float(r.predicted_count) if r.predicted_count is not None else 0.0,
            lower_bound=r.lower_bound,
            upper_bound=r.upper_bound,
            confidence=r.confidence,
        )
        for r in rows
    ]
    return VolumeForecastResponse(horizon_days=VOLUME_HORIZON_DAYS, items=items)


async def get_sla_risk(session: AsyncSession, f) -> SlaRiskResponse:
    rows = (
        await session.execute(
            text(
                f"""
                SELECT r.technician_id, {user_name_expr('r.technician_id')} AS name,
                       r.risk_score, r.next_48h_prediction, r.confidence
                FROM ml_sla_risk r
                LEFT JOIN dim_users u ON u.id = r.technician_id
                ORDER BY r.risk_score DESC NULLS LAST
                LIMIT :limit
                """
            ),
            {"limit": f.limit},
        )
    ).all()
    items = [
        SlaRisk(
            technician_id=r.technician_id,
            name=r.name,
            risk_score=r.risk_score,
            next_48h_prediction=r.next_48h_prediction,
            confidence=r.confidence,
        )
        for r in rows
    ]
    return SlaRiskResponse(items=items)
