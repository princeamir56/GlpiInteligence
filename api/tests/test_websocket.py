import os

import pytest

os.environ.setdefault("API_JWT_SECRET", "test-secret")

from starlette.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

import api.main as main_mod  # noqa: E402
from api.alerts.broadcaster import AlertBroadcaster, broadcaster  # noqa: E402
from api.security import create_access_token  # noqa: E402


@pytest.fixture
def ws_app(monkeypatch):
    monkeypatch.setattr(main_mod.broadcaster, "start", lambda: None)

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(main_mod.broadcaster, "stop", _noop)
    monkeypatch.setattr(main_mod, "close_cache", _noop)
    monkeypatch.setattr(main_mod, "dispose_engine", _noop)
    return main_mod.create_app()


def test_ws_rejects_missing_token(ws_app):
    with TestClient(ws_app) as tc:
        with pytest.raises((WebSocketDisconnect, Exception)):
            with tc.websocket_connect("/ws/alerts"):
                pass


def test_ws_rejects_bad_token(ws_app):
    with TestClient(ws_app) as tc:
        with pytest.raises(WebSocketDisconnect):
            with tc.websocket_connect("/ws/alerts?token=not-a-jwt"):
                pass


def test_ws_accepts_valid_token(ws_app):
    token = create_access_token("tester", "DSI")
    before = broadcaster.client_count
    with TestClient(ws_app) as tc:
        with tc.websocket_connect(f"/ws/alerts?token={token}"):
            assert broadcaster.client_count == before + 1
    # disconnect unregisters
    assert broadcaster.client_count == before


@pytest.mark.asyncio
async def test_broadcaster_fanout_and_dead_client():
    b = AlertBroadcaster()

    class FakeWS:
        def __init__(self, fail=False):
            self.fail = fail
            self.received = []

        async def send_json(self, msg):
            if self.fail:
                raise RuntimeError("dead")
            self.received.append(msg)

    good, dead = FakeWS(), FakeWS(fail=True)
    await b.register(good)
    await b.register(dead)
    await b.broadcast({"type": "alert", "title": "x"})
    assert good.received == [{"type": "alert", "title": "x"}]
    # dead client is pruned after a failed send
    assert b.client_count == 1
