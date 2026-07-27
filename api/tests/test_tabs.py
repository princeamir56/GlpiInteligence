"""Coverage for the remaining tab routes: services, sites, techniciens, categories,
and the two prediction endpoints. Happy + auth-failure + empty for each."""
import pytest

import api.routers.categories as cat
import api.routers.predictions as pred
import api.routers.services as svc
import api.routers.sites as st
import api.routers.techniciens as tech
from api.schemas.tabs import (
    CategoriesResponse,
    CategoryRow,
    ServiceRow,
    ServicesResponse,
    SiteRow,
    SitesResponse,
    SlaRisk,
    SlaRiskResponse,
    TechnicianRow,
    TechniciensResponse,
    VolumeForecast,
    VolumeForecastResponse,
)
from api.tests.conftest import as_role, auth_header


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    async def _get(*a, **k):
        return None

    async def _set(*a, **k):
        return None

    for mod in (st, tech):
        monkeypatch.setattr(mod, "cache_get", _get)
        monkeypatch.setattr(mod, "cache_set", _set)


@pytest.mark.asyncio
async def test_services(client, app_no_lifespan, monkeypatch):
    async def fake(session, filters):
        return ServicesResponse(
            items=[ServiceRow(service_id=1, service="Prod", total=10,
                              high_priority=6, open=3, criticality="CRITIQUE")]
        )

    monkeypatch.setattr(svc, "get_services", fake)
    as_role(app_no_lifespan, "DSI")
    r = await client.get("/api/services", headers=auth_header("DSI"))
    assert r.status_code == 200
    assert r.json()["items"][0]["criticality"] == "CRITIQUE"


@pytest.mark.asyncio
async def test_services_auth_failure(client):
    assert (await client.get("/api/services")).status_code == 401


@pytest.mark.asyncio
async def test_sites(client, app_no_lifespan, monkeypatch):
    async def fake(session, filters):
        return SitesResponse(
            total_tickets=100,
            items=[SiteRow(entity_id=1, name="Sfax", total=40, resolved=30,
                           open=10, part_pct=40.0)],
        )

    monkeypatch.setattr(st, "get_sites", fake)
    as_role(app_no_lifespan, "MANAGER")
    r = await client.get("/api/sites", headers=auth_header("MANAGER"))
    assert r.status_code == 200
    assert r.json()["total_tickets"] == 100


@pytest.mark.asyncio
async def test_sites_empty(client, app_no_lifespan, monkeypatch):
    async def fake(session, filters):
        return SitesResponse(total_tickets=0, items=[])

    monkeypatch.setattr(st, "get_sites", fake)
    as_role(app_no_lifespan, "DSI")
    r = await client.get("/api/sites", headers=auth_header("DSI"))
    assert r.status_code == 200
    assert r.json()["items"] == []


@pytest.mark.asyncio
async def test_techniciens(client, app_no_lifespan, monkeypatch):
    async def fake(session, filters):
        return TechniciensResponse(
            items=[TechnicianRow(technician_id=5, name="Sami", total=20, resolved=18,
                                 sla_pct=90.0, avg_resolution_days=1.2, risk_score=0.3,
                                 next_48h_prediction=2, risk_confidence="high")]
        )

    monkeypatch.setattr(tech, "get_techniciens", fake)
    as_role(app_no_lifespan, "DSI")
    r = await client.get("/api/techniciens", headers=auth_header("DSI"))
    assert r.status_code == 200
    assert r.json()["items"][0]["sla_pct"] == 90.0


@pytest.mark.asyncio
async def test_techniciens_invalid_param(client, app_no_lifespan):
    as_role(app_no_lifespan, "DSI")
    r = await client.get("/api/techniciens?limit=-1", headers=auth_header("DSI"))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_categories(client, app_no_lifespan, monkeypatch):
    async def fake(session, filters):
        return CategoriesResponse(
            items=[CategoryRow(category_id=2, name="Réseau", total=30, resolved=25,
                               resolution_rate=83.3, avg_resolution_days=0.9)]
        )

    monkeypatch.setattr(cat, "get_categories", fake)
    as_role(app_no_lifespan, "DIRECTION")
    r = await client.get("/api/categories", headers=auth_header("DIRECTION"))
    assert r.status_code == 200
    assert r.json()["items"][0]["name"] == "Réseau"


@pytest.mark.asyncio
async def test_predictions_volume(client, app_no_lifespan, monkeypatch):
    async def fake(session, filters):
        return VolumeForecastResponse(
            horizon_days=3,
            items=[VolumeForecast(category_id=2, category_name="Réseau",
                                  forecast_date="2026-07-17", predicted_count=12.0,
                                  lower_bound=8.0, upper_bound=16.0, confidence="high")],
        )

    monkeypatch.setattr(pred, "get_volume_forecast", fake)
    as_role(app_no_lifespan, "DSI")
    r = await client.get("/api/predictions/volume", headers=auth_header("DSI"))
    assert r.status_code == 200
    assert r.json()["horizon_days"] == 3


@pytest.mark.asyncio
async def test_predictions_sla_risk_empty(client, app_no_lifespan, monkeypatch):
    async def fake(session, filters):
        return SlaRiskResponse(items=[])

    monkeypatch.setattr(pred, "get_sla_risk", fake)
    as_role(app_no_lifespan, "DSI")
    r = await client.get("/api/predictions/sla_risk", headers=auth_header("DSI"))
    assert r.status_code == 200
    assert r.json()["items"] == []


@pytest.mark.asyncio
async def test_predictions_auth_failure(client):
    assert (await client.get("/api/predictions/volume")).status_code == 401
