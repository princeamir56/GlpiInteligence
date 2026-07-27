import pytest

import api.routers.auth as auth_mod
from api.security import CurrentUser


@pytest.mark.asyncio
async def test_login_happy(client, app_no_lifespan, monkeypatch):
    async def fake_auth(session, username, password):
        assert username == "dsi@sartex"
        return CurrentUser(user_id=1, username="dsi@sartex", role="DSI")

    monkeypatch.setattr(auth_mod, "authenticate_user", fake_auth)
    r = await client.post(
        "/api/auth/login", json={"username": "dsi@sartex", "password": "x"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_bad_credentials(client, app_no_lifespan, monkeypatch):
    async def fake_auth(session, username, password):
        return None

    monkeypatch.setattr(auth_mod, "authenticate_user", fake_auth)
    r = await client.post(
        "/api/auth/login", json={"username": "x", "password": "y"}
    )
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "http_401"


@pytest.mark.asyncio
async def test_login_invalid_params(client):
    r = await client.post("/api/auth/login", json={"username": "only"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


@pytest.mark.asyncio
async def test_refresh_flow(client, app_no_lifespan, monkeypatch):
    from api.security import create_refresh_token

    token = create_refresh_token("dsi@sartex", "DSI")
    r = await client.post("/api/auth/refresh", json={"refresh_token": token})
    assert r.status_code == 200
    assert r.json()["access_token"]


@pytest.mark.asyncio
async def test_refresh_rejects_access_token(client):
    from api.security import create_access_token

    token = create_access_token("dsi@sartex", "DSI")
    r = await client.post("/api/auth/refresh", json={"refresh_token": token})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_token(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401
