"""GET /api/repetitifs — repetitive ticket clusters from ml_clusters."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..queries.tabs import get_repetitifs
from ..schemas.common import CommonFilters, common_filters
from ..schemas.tabs import RepetitifsResponse
from ..security import CurrentUser, require_role

router = APIRouter(prefix="/api", tags=["repetitifs"])
_ANY = require_role("DSI", "MANAGER", "DIRECTION")


@router.get("/repetitifs", response_model=RepetitifsResponse)
async def repetitifs(
    filters: CommonFilters = Depends(common_filters),
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(_ANY),
) -> RepetitifsResponse:
    return await get_repetitifs(session, filters)
