"""ML retrain DAG — weekly, Sunday 02:00.

Loops over the four models with the uniform train/evaluate interface, logs each
run to MLflow, registers a new version, and promotes it to Production ONLY if
its primary metric improved vs the current Production model.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from airflow.decorators import dag, task

logger = logging.getLogger(__name__)

DEFAULT_ARGS = {
    "owner": "ml-platform",
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
}

# model_key -> (module path, flavor, primary metric, higher_is_better)
MODEL_SPECS = {
    "classifier": ("ml_engine.models.classifier", "sklearn", "f1_macro", True),
    "sla_risk": ("ml_engine.models.sla_risk", "xgboost", "f1", True),
    "forecaster": ("ml_engine.models.forecaster", "sklearn", "mape", False),
    "clusterer": ("ml_engine.models.clusterer", "sklearn", "silhouette", True),
}


@dag(
    dag_id="ml_retrain",
    description="Weekly retrain + evaluate + conditional promotion of ML models.",
    schedule="0 2 * * 0",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["glpi", "ml", "layer3", "retrain"],
)
def ml_retrain_dag() -> None:

    @task()
    def retrain_model_task(model_key: str) -> dict:
        import importlib

        from ml_engine import registry
        from ml_engine.config import MLConfig
        from ml_engine.data_access import read_tickets
        from ml_engine.features import dataframe_hash

        module_path, flavor, metric, higher_better = MODEL_SPECS[model_key]
        mod = importlib.import_module(module_path)
        cfg = MLConfig.from_env()
        df = read_tickets(cfg)

        model = mod.train(df, config=cfg)
        if model is None:
            logger.warning("retrain %s: cold start, skipped", model_key)
            return {"model": model_key, "promoted": False, "reason": "cold_start"}

        metrics = mod.evaluate(model, df)
        estimator = getattr(model, "estimator", model)  # unwrap dataclass bundles

        version = registry.log_run(
            model=estimator,
            registered_model_name=mod.REGISTERED_MODEL_NAME,
            params={"model_key": model_key, "random_state": cfg.random_state},
            metrics=metrics,
            input_hash=dataframe_hash(df),
            feature_schema=list(getattr(model, "feature_columns", [])),
            flavor=flavor,
            config=cfg,
        )

        prod = registry.get_production_metrics(mod.REGISTERED_MODEL_NAME, cfg)
        new_val = metrics.get(metric, 0.0)
        old_val = prod.get(metric)
        improved = (
            old_val is None
            or (new_val >= old_val if higher_better else new_val <= old_val)
        )
        if improved:
            registry.promote_to_production(mod.REGISTERED_MODEL_NAME, version, cfg)
        logger.info(
            "retrain %s: v%s %s=%s (prev=%s) promoted=%s",
            model_key, version, metric, new_val, old_val, improved,
        )
        return {"model": model_key, "version": version, "metrics": metrics, "promoted": improved}

    retrain_model_task.expand(model_key=list(MODEL_SPECS.keys()))


ml_retrain_dag()
