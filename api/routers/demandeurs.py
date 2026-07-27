"""GET /api/demandeurs — top requesters + ML profile."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..queries.tabs import get_demandeurs
from ..schemas.common import CommonFilters, common_filters
from ..schemas.tabs import DemandeursResponse
from ..security import CurrentUser, require_role

router = APIRouter(prefix="/api", tags=["demandeurs"])
_ANY = require_role("DSI", "MANAGER", "DIRECTION")


@router.get("/demandeurs", response_model=DemandeursResponse)
async def demandeurs(
    filters: CommonFilters = Depends(common_filters),
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(_ANY),
) -> DemandeursResponse:
    return await get_demandeurs(session, filters)
