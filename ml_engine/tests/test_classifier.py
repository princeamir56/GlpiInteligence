from __future__ import annotations

from dataclasses import replace

import pandas as pd

from ml_engine.config import MLConfig
from ml_engine.models import classifier


def _cfg(min_rows=10):
    base = MLConfig.from_env()
    return replace(base, cold_start_min_rows=min_rows)


def test_rule_labeler_covers_classes(tickets):
    from ml_engine.features import build_user_features

    labels = classifier.label_users(build_user_features(tickets))
    assert set(labels.unique()).issubset(set(classifier.PROFILES))
    assert len(labels.unique()) >= 2


def test_train_predict_output(tickets):
    model = classifier.train(tickets, config=_cfg())
    assert model is not None
    preds = classifier.predict(model, tickets)
    assert set(preds.columns) == {"user_id", "profile", "confidence", "features_snapshot"}
    assert len(preds) == tickets["user_requester"].nunique()
    assert preds["profile"].isin(classifier.PROFILES).all()
    assert preds["confidence"].between(0, 1).all()
    assert isinstance(preds.iloc[0]["features_snapshot"], dict)


def test_evaluate_self_consistency(tickets):
    model = classifier.train(tickets, config=_cfg())
    metrics = classifier.evaluate(model, tickets)
    # RF trained to reproduce the rules should fit them very well.
    assert metrics["accuracy"] >= 0.9
    assert 0.0 <= metrics["f1_macro"] <= 1.0


def test_cold_start_returns_none(tiny_tickets):
    model = classifier.train(tiny_tickets, config=_cfg(min_rows=1000))
    assert model is None
    # predict on None must not crash
    assert classifier.predict(model, tiny_tickets).empty
