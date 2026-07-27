"""Unit tests for high-level extractors."""
from __future__ import annotations

import requests_mock

from glpi_connector.client import GLPIClient
from glpi_connector.config import GLPIConfig
from glpi_connector.extractors import (
    TICKET_FIELD_MAP,
    extract_categories,
    extract_entities,
    extract_groups,
    extract_ticket_followups,
    extract_tickets,
    extract_users,
)

BASE = "https://glpi.example.test/apirest.php"


def _cfg() -> GLPIConfig:
    return GLPIConfig(
        base_url=BASE, app_token="a", user_token="u",
        page_size=10, request_timeout=1.0, max_retries=2,
        retry_backoff=1.0, verify_ssl=False,
    )


def test_extract_tickets_remaps_fields() -> None:
    raw_row = {str(k): f"v{k}" for k in TICKET_FIELD_MAP}
    raw_row["2"] = 123
    raw_row["1"] = "Printer down"
    raw_row["12"] = 2
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/initSession", json={"session_token": "t"})
        m.get(f"{BASE}/killSession", text="")
        m.get(f"{BASE}/search/Ticket", json={"totalcount": 1, "data": [raw_row]})
        with GLPIClient(_cfg()) as client:
            rows = extract_tickets(client)
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == 123
    assert r["name"] == "Printer down"
    assert r["status"] == 2
    # Every mapped name is present, even if value is None for missing IDs
    assert set(r.keys()) == set(TICKET_FIELD_MAP.values())


def test_extract_users_slims_fields() -> None:
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/initSession", json={"session_token": "t"})
        m.get(f"{BASE}/killSession", text="")
        m.get(f"{BASE}/User", json=[
            {"id": 1, "name": "alice", "realname": "A", "firstname": "Al",
             "is_active": 1, "entities_id": "Root", "groups_id": [], "secret": "x"},
        ])
        with GLPIClient(_cfg()) as client:
            users = extract_users(client)
    assert users == [{
        "id": 1, "name": "alice", "realname": "A", "firstname": "Al",
        "is_active": 1, "entities_id": "Root", "groups_id": [],
    }]


def test_extract_entities_and_categories_and_groups() -> None:
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/initSession", json={"session_token": "t"})
        m.get(f"{BASE}/killSession", text="")
        m.get(f"{BASE}/Entity", json=[
            {"id": 0, "name": "Root", "completename": "Root", "entities_id": -1, "level": 0},
        ])
        m.get(f"{BASE}/ITILCategory", json=[
            {"id": 1, "name": "Network", "completename": "IT > Network", "itilcategories_id": 0},
        ])
        m.get(f"{BASE}/Group", json=[
            {"id": 1, "name": "Helpdesk", "completename": "Helpdesk",
             "groups_id": 0, "entities_id": 0},
        ])
        with GLPIClient(_cfg()) as client:
            assert extract_entities(client)[0]["name"] == "Root"
            assert extract_categories(client)[0]["completename"] == "IT > Network"
            assert extract_groups(client)[0]["name"] == "Helpdesk"


def test_extract_followups_normalizes_tickets_id_and_handles_fallback() -> None:
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/initSession", json={"session_token": "t"})
        m.get(f"{BASE}/killSession", text="")
        # ITILFollowup endpoint returns 400 -> fallback should kick in
        m.get(f"{BASE}/ITILFollowup", status_code=400, text="not available")
        m.get(f"{BASE}/TicketFollowup", json=[
            {"id": 1, "items_id": 99, "itemtype": "Ticket",
             "content": "Réparé — accent é", "date": "2026-01-02", "users_id": 5},
        ])
        with GLPIClient(_cfg()) as client:
            rows = extract_ticket_followups(client)
    assert rows[0]["tickets_id"] == 99
    assert "é" in rows[0]["content"]
