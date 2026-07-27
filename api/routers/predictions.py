"""GET /api/predictions/volume and /api/predictions/sla_risk."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..queries.predictions import get_sla_risk, get_volume_forecast
from ..schemas.common import CommonFilters, common_filters
from ..schemas.tabs import SlaRiskResponse, VolumeForecastResponse
from ..security import CurrentUser, require_role

router = APIRouter(prefix="/api/predictions", tags=["predictions"])
_ANY = require_role("DSI", "MANAGER", "DIRECTION")


@router.get("/volume", response_model=VolumeForecastResponse)
async def volume(
    filters: CommonFilters = Depends(common_filters),
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(_ANY),
) -> VolumeForecastResponse:
    return await get_volume_forecast(session, filters)


@router.get("/sla_risk", response_model=SlaRiskResponse)
async def sla_risk(
    filters: CommonFilters = Depends(common_filters),
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(_ANY),
) -> SlaRiskResponse:
    return await get_sla_risk(session, filters)
