"""Tests for the upsert loaders using an in-memory SQLite engine."""
from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from etl.load import load_dimension, load_tickets
from etl.transform import TicketTransformer

# SQLite-compatible schema (no NOW(), no DOUBLE PRECISION quirks).
SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS dim_tickets_enriched (
    id INTEGER PRIMARY KEY,
    name TEXT, content TEXT, status INTEGER, type INTEGER, priority INTEGER,
    itilcategories_id INTEGER,
    date TEXT, date_mod TEXT, solvedate TEXT, closedate TEXT, time_to_resolve TEXT,
    user_requester INTEGER, user_assign INTEGER, entities_id INTEGER,
    groups_id_requester INTEGER, urgency INTEGER, impact INTEGER,
    is_resolved INTEGER, is_high_priority INTEGER, resolution_days REAL,
    name_normalized TEXT
);
CREATE TABLE IF NOT EXISTS dim_users (
    id INTEGER PRIMARY KEY, name TEXT, realname TEXT, firstname TEXT,
    is_active INTEGER, entities_id INTEGER, groups_id TEXT
);
"""


@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:", future=True)
    with eng.begin() as conn:
        for stmt in [s.strip() for s in SQLITE_SCHEMA.split(";") if s.strip()]:
            conn.execute(text(stmt))
    return eng


def _raw_ticket(i: int, name: str, status: int = 5) -> dict:
    return {
        "id": i, "name": name, "content": "x", "status": status, "type": 1,
        "priority": 3, "itilcategories_id": 10,
        "date": "2026-06-20 09:00:00", "date_mod": "2026-06-21 10:00:00",
        "solvedate": "2026-06-21 11:00:00", "closedate": None, "time_to_resolve": None,
        "_users_id_requester": 100, "_users_id_assign": 200, "entities_id": 1,
        "_groups_id_requester": 5, "urgency": 3, "impact": 3,
    }


def test_upsert_tickets_idempotent(engine):
    df = TicketTransformer().transform([_raw_ticket(1, "Printer"), _raw_ticket(2, "VPN")])
    assert load_tickets(engine, df) == 2

    # Re-run with one updated row, one new row.
    df2 = TicketTransformer().transform([
        _raw_ticket(2, "VPN restored", status=6),
        _raw_ticket(3, "New issue"),
    ])
    load_tickets(engine, df2)

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, name FROM dim_tickets_enriched ORDER BY id")
        ).all()
    assert [(r[0], r[1]) for r in rows] == [(1, "Printer"), (2, "VPN restored"), (3, "New issue")]


def test_dimension_upsert(engine):
    users = [
        {"id": 1, "name": "alice", "realname": "A", "firstname": "Al",
         "is_active": True, "entities_id": 1, "groups_id": "[1]"},
    ]
    assert load_dimension(engine, "dim_users", users) == 1
    # update
    users[0]["realname"] = "Alpha"
    load_dimension(engine, "dim_users", users)
    with engine.begin() as conn:
        realname = conn.execute(text("SELECT realname FROM dim_users WHERE id=1")).scalar()
    assert realname == "Alpha"
