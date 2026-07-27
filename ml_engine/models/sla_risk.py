"""3.2b SLA-violation risk — XGBoost classifier, one score per technician.

Label: did the technician have an SLA violation among their tickets (see
`features._sla_violation_flag`, based on solve/close time vs the
`time_to_resolve` deadline). We predict the probability of a violation in the
next 48h. On cold start / single-class data we fall back to the historical
violation rate with `confidence="low"`.

Interface: train(df) / predict(model, df) / evaluate(model, df).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ..features import SLA_FEATURE_COLUMNS, build_sla_features, select_features

logger = logging.getLogger(__name__)

REGISTERED_MODEL_NAME = "glpi_sla_risk"


@dataclass
class SLARiskModel:
    estimator: Any            # xgb booster/classifier, or None for fallback
    feature_columns: list[str]
    fallback_rate: float      # base violation rate used when estimator is None
    confidence: str = "high"


def train(df: pd.DataFrame, *, config: Any | None = None) -> SLARiskModel | None:
    from ..config import MLConfig

    cfg = config or MLConfig.from_env()
    if df is None or len(df) < cfg.cold_start_min_rows:
        logger.warning("sla_risk.train: cold start, skipping")
        return None

    feats = build_sla_features(df)
    if feats.empty:
        logger.warning("sla_risk.train: no technician features")
        return None

    X = select_features(feats, SLA_FEATURE_COLUMNS)
    y = feats["sla_violation"].to_numpy(dtype=int)
    base_rate = float(y.mean()) if len(y) else 0.0

    # Single class or too few technicians -> statistical fallback.
    if len(np.unique(y)) < 2 or len(feats) < 5:
        logger.warning("sla_risk.train: single-class/small data, using fallback rate %.3f", base_rate)
        return SLARiskModel(None, list(SLA_FEATURE_COLUMNS), base_rate, "low")

    from xgboost import XGBClassifier

    clf = XGBClassifier(
        n_estimators=150,
        max_depth=4,
        learning_rate=0.1,
        subsample=0.9,
        colsample_bytree=0.9,
        eval_metric="logloss",
        random_state=cfg.random_state,
        n_jobs=-1,
    )
    clf.fit(X, y)
    logger.info("sla_risk.train: fitted on %d technicians", len(feats))
    return SLARiskModel(clf, list(SLA_FEATURE_COLUMNS), base_rate, "high")


def predict(model: SLARiskModel, df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame[technician_id, risk_score, next_48h_prediction, confidence]."""
    cols = ["technician_id", "risk_score", "next_48h_prediction", "confidence"]
    if model is None:
        return pd.DataFrame(columns=cols)
    feats = build_sla_features(df)
    if feats.empty:
        return pd.DataFrame(columns=cols)

    if model.estimator is None:
        scores = np.full(len(feats), model.fallback_rate, dtype=float)
        conf = "low"
    else:
        X = select_features(feats, model.feature_columns)
        scores = model.estimator.predict_proba(X)[:, 1]
        conf = model.confidence

    out = pd.DataFrame(
        {
            "technician_id": feats.index.to_numpy(),
            "risk_score": np.round(scores, 4),
            "next_48h_prediction": (scores >= 0.5).astype(int),
            "confidence": conf,
        }
    )
    logger.info("sla_risk.predict: %d technicians scored", len(out))
    return out


def evaluate(model: SLARiskModel, df: pd.DataFrame) -> dict[str, float]:
    if model is None:
        return {"accuracy": 0.0, "f1": 0.0, "auc": 0.0, "n_techs": 0.0}
    feats = build_sla_features(df)
    if feats.empty:
        return {"accuracy": 0.0, "f1": 0.0, "auc": 0.0, "n_techs": 0.0}
    y_true = feats["sla_violation"].to_numpy(dtype=int)
    pred = predict(model, df)
    y_pred = pred["next_48h_prediction"].to_numpy(dtype=int)
    scores = pred["risk_score"].to_numpy(dtype=float)

    from sklearn.metrics import accuracy_score, f1_score, roc_auc_score

    metrics = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "n_techs": float(len(feats)),
    }
    try:
        metrics["auc"] = float(roc_auc_score(y_true, scores)) if len(np.unique(y_true)) > 1 else 0.0
    except Exception:
        metrics["auc"] = 0.0
    return metrics
