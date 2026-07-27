"""Unit tests for TicketTransformer — pure pandas, no external services."""
from __future__ import annotations

import pandas as pd
import pytest

from etl.transform import TicketTransformer, normalize_title


SAMPLE_ROWS = [
    {
        "id": 1, "name": "Re: Tr: Printer broken", "content": "...",
        "status": 5, "type": 1, "priority": 3, "itilcategories_id": 10,
        "date": "2026-06-20 09:00:00", "date_mod": "2026-06-21 10:00:00",
        "solvedate": "2026-06-21 11:00:00", "closedate": None, "time_to_resolve": None,
        "_users_id_requester": 100, "_users_id_assign": 200, "entities_id": 1,
        "_groups_id_requester": 5, "urgency": 3, "impact": 3,
    },
    {
        "id": 2, "name": "VPN down", "content": "urgent",
        "status": 2, "type": 1, "priority": 5, "itilcategories_id": 11,
        "date": "2026-06-22 08:00:00", "date_mod": "2026-06-22 08:30:00",
        "solvedate": None, "closedate": None, "time_to_resolve": None,
        "_users_id_requester": 101, "_users_id_assign": None, "entities_id": 2,
        "_groups_id_requester": None, "urgency": 5, "impact": 5,
    },
]


def test_normalize_title_strips_prefixes():
    assert normalize_title("Re: Tr: Hello") == "hello"
    assert normalize_title("FWD: alert") == "alert"
    assert normalize_title("  RE:RE: hi  ") == "hi"
    assert normalize_title(None) == ""


def test_transform_renames_and_derives():
    df = TicketTransformer().transform(SAMPLE_ROWS)
    assert "user_requester" in df.columns
    assert "user_assign" in df.columns
    assert "groups_id_requester" in df.columns
    assert "_users_id_requester" not in df.columns

    assert df.loc[0, "is_resolved"] is True or df.loc[0, "is_resolved"] == True  # noqa
    assert bool(df.loc[1, "is_resolved"]) is False
    assert bool(df.loc[1, "is_high_priority"]) is True

    assert df.loc[0, "name_normalized"] == "printer broken"
    assert df.loc[1, "name_normalized"] == "vpn down"

    # resolution_days: row 0 ~ 1.08 days, row 1 NaN
    assert df.loc[0, "resolution_days"] == pytest.approx(1.0833333, rel=1e-3)
    assert pd.isna(df.loc[1, "resolution_days"])


def test_transform_empty():
    df = TicketTransformer().transform([])
    assert df.empty
    assert "name_normalized" in df.columns


def test_kpis():
    df = TicketTransformer().transform(SAMPLE_ROWS)
    k = TicketTransformer.compute_kpis(df)
    assert k["total_tickets"] == 2
    assert k["resolved_pct"] == 50.0
    assert k["high_priority_count"] == 1
    assert k["avg_resolution_days"] == pytest.approx(1.08, abs=0.01)


def test_kpis_empty():
    df = TicketTransformer().transform([])
    k = TicketTransformer.compute_kpis(df)
    assert k == {"total_tickets": 0, "resolved_pct": 0.0,
                 "high_priority_count": 0, "avg_resolution_days": 0.0}


def test_dates_are_parsed():
    df = TicketTransformer().transform(SAMPLE_ROWS)
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert pd.api.types.is_datetime64_any_dtype(df["solvedate"])
