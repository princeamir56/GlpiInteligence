"""Unit tests for GLPIClient using requests_mock."""
from __future__ import annotations

import pytest
import requests
import requests_mock

from glpi_connector.client import GLPIClient
from glpi_connector.config import GLPIConfig
from glpi_connector.exceptions import (
    GLPIAuthError,
    GLPIRateLimited,
    GLPIUnavailable,
)


BASE = "https://glpi.example.test/apirest.php"


def _config(**overrides) -> GLPIConfig:
    defaults = dict(
        base_url=BASE,
        app_token="app-token",
        user_token="user-token",
        page_size=2,
        request_timeout=1.0,
        max_retries=2,
        retry_backoff=1.0,
        verify_ssl=False,
    )
    defaults.update(overrides)
    return GLPIConfig(**defaults)


def test_init_session_success() -> None:
    cfg = _config()
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/initSession", json={"session_token": "tok"})
        client = GLPIClient(cfg)
        token = client.init_session()
        assert token == "tok"


def test_init_session_unauthorized() -> None:
    cfg = _config()
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/initSession", status_code=401, text="bad token")
        with pytest.raises(GLPIAuthError):
            GLPIClient(cfg).init_session()


def test_init_session_network_error() -> None:
    cfg = _config()
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/initSession", exc=requests.ConnectionError("dns fail"))
        with pytest.raises(GLPIUnavailable):
            GLPIClient(cfg).init_session()


def test_context_manager_kills_session() -> None:
    cfg = _config()
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/initSession", json={"session_token": "tok"})
        kill = m.get(f"{BASE}/killSession", text="")
        with GLPIClient(cfg) as client:
            assert client._session_token == "tok"
        assert kill.called
        assert client._session_token is None


def test_search_pagination_yields_all_rows() -> None:
    cfg = _config(page_size=2)
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/initSession", json={"session_token": "tok"})
        m.get(f"{BASE}/killSession", text="")
        # Two pages: rows 0-1 then row 2, total=3
        m.get(
            f"{BASE}/search/Ticket",
            [
                {"json": {"totalcount": 3, "data": [{"2": 1}, {"2": 2}]}},
                {"json": {"totalcount": 3, "data": [{"2": 3}]}},
            ],
        )
        with GLPIClient(cfg) as client:
            rows = list(client.search("Ticket", forcedisplay=[2]))
        assert [r["2"] for r in rows] == [1, 2, 3]


def test_session_expiry_triggers_reauth() -> None:
    cfg = _config()
    with requests_mock.Mocker() as m:
        m.get(
            f"{BASE}/initSession",
            [{"json": {"session_token": "t1"}}, {"json": {"session_token": "t2"}}],
        )
        m.get(f"{BASE}/killSession", text="")
        m.get(
            f"{BASE}/search/Ticket",
            [
                {"status_code": 401, "text": "expired"},
                {"json": {"totalcount": 1, "data": [{"2": 42}]}},
            ],
        )
        with GLPIClient(cfg) as client:
            rows = list(client.search("Ticket", forcedisplay=[2]))
        assert rows == [{"2": 42}]


def test_rate_limit_retries_then_raises() -> None:
    cfg = _config(max_retries=2)
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/initSession", json={"session_token": "tok"})
        m.get(f"{BASE}/killSession", text="")
        m.get(f"{BASE}/search/Ticket", status_code=429, text="slow down")
        with GLPIClient(cfg) as client:
            with pytest.raises(GLPIRateLimited):
                list(client.search("Ticket", forcedisplay=[2]))


def test_list_items_paginates_until_short_page() -> None:
    cfg = _config(page_size=2)
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/initSession", json={"session_token": "tok"})
        m.get(f"{BASE}/killSession", text="")
        m.get(
            f"{BASE}/User",
            [
                {"json": [{"id": 1}, {"id": 2}]},
                {"json": [{"id": 3}]},
            ],
        )
        with GLPIClient(cfg) as client:
            items = client.list_items("User")
        assert [u["id"] for u in items] == [1, 2, 3]
