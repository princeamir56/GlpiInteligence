"""3.1 User classification — RandomForest over behaviour features.

We have no hand-labelled data, so we bootstrap labels with a documented,
rule-based labeler on the same features, then train a RandomForest to reproduce
and generalise those rules. The model is what gets registered & served; the
rules are only the training signal.

Profiles (French, as the dashboard expects):
  * autonome  — few tickets, mostly resolved, rarely high priority, self-reliant.
  * standard  — average activity, nothing notable.
  * dependant — many tickets, many repetitive ones / high tickets_per_month.
  * critique  — high-priority heavy and/or slow-to-resolve, business-critical.

Interface: train(df) / predict(model, df) / evaluate(model, df).
`df` is the raw dim_tickets_enriched frame; feature building happens inside.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ..config import RANDOM_STATE
from ..features import USER_FEATURE_COLUMNS, build_user_features, select_features

logger = logging.getLogger(__name__)

PROFILES = ("autonome", "standard", "dependant", "critique")
REGISTERED_MODEL_NAME = "glpi_user_classifier"


# --------------------------------------------------------------------------- #
# Rule-based labeler (documented). Order matters: critique > dependant >
# autonome > standard (first match wins).
# --------------------------------------------------------------------------- #
def rule_label(row: pd.Series) -> str:
    total = row["total_tickets"]
    high = row["high_priority_count"]
    avg_res = row["avg_resolution_days"]
    repetitive = row["repetitive_count"]
    per_month = row["tickets_per_month"]
    resolved_ratio = row["resolved_count"] / total if total else 0.0
    high_ratio = high / total if total else 0.0

    # critique: business-critical — lots of high priority OR chronically slow.
    if high_ratio >= 0.30 or (high >= 3 and avg_res >= 5):
        return "critique"
    # dependant: leans on IT — heavy volume, repetitive, or high monthly rate.
    if per_month >= 4 or repetitive >= 5 or total >= 20:
        return "dependant"
    # autonome: light user, mostly self-resolved, no high-prio noise.
    if total <= 5 and resolved_ratio >= 0.8 and high == 0:
        return "autonome"
    return "standard"


def label_users(features: pd.DataFrame) -> pd.Series:
    if features.empty:
        return pd.Series(dtype="object", name="profile")
    return features.apply(rule_label, axis=1).rename("profile")


@dataclass
class ClassifierModel:
    """Bundle so predict() can rebuild features and decode labels."""

    estimator: Any
    classes: list[str]
    feature_columns: list[str]


def train(df: pd.DataFrame, *, config: Any | None = None) -> ClassifierModel | None:
    """Train the RandomForest on rule-labelled user features.

    Returns None on cold start (too few tickets) so callers can skip + warn.
    """
    from ..config import MLConfig

    cfg = config or MLConfig.from_env()
    if df is None or len(df) < cfg.cold_start_min_rows:
        logger.warning(
            "classifier.train: cold start (%d < %d rows), skipping",
            0 if df is None else len(df),
            cfg.cold_start_min_rows,
        )
        return None

    feats = build_user_features(df)
    if feats.empty:
        logger.warning("classifier.train: no user features, skipping")
        return None

    labels = label_users(feats)
    X = select_features(feats, USER_FEATURE_COLUMNS)
    y = labels.to_numpy()

    from sklearn.ensemble import RandomForestClassifier

    clf = RandomForestClassifier(
        n_estimators=200,
        max_depth=None,
        class_weight="balanced",
        random_state=cfg.random_state,
        n_jobs=-1,
    )
    clf.fit(X, y)
    logger.info("classifier.train: fitted on %d users, classes=%s", len(feats), list(clf.classes_))
    return ClassifierModel(
        estimator=clf,
        classes=list(clf.classes_),
        feature_columns=list(USER_FEATURE_COLUMNS),
    )


def predict(model: ClassifierModel, df: pd.DataFrame) -> pd.DataFrame:
    """Return DataFrame[user_id, profile, confidence, features_snapshot(dict)]."""
    feats = build_user_features(df)
    if feats.empty or model is None:
        return pd.DataFrame(
            columns=["user_id", "profile", "confidence", "features_snapshot"]
        )
    X = select_features(feats, model.feature_columns)
    proba = model.estimator.predict_proba(X)
    idx = proba.argmax(axis=1)
    profiles = model.estimator.classes_[idx]
    confidence = proba.max(axis=1)

    snapshots = feats[list(model.feature_columns)].to_dict(orient="records")
    out = pd.DataFrame(
        {
            "user_id": feats.index.to_numpy(),
            "profile": profiles,
            "confidence": np.round(confidence, 4),
            "features_snapshot": snapshots,
        }
    )
    logger.info("classifier.predict: %d users scored", len(out))
    return out


def evaluate(model: ClassifierModel, df: pd.DataFrame) -> dict[str, float]:
    """Accuracy / macro-F1 of the model vs the rule labels (self-consistency)."""
    if model is None:
        return {"accuracy": 0.0, "f1_macro": 0.0, "n_users": 0.0}
    feats = build_user_features(df)
    if feats.empty:
        return {"accuracy": 0.0, "f1_macro": 0.0, "n_users": 0.0}
    y_true = label_users(feats).to_numpy()
    X = select_features(feats, model.feature_columns)
    y_pred = model.estimator.predict(X)

    from sklearn.metrics import accuracy_score, f1_score

    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "n_users": float(len(feats)),
    }


def _cli() -> None:  # pragma: no cover - manual entry point
    import argparse

    from ..config import MLConfig
    from ..data_access import read_tickets
    from .. import registry

    parser = argparse.ArgumentParser(description="Train the GLPI user classifier.")
    parser.add_argument("--train", action="store_true")
    parser.add_argument("--register", action="store_true", help="log & register in MLflow")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    cfg = MLConfig.from_env()
    df = read_tickets(cfg)
    model = train(df, config=cfg)
    if model is None:
        print("Cold start — model not trained.")
        return
    metrics = evaluate(model, df)
    print("metrics:", metrics)
    if args.register:
        from ..features import dataframe_hash

        version = registry.log_run(
            model=model.estimator,
            registered_model_name=REGISTERED_MODEL_NAME,
            params={"n_estimators": 200, "random_state": cfg.random_state},
            metrics=metrics,
            input_hash=dataframe_hash(df),
            feature_schema=list(USER_FEATURE_COLUMNS),
            flavor="sklearn",
            config=cfg,
        )
        print(f"registered version {version}")


if __name__ == "__main__":  # pragma: no cover
    _cli()
