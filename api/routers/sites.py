"""GET /api/sites — entities with ticket counts and part%. Cached 5 min."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import cache_get, cache_set
from ..database import get_session
from ..queries.shared import cache_key
from ..queries.tabs import get_sites
from ..schemas.common import CommonFilters, common_filters
from ..schemas.tabs import SitesResponse
from ..security import CurrentUser, require_role

router = APIRouter(prefix="/api", tags=["sites"])
_ANY = require_role("DSI", "MANAGER", "DIRECTION")


@router.get("/sites", response_model=SitesResponse)
async def sites(
    filters: CommonFilters = Depends(common_filters),
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(_ANY),
) -> SitesResponse:
    key = cache_key("sites", filters)
    cached = await cache_get(key, "heavy")
    if cached is not None:
        return SitesResponse.model_validate(cached)
    result = await get_sites(session, filters)
    await cache_set(key, result.model_dump(mode="json"), "heavy")
    return result
