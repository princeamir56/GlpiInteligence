"""GET /api/techniciens — per-technician SLA metrics + ML risk. Cached 5 min."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import cache_get, cache_set
from ..database import get_session
from ..queries.shared import cache_key
from ..queries.tabs import get_techniciens
from ..schemas.common import CommonFilters, common_filters
from ..schemas.tabs import TechniciensResponse
from ..security import CurrentUser, require_role

router = APIRouter(prefix="/api", tags=["techniciens"])
_ANY = require_role("DSI", "MANAGER", "DIRECTION")


@router.get("/techniciens", response_model=TechniciensResponse)
async def techniciens(
    filters: CommonFilters = Depends(common_filters),
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(_ANY),
) -> TechniciensResponse:
    key = cache_key("techniciens", filters)
    cached = await cache_get(key, "heavy")
    if cached is not None:
        return TechniciensResponse.model_validate(cached)
    result = await get_techniciens(session, filters)
    await cache_set(key, result.model_dump(mode="json"), "heavy")
    return result
