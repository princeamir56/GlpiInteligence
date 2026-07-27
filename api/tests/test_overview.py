import pytest

import api.routers.overview as ov
from api.schemas.common import Alert, Severity
from api.schemas.overview import (
    NamedCount,
    OverviewCharts,
    OverviewKpis,
    OverviewResponse,
    TechnicianSla,
)
from api.tests.conftest import as_role, auth_header


def _sample() -> OverviewResponse:
    return OverviewResponse(
        kpis=OverviewKpis(
            total_tickets=120,
            resolved_pct=75.0,
            sla_global_pct=88.5,
            repetitive_count=4,
            active_sites_count=7,
            top_category="Réseau",
        ),
        charts=OverviewCharts(
            top_sites=[NamedCount(id=1, name="Sfax", count=40)],
            top_categories=[NamedCount(id=2, name="Réseau", count=30)],
            top_requesters=[NamedCount(id=3, name="Ali", count=12)],
            sla_by_technician=[
                TechnicianSla(technician_id=5, name="Sami", sla_pct=90.0, total=20)
            ],
        ),
        alerts=[
            Alert(
                recommendation_id="abc",
                severity=Severity.CRITIQUE,
                title="Surcharge",
                description="...",
            )
        ],
    )


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    async def _get(*a, **k):
        return None

    async def _set(*a, **k):
        return None

    monkeypatch.setattr(ov, "cache_get", _get)
    monkeypatch.setattr(ov, "cache_set", _set)


@pytest.mark.asyncio
async def test_overview_happy(client, app_no_lifespan, monkeypatch):
    async def fake(session, filters):
        return _sample()

    monkeypatch.setattr(ov, "get_overview", fake)
    as_role(app_no_lifespan, "DSI")
    r = await client.get("/api/overview", headers=auth_header("DSI"))
    assert r.status_code == 200
    body = r.json()
    assert body["kpis"]["total_tickets"] == 120
    assert body["charts"]["top_sites"][0]["name"] == "Sfax"
    assert body["alerts"][0]["severity"] == "CRITIQUE"


@pytest.mark.asyncio
async def test_overview_requires_auth(client):
    r = await client.get("/api/overview")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_overview_invalid_param(client, app_no_lifespan):
    as_role(app_no_lifespan, "DSI")
    r = await client.get("/api/overview?limit=99999", headers=auth_header("DSI"))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_overview_empty(client, app_no_lifespan, monkeypatch):
    async def fake(session, filters):
        return OverviewResponse(
            kpis=OverviewKpis(
                total_tickets=0, resolved_pct=0.0, sla_global_pct=0.0,
                repetitive_count=0, active_sites_count=0, top_category=None,
            ),
            charts=OverviewCharts(
                top_sites=[], top_categories=[], top_requesters=[], sla_by_technician=[]
            ),
            alerts=[],
        )

    monkeypatch.setattr(ov, "get_overview", fake)
    as_role(app_no_lifespan, "DIRECTION")
    r = await client.get("/api/overview", headers=auth_header("DIRECTION"))
    assert r.status_code == 200
    assert r.json()["kpis"]["total_tickets"] == 0
