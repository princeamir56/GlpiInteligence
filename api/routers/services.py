"""GET /api/services — tickets grouped by service with criticality."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..queries.tabs import get_services
from ..schemas.common import CommonFilters, common_filters
from ..schemas.tabs import ServicesResponse
from ..security import CurrentUser, require_role

router = APIRouter(prefix="/api", tags=["services"])
_ANY = require_role("DSI", "MANAGER", "DIRECTION")


@router.get("/services", response_model=ServicesResponse)
async def services(
    filters: CommonFilters = Depends(common_filters),
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(_ANY),
) -> ServicesResponse:
    return await get_services(session, filters)
