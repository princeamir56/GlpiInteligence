from __future__ import annotations

from dataclasses import replace

from ml_engine.config import MLConfig
from ml_engine.models import sla_risk


def _cfg(min_rows=10):
    return replace(MLConfig.from_env(), cold_start_min_rows=min_rows)


def test_train_predict(tickets):
    model = sla_risk.train(tickets, config=_cfg())
    assert model is not None
    preds = sla_risk.predict(model, tickets)
    assert set(preds.columns) == {
        "technician_id", "risk_score", "next_48h_prediction", "confidence"
    }
    assert preds["risk_score"].between(0, 1).all()
    assert preds["next_48h_prediction"].isin([0, 1]).all()


def test_evaluate(tickets):
    model = sla_risk.train(tickets, config=_cfg())
    metrics = sla_risk.evaluate(model, tickets)
    assert set(["accuracy", "f1", "n_techs"]).issubset(metrics)
    assert 0.0 <= metrics["accuracy"] <= 1.0


def test_cold_start(tiny_tickets):
    model = sla_risk.train(tiny_tickets, config=_cfg(min_rows=1000))
    assert model is None
    assert sla_risk.predict(model, tiny_tickets).empty
