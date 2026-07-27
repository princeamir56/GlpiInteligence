import pytest

import api.routers.demandeurs as dem
from api.schemas.tabs import DemandeursResponse, Requester
from api.tests.conftest import as_role, auth_header


def _sample():
    return DemandeursResponse(
        items=[
            Requester(
                rank=1, user_id=3, name="Ali", total=12, incidents=8, requests=4,
                open=2, repetitive=0, high_priority=3, tickets_per_month=4.0,
                profile="dependant",
            )
        ]
    )


@pytest.mark.asyncio
async def test_demandeurs_happy(client, app_no_lifespan, monkeypatch):
    async def fake(session, filters):
        return _sample()

    monkeypatch.setattr(dem, "get_demandeurs", fake)
    as_role(app_no_lifespan, "MANAGER")
    r = await client.get("/api/demandeurs", headers=auth_header("MANAGER"))
    assert r.status_code == 200
    assert r.json()["items"][0]["profile"] == "dependant"


@pytest.mark.asyncio
async def test_demandeurs_auth_failure(client):
    r = await client.get("/api/demandeurs")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_demandeurs_invalid_param(client, app_no_lifespan):
    as_role(app_no_lifespan, "DSI")
    r = await client.get("/api/demandeurs?entity_id=-5", headers=auth_header("DSI"))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_demandeurs_empty(client, app_no_lifespan, monkeypatch):
    async def fake(session, filters):
        return DemandeursResponse(items=[])

    monkeypatch.setattr(dem, "get_demandeurs", fake)
    as_role(app_no_lifespan, "DSI")
    r = await client.get("/api/demandeurs", headers=auth_header("DSI"))
    assert r.status_code == 200
    assert r.json()["items"] == []
