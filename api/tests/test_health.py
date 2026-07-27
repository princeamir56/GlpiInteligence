import pytest

from api.tests.conftest import _DummySession


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_db_ok(client, app_no_lifespan):
    # override the dummy session with one whose execute succeeds
    from api.database import get_session

    class OkSession(_DummySession):
        async def execute(self, *a, **k):
            return None

    async def _ok():
        yield OkSession()

    app_no_lifespan.dependency_overrides[get_session] = _ok
    r = await client.get("/health/db")
    assert r.status_code == 200
    assert r.json()["db"] == "reachable"


@pytest.mark.asyncio
async def test_health_db_down(client, app_no_lifespan):
    from api.database import get_session

    class BadSession:
        async def execute(self, *a, **k):
            raise RuntimeError("no db")

    async def _bad():
        yield BadSession()

    app_no_lifespan.dependency_overrides[get_session] = _bad
    r = await client.get("/health/db")
    assert r.status_code == 503
    assert r.json()["db"] == "unreachable"


@pytest.mark.asyncio
async def test_metrics_exposed(client):
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert "http_request" in r.text or "python_info" in r.text
