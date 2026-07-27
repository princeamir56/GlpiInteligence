"""GET /api/recommendations and POST /api/recommendations/{id}/acknowledge."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import cache_bust_prefix
from ..database import get_session
from ..queries.recommendations import (
    acknowledge,
    list_recommendations,
    recommendation_exists,
)
from ..schemas.common import RecoType, Severity
from ..schemas.tabs import AckResponse, RecommendationsResponse
from ..security import CurrentUser, require_role

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])
_ANY = require_role("DSI", "MANAGER", "DIRECTION")
_WRITE = require_role("DSI", "MANAGER")


@router.get("", response_model=RecommendationsResponse)
async def recommendations(
    type: Optional[RecoType] = Query(None, description="Filter by recommendation type."),
    severity: Optional[Severity] = Query(None, description="Filter by severity."),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(_ANY),
) -> RecommendationsResponse:
    return await list_recommendations(
        session,
        user_id=user.user_id,
        reco_type=type.value if type else None,
        severity=severity.value if severity else None,
        limit=limit,
    )


@router.post("/{reco_id}/acknowledge", response_model=AckResponse)
async def ack(
    reco_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(_WRITE),
) -> AckResponse:
    if not await recommendation_exists(session, reco_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recommendation {reco_id} not found",
        )
    acknowledged_at = await acknowledge(session, reco_id, user.user_id)
    # bust caches that may embed this alert (overview lists top alerts)
    await cache_bust_prefix("overview")
    return AckResponse(
        recommendation_id=reco_id,
        acknowledged_at=acknowledged_at,
        user_id=user.user_id,
    )
