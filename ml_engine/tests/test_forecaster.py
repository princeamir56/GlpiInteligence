from __future__ import annotations

import numpy as np
import pandas as pd

from ml_engine.config import MLConfig
from ml_engine.models import forecaster


def _long_series_tickets(days=60, seed=1):
    """One category with a long daily history so a real forecast (or the average
    fallback) can run without Prophet installed."""
    rng = np.random.default_rng(seed)
    base = pd.Timestamp("2026-01-01")
    rows = []
    tid = 1
    for d in range(days):
        for _ in range(int(rng.integers(1, 6))):
            date = base + pd.Timedelta(days=d)
            rows.append({
                "id": tid, "itilcategories_id": 1, "date": date,
                "status": 6, "type": 1, "priority": 3,
                "user_requester": 1, "user_assign": 101,
                "name": "x", "content": "y", "name_normalized": "x",
                "solvedate": date, "closedate": pd.NaT,
                "time_to_resolve": date + pd.Timedelta(days=3), "resolution_days": 0.5,
            })
            tid += 1
    return pd.DataFrame(rows)


def test_train_predict_horizon():
    df = _long_series_tickets()
    model = forecaster.train(df)
    assert model  # at least one category model
    preds = forecaster.predict(model, df)
    assert set(preds.columns) == {
        "category_id", "forecast_date", "predicted_count",
        "lower_bound", "upper_bound", "confidence",
    }
    # 72h horizon -> 3 daily points per category
    assert len(preds) == 3 * len(model)
    assert (preds["predicted_count"] >= 0).all()
    assert (preds["upper_bound"] >= preds["lower_bound"]).all()


def test_short_series_low_confidence():
    # only a few days -> average fallback, confidence low
    df = _long_series_tickets(days=4)
    model = forecaster.train(df)
    preds = forecaster.predict(model, df)
    assert (preds["confidence"] == "low").all()


def test_empty():
    model = forecaster.train(pd.DataFrame())
    assert model == {}
    assert forecaster.predict(model, pd.DataFrame()).empty
