"""GET /api/overview — feeds the Vue d'ensemble tab. Cached 60s."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import cache_get, cache_set
from ..database import get_session
from ..queries.overview import get_overview
from ..queries.shared import cache_key
from ..schemas.common import CommonFilters, common_filters
from ..schemas.overview import OverviewResponse
from ..security import CurrentUser, require_role

router = APIRouter(prefix="/api", tags=["overview"])

_ANY = require_role("DSI", "MANAGER", "DIRECTION")


@router.get("/overview", response_model=OverviewResponse)
async def overview(
    filters: CommonFilters = Depends(common_filters),
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(_ANY),
) -> OverviewResponse:
    key = cache_key("overview", filters)
    cached = await cache_get(key, "overview")
    if cached is not None:
        return OverviewResponse.model_validate(cached)
    result = await get_overview(session, filters)
    await cache_set(key, result.model_dump(mode="json"), "overview")
    return result
