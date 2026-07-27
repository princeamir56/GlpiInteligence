from datetime import datetime, timezone

import pytest

import api.routers.recommendations as rec
from api.schemas.tabs import Recommendation, RecommendationsResponse
from api.tests.conftest import as_role, auth_header


@pytest.fixture(autouse=True)
def _no_bust(monkeypatch):
    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(rec, "cache_bust_prefix", _noop)


@pytest.mark.asyncio
async def test_list_recommendations(client, app_no_lifespan, monkeypatch):
    async def fake(session, *, user_id, reco_type, severity, limit):
        return RecommendationsResponse(
            items=[
                Recommendation(
                    id="r1", type="FORMATION", severity="CRITIQUE",
                    title="Former Ali", acknowledged=False,
                )
            ]
        )

    monkeypatch.setattr(rec, "list_recommendations", fake)
    as_role(app_no_lifespan, "DSI")
    r = await client.get("/api/recommendations", headers=auth_header("DSI"))
    assert r.status_code == 200
    assert r.json()["items"][0]["type"] == "FORMATION"


@pytest.mark.asyncio
async def test_recommendations_auth_failure(client):
    r = await client.get("/api/recommendations")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_recommendations_invalid_type(client, app_no_lifespan):
    as_role(app_no_lifespan, "DSI")
    r = await client.get(
        "/api/recommendations?type=NOPE", headers=auth_header("DSI")
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_acknowledge_happy(client, app_no_lifespan, monkeypatch):
    async def exists(session, rid):
        return True

    async def ack(session, rid, uid):
        return datetime.now(timezone.utc)

    monkeypatch.setattr(rec, "recommendation_exists", exists)
    monkeypatch.setattr(rec, "acknowledge", ack)
    as_role(app_no_lifespan, "MANAGER")
    r = await client.post(
        "/api/recommendations/r1/acknowledge", headers=auth_header("MANAGER")
    )
    assert r.status_code == 200
    assert r.json()["recommendation_id"] == "r1"


@pytest.mark.asyncio
async def test_acknowledge_not_found(client, app_no_lifespan, monkeypatch):
    async def exists(session, rid):
        return False

    monkeypatch.setattr(rec, "recommendation_exists", exists)
    as_role(app_no_lifespan, "DSI")
    r = await client.post(
        "/api/recommendations/missing/acknowledge", headers=auth_header("DSI")
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_acknowledge_forbidden_for_direction(client, app_no_lifespan):
    # DIRECTION is read-only: not allowed to acknowledge.
    as_role(app_no_lifespan, "DIRECTION")
    r = await client.post(
        "/api/recommendations/r1/acknowledge", headers=auth_header("DIRECTION")
    )
    assert r.status_code == 403
