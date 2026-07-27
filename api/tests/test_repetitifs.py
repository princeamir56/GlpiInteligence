import pytest

import api.routers.repetitifs as rep
from api.schemas.common import Severity
from api.schemas.tabs import RepetitifsResponse, RepetitiveCluster
from api.tests.conftest import as_role, auth_header


def _sample():
    return RepetitifsResponse(
        items=[
            RepetitiveCluster(
                cluster_id=1, algorithm="dbscan", severity=Severity.CRITIQUE,
                ticket_count=15, top_keywords=["vpn", "connexion"],
                sample_titles=["VPN down"], neg_ratio=0.6,
            )
        ]
    )


@pytest.mark.asyncio
async def test_repetitifs_happy(client, app_no_lifespan, monkeypatch):
    async def fake(session, filters):
        return _sample()

    monkeypatch.setattr(rep, "get_repetitifs", fake)
    as_role(app_no_lifespan, "DSI")
    r = await client.get("/api/repetitifs", headers=auth_header("DSI"))
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["severity"] == "CRITIQUE"
    assert "vpn" in item["top_keywords"]


@pytest.mark.asyncio
async def test_repetitifs_auth_failure(client):
    r = await client.get("/api/repetitifs")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_repetitifs_invalid_param(client, app_no_lifespan):
    as_role(app_no_lifespan, "DSI")
    r = await client.get("/api/repetitifs?limit=0", headers=auth_header("DSI"))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_repetitifs_empty(client, app_no_lifespan, monkeypatch):
    async def fake(session, filters):
        return RepetitifsResponse(items=[])

    monkeypatch.setattr(rep, "get_repetitifs", fake)
    as_role(app_no_lifespan, "DSI")
    r = await client.get("/api/repetitifs", headers=auth_header("DSI"))
    assert r.status_code == 200
    assert r.json()["items"] == []
