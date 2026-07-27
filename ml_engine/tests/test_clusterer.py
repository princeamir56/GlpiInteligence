from __future__ import annotations

from dataclasses import replace

import pandas as pd

from ml_engine.config import MLConfig
from ml_engine.models import clusterer


def _cfg(**kw):
    return replace(MLConfig.from_env(), **kw)


def test_preprocess_fallback_runs():
    out = clusterer.preprocess_texts(["Bonjour, l'imprimante est en panne!!!"])
    assert isinstance(out, list) and len(out) == 1
    assert "imprimante" in out[0] or "panne" in out[0]


def test_sentiment():
    assert clusterer.sentiment_label("impossible panne urgent bloqué") == "negative"
    assert clusterer.sentiment_label("merci parfait resolu") == "positive"
    assert clusterer.sentiment_label("ceci est une phrase") == "neutral"


def test_severity_thresholds():
    assert clusterer.severity_for_count(150) == "CRITIQUE"
    assert clusterer.severity_for_count(60) == "ÉLEVÉ"
    assert clusterer.severity_for_count(25) == "MODÉRÉ"
    assert clusterer.severity_for_count(3) == "FAIBLE"


def test_kmeans_cluster_shape(text_tickets):
    # KMeans is deterministic and works with the TF-IDF fallback (no ST needed).
    model = clusterer.train(text_tickets, config=_cfg(kmeans_k=3), algorithm="kmeans")
    assert model is not None
    summary = clusterer.predict(model, text_tickets)
    assert not summary.empty
    expected = {
        "cluster_id", "algorithm", "sample_titles", "ticket_count",
        "top_keywords", "severity", "first_seen", "last_seen", "neg_ratio",
    }
    assert set(summary.columns) == expected
    assert summary["ticket_count"].sum() <= len(text_tickets)
    assert summary["sample_titles"].map(lambda t: len(t) <= 5).all()
    assert (summary["algorithm"] == "kmeans").all()


def test_empty_corpus():
    assert clusterer.train(pd.DataFrame()) is None
