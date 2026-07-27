"""3.2a Volume forecast — one Prophet model per top-N category.

Input: raw dim_tickets_enriched. Output: 72h-ahead daily forecast with lower/
upper bounds per category. On "not enough data" (short series) we fall back to a
trailing average and flag `confidence="low"`.

Interface: train(df) / predict(model, df) / evaluate(model, df).
The "model" here is a dict {category_id: fitted_prophet_or_fallback}.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from ..features import build_daily_category_counts

logger = logging.getLogger(__name__)

REGISTERED_MODEL_NAME = "glpi_volume_forecaster"
MIN_POINTS_FOR_PROPHET = 14  # need ~2 weeks of daily points to fit seasonality


class _AverageFallback:
    """Trailing-mean forecaster used when a series is too short for Prophet."""

    confidence = "low"

    def __init__(self, series: pd.DataFrame) -> None:
        y = series["y"].tail(14)
        self.mean = float(y.mean()) if len(y) else 0.0
        self.std = float(y.std(ddof=0)) if len(y) > 1 else 0.0
        self.last_ds = pd.to_datetime(series["ds"]).max() if len(series) else pd.Timestamp.utcnow()

    def forecast(self, horizon_days: int) -> pd.DataFrame:
        dates = [self.last_ds + pd.Timedelta(days=i + 1) for i in range(horizon_days)]
        return pd.DataFrame(
            {
                "ds": dates,
                "yhat": self.mean,
                "yhat_lower": max(self.mean - 1.96 * self.std, 0.0),
                "yhat_upper": self.mean + 1.96 * self.std,
            }
        )


def _fit_one(series: pd.DataFrame, config: Any) -> Any:
    if len(series) < MIN_POINTS_FOR_PROPHET:
        return _AverageFallback(series)
    try:
        from prophet import Prophet
    except Exception as exc:  # prophet not installed -> degrade
        logger.warning("prophet unavailable (%s); using average fallback", exc)
        return _AverageFallback(series)
    m = Prophet(
        daily_seasonality=False,
        weekly_seasonality=True,
        yearly_seasonality=False,
        interval_width=0.8,
    )
    m.fit(series[["ds", "y"]])
    setattr(m, "confidence", "high")
    return m


def train(df: pd.DataFrame, *, config: Any | None = None) -> dict[int, Any]:
    from ..config import MLConfig

    cfg = config or MLConfig.from_env()
    counts = build_daily_category_counts(df, top_n=cfg.top_n_categories)
    if not counts:
        logger.warning("forecaster.train: no category series available")
        return {}
    models = {cat: _fit_one(series, cfg) for cat, series in counts.items()}
    logger.info("forecaster.train: fitted %d category models", len(models))
    return models


def _predict_one(model: Any, horizon_days: int) -> pd.DataFrame:
    if isinstance(model, _AverageFallback):
        fc = model.forecast(horizon_days)
        fc["confidence"] = "low"
        return fc
    future = model.make_future_dataframe(periods=horizon_days, freq="D")
    fc = model.predict(future).tail(horizon_days)[
        ["ds", "yhat", "yhat_lower", "yhat_upper"]
    ].copy()
    fc["yhat"] = fc["yhat"].clip(lower=0.0)
    fc["yhat_lower"] = fc["yhat_lower"].clip(lower=0.0)
    fc["confidence"] = getattr(model, "confidence", "high")
    return fc


def predict(model: dict[int, Any], df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Return DataFrame[category_id, forecast_date, predicted_count,
    lower_bound, upper_bound, confidence] for the next 72h (3 daily points)."""
    from ..config import MLConfig

    cfg = MLConfig.from_env()
    horizon_days = max(1, cfg.forecast_horizon_hours // 24)
    rows = []
    for cat, m in (model or {}).items():
        fc = _predict_one(m, horizon_days)
        for _, r in fc.iterrows():
            rows.append(
                {
                    "category_id": int(cat),
                    "forecast_date": pd.to_datetime(r["ds"]).date(),
                    "predicted_count": round(float(r["yhat"]), 2),
                    "lower_bound": round(float(r["yhat_lower"]), 2),
                    "upper_bound": round(float(r["yhat_upper"]), 2),
                    "confidence": r["confidence"],
                }
            )
    out = pd.DataFrame(
        rows,
        columns=[
            "category_id",
            "forecast_date",
            "predicted_count",
            "lower_bound",
            "upper_bound",
            "confidence",
        ],
    )
    logger.info("forecaster.predict: %d forecast rows", len(out))
    return out


def evaluate(model: dict[int, Any], df: pd.DataFrame) -> dict[str, float]:
    """Backtest MAPE/RMSE on the last `horizon` points of each real series."""
    from ..config import MLConfig

    cfg = MLConfig.from_env()
    counts = build_daily_category_counts(df, top_n=cfg.top_n_categories)
    errs_rmse: list[float] = []
    errs_mape: list[float] = []
    horizon = max(1, cfg.forecast_horizon_hours // 24)
    for cat, series in counts.items():
        if len(series) <= horizon + MIN_POINTS_FOR_PROPHET:
            continue
        train_s = series.iloc[:-horizon]
        test_s = series.iloc[-horizon:]
        m = _fit_one(train_s, cfg)
        fc = _predict_one(m, horizon)
        y_true = test_s["y"].to_numpy(dtype=float)
        y_pred = fc["yhat"].to_numpy(dtype=float)[: len(y_true)]
        if len(y_pred) < len(y_true):
            continue
        errs_rmse.append(float(np.sqrt(np.mean((y_true - y_pred) ** 2))))
        denom = np.where(y_true == 0, 1.0, y_true)
        errs_mape.append(float(np.mean(np.abs((y_true - y_pred) / denom)) * 100.0))
    return {
        "rmse": float(np.mean(errs_rmse)) if errs_rmse else 0.0,
        "mape": float(np.mean(errs_mape)) if errs_mape else 0.0,
        "n_categories": float(len(counts)),
    }
