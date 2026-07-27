from __future__ import annotations

import pandas as pd

from ml_engine.features import (
    SLA_FEATURE_COLUMNS,
    USER_FEATURE_COLUMNS,
    build_daily_category_counts,
    build_sla_features,
    build_text_corpus,
    build_user_features,
    dataframe_hash,
)


def test_user_features_shape_and_columns(tickets):
    feats = build_user_features(tickets)
    assert not feats.empty
    assert list(feats.columns) == list(USER_FEATURE_COLUMNS)
    assert feats.index.name == "user_id"
    # per-user consistency: incidents + requests <= total
    assert (feats["incidents_count"] + feats["requests_count"] <= feats["total_tickets"]).all()
    assert (feats["resolved_count"] + feats["open_count"] == feats["total_tickets"]).all()


def test_user_features_empty():
    feats = build_user_features(pd.DataFrame())
    assert feats.empty
    assert list(feats.columns) == list(USER_FEATURE_COLUMNS)


def test_daily_category_counts_top_n(tickets):
    counts = build_daily_category_counts(tickets, top_n=3)
    assert 0 < len(counts) <= 3
    for series in counts.values():
        assert list(series.columns) == ["ds", "y"]
        assert (series["y"] >= 0).all()


def test_sla_features(tickets):
    feats = build_sla_features(tickets)
    assert not feats.empty
    assert set(SLA_FEATURE_COLUMNS).issubset(feats.columns)
    assert feats["sla_violation"].isin([0, 1]).all()
    assert (feats["historical_sla_pct"].between(0, 100)).all()


def test_text_corpus(tickets):
    corpus = build_text_corpus(tickets)
    assert list(corpus.columns) == ["id", "itilcategories_id", "date", "text"]
    assert (corpus["text"].str.len() > 0).all()


def test_dataframe_hash_stable(tickets):
    assert dataframe_hash(tickets) == dataframe_hash(tickets.copy())
    assert dataframe_hash(tickets) != dataframe_hash(tickets.iloc[:-1])
