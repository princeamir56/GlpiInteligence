"""GET /api/categories — per-category volumes, delays, resolution rate."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..queries.tabs import get_categories
from ..schemas.common import CommonFilters, common_filters
from ..schemas.tabs import CategoriesResponse
from ..security import CurrentUser, require_role

router = APIRouter(prefix="/api", tags=["categories"])
_ANY = require_role("DSI", "MANAGER", "DIRECTION")


@router.get("/categories", response_model=CategoriesResponse)
async def categories(
    filters: CommonFilters = Depends(common_filters),
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(_ANY),
) -> CategoriesResponse:
    return await get_categories(session, filters)
