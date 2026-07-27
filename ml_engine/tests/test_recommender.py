from __future__ import annotations

import pandas as pd

from ml_engine import recommender


def _rules():
    return recommender.load_rules()


def test_rules_yaml_loads():
    rules = _rules()
    assert "rules" in rules
    assert set(rules["rules"]).issuperset(
        {"formation", "surcharge", "cause_racine", "automatisation"}
    )


def test_formation_rule():
    tickets = pd.DataFrame(
        [
            # user 1: critique, 90% incidents on category 7
            *[{"user_requester": 1, "type": 1, "itilcategories_id": 7} for _ in range(9)],
            {"user_requester": 1, "type": 1, "itilcategories_id": 3},
        ]
    )
    profiles = pd.DataFrame([{"user_id": 1, "profile": "critique", "confidence": 0.9,
                              "features_snapshot": {"repetitive_count": 2}}])
    recos = recommender.generate_recommendations(
        tickets=tickets, profiles=profiles, rules=_rules()
    )
    assert (recos["type"] == "FORMATION").any()
    row = recos[recos["type"] == "FORMATION"].iloc[0]
    assert row["target_user_id"] == 1
    assert row["target_category_id"] == 7


def test_automatisation_rule():
    profiles = pd.DataFrame([{"user_id": 5, "profile": "dependant", "confidence": 0.8,
                              "features_snapshot": {"repetitive_count": 42}}])
    recos = recommender.generate_recommendations(
        tickets=pd.DataFrame(), profiles=profiles, rules=_rules()
    )
    assert (recos["type"] == "AUTOMATISATION").any()


def test_cause_racine_rule():
    clusters = pd.DataFrame([{
        "cluster_id": 3, "algorithm": "dbscan", "ticket_count": 120,
        "sample_titles": ["panne wifi"], "top_keywords": ["wifi", "panne"],
        "last_seen": pd.Timestamp("2026-07-15"),
    }])
    recos = recommender.generate_recommendations(
        tickets=pd.DataFrame(), clusters=clusters, rules=_rules(),
        now=pd.Timestamp("2026-07-16").to_pydatetime(),
    )
    assert (recos["type"] == "CAUSE_RACINE").any()


def test_surcharge_rule():
    forecasts = pd.DataFrame([
        {"category_id": 2, "predicted_count": 100.0},
        {"category_id": 2, "predicted_count": 10.0},
        {"category_id": 2, "predicted_count": 10.0},
    ])
    sla = pd.DataFrame([{"technician_id": 1, "historical_sla_pct": 70.0}])
    recos = recommender.generate_recommendations(
        tickets=pd.DataFrame(), forecasts=forecasts, sla_risk=sla, rules=_rules()
    )
    assert (recos["type"] == "SURCHARGE").any()


def test_no_recos_when_nothing_triggers():
    recos = recommender.generate_recommendations(tickets=pd.DataFrame(), rules=_rules())
    assert recos.empty
    assert list(recos.columns) == recommender.RECO_COLUMNS


def test_evidence_to_json_serialises():
    clusters = pd.DataFrame([{
        "cluster_id": 1, "algorithm": "dbscan", "ticket_count": 200,
        "sample_titles": ["x"], "top_keywords": ["a"], "last_seen": pd.NaT,
    }])
    recos = recommender.generate_recommendations(
        tickets=pd.DataFrame(), clusters=clusters, rules=_rules()
    )
    js = recommender.evidence_to_json(recos)
    assert isinstance(js.iloc[0]["evidence"], str)


def test_deterministic_ids():
    profiles = pd.DataFrame([{"user_id": 5, "profile": "dependant", "confidence": 0.8,
                              "features_snapshot": {"repetitive_count": 42}}])
    a = recommender.generate_recommendations(tickets=pd.DataFrame(), profiles=profiles, rules=_rules())
    b = recommender.generate_recommendations(tickets=pd.DataFrame(), profiles=profiles, rules=_rules())
    assert a.iloc[0]["id"] == b.iloc[0]["id"]
