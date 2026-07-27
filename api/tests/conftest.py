"""Test fixtures.

The DB is never hit: `get_session` is overridden with a dummy session and each
router's query builder is monkeypatched per-test to return canned Pydantic models.
Auth is exercised for real (JWT create/verify) but the user lookup is stubbed.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio

# Deterministic settings before anything imports config.
os.environ.setdefault("API_JWT_SECRET", "test-secret")
os.environ.setdefault("POSTGRES_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from api.database import get_session  # noqa: E402
from api.security import CurrentUser, create_access_token, get_current_user  # noqa: E402


class _DummySession:
    async def execute(self, *a, **k):  # pragma: no cover - queries are patched
        raise AssertionError("query builder should be patched in tests")

    async def commit(self):
        return None


async def _dummy_session():
    yield _DummySession()


@pytest_asyncio.fixture
async def app_no_lifespan(monkeypatch):
    """Build the app but skip the broadcaster/DB lifespan side effects."""
    # Prevent the background broadcaster from starting real DB polling.
    import api.main as main_mod

    monkeypatch.setattr(main_mod.broadcaster, "start", lambda: None)

    async def _noop():
        return None

    monkeypatch.setattr(main_mod.broadcaster, "stop", _noop)
    monkeypatch.setattr(main_mod, "close_cache", _noop)
    monkeypatch.setattr(main_mod, "dispose_engine", _noop)

    app = main_mod.create_app()
    app.dependency_overrides[get_session] = _dummy_session
    return app


def as_role(app, role: str = "DSI", user_id: int = 1, username: str = "tester"):
    """Override auth so requests act as a user with the given role."""
    async def _override():
        return CurrentUser(user_id=user_id, username=username, role=role)

    app.dependency_overrides[get_current_user] = _override


@pytest_asyncio.fixture
async def client(app_no_lifespan):
    transport = ASGITransport(app=app_no_lifespan)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def auth_header(role: str = "DSI") -> dict:
    token = create_access_token("tester", role)
    return {"Authorization": f"Bearer {token}"}
