"""ML inference DAG — runs hourly.

check_freshness -> [classify | forecast + sla | cluster] -> recommend -> load.

Tasks are thin wrappers: they read tickets once, call the pure model modules,
and hand results to the loaders. Heavy work stays in ml_engine.* modules.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from airflow.decorators import dag, task

logger = logging.getLogger(__name__)

DEFAULT_ARGS = {
    "owner": "ml-platform",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "depends_on_past": False,
}


@dag(
    dag_id="ml_inference",
    description="Hourly ML inference: profiles, forecasts, SLA risk, clusters, recommendations.",
    schedule="0 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["glpi", "ml", "layer3"],
)
def ml_inference_dag() -> None:

    @task()
    def check_data_freshness_task() -> bool:
        from ml_engine.config import MLConfig
        from ml_engine.data_access import count_recent_tickets

        cfg = MLConfig.from_env()
        recent = count_recent_tickets(cfg, hours=24)
        if recent == 0:
            logger.warning("no tickets modified in the last 24h — proceeding on full table")
        return True

    @task()
    def classify_users_task(_ready: bool) -> list[dict]:
        from ml_engine.config import MLConfig
        from ml_engine.data_access import read_tickets
        from ml_engine.models import classifier
        from ml_engine import registry

        cfg = MLConfig.from_env()
        df = read_tickets(cfg)
        model = registry.load_production_model(classifier.REGISTERED_MODEL_NAME, "sklearn", cfg)
        if model is None:
            model = classifier.train(df, config=cfg)  # fall back to on-the-fly train
        if model is None:
            return []
        return classifier.predict(model, df).to_dict(orient="records")

    @task()
    def forecast_volume_task(_ready: bool) -> list[dict]:
        from ml_engine.config import MLConfig
        from ml_engine.data_access import read_tickets
        from ml_engine.models import forecaster

        cfg = MLConfig.from_env()
        df = read_tickets(cfg)
        model = forecaster.train(df, config=cfg)
        return forecaster.predict(model, df).to_dict(orient="records")

    @task()
    def predict_sla_risk_task(_ready: bool) -> list[dict]:
        from ml_engine.config import MLConfig
        from ml_engine.data_access import read_tickets
        from ml_engine.models import sla_risk
        from ml_engine import registry

        cfg = MLConfig.from_env()
        df = read_tickets(cfg)
        model = registry.load_production_model(sla_risk.REGISTERED_MODEL_NAME, "xgboost", cfg)
        if model is None:
            model = sla_risk.train(df, config=cfg)
        if model is None:
            return []
        return sla_risk.predict(model, df).to_dict(orient="records")

    @task()
    def cluster_tickets_task(_ready: bool) -> list[dict]:
        from ml_engine.config import MLConfig
        from ml_engine.data_access import read_tickets
        from ml_engine.models import clusterer

        cfg = MLConfig.from_env()
        df = read_tickets(cfg)
        model = clusterer.train(df, config=cfg, algorithm="dbscan")
        if model is None:
            return []
        return clusterer.predict(model, df).to_dict(orient="records")

    @task()
    def generate_recommendations_task(
        profiles: list[dict], forecasts: list[dict], sla: list[dict], clusters: list[dict]
    ) -> list[dict]:
        import pandas as pd
        from ml_engine.config import MLConfig
        from ml_engine.data_access import read_tickets
        from ml_engine.recommender import evidence_to_json, generate_recommendations

        cfg = MLConfig.from_env()
        df = read_tickets(cfg)
        recos = generate_recommendations(
            tickets=df,
            profiles=pd.DataFrame(profiles),
            forecasts=pd.DataFrame(forecasts),
            sla_risk=pd.DataFrame(sla),
            clusters=pd.DataFrame(clusters),
        )
        return evidence_to_json(recos).to_dict(orient="records")

    @task()
    def load_ml_results_task(
        profiles: list[dict], forecasts: list[dict], sla: list[dict],
        clusters: list[dict], recos: list[dict],
    ) -> dict[str, int]:
        import pandas as pd
        from ml_engine import load
        from ml_engine.config import MLConfig
        from ml_engine.data_access import get_engine

        engine = get_engine(MLConfig.from_env())
        load.ensure_schema(engine)
        counts = {
            "profiles": load.load_user_profiles(engine, pd.DataFrame(profiles)),
            "forecasts": load.load_forecasts(engine, pd.DataFrame(forecasts)),
            "sla_risk": load.load_sla_risk(engine, pd.DataFrame(sla)),
            "clusters": load.load_clusters(engine, pd.DataFrame(clusters)),
            "recommendations": load.load_recommendations(engine, pd.DataFrame(recos)),
        }
        logger.info("load_ml_results: %s", counts)
        return counts

    ready = check_data_freshness_task()
    profiles = classify_users_task(ready)
    forecasts = forecast_volume_task(ready)
    sla = predict_sla_risk_task(ready)
    clusters = cluster_tickets_task(ready)
    recos = generate_recommendations_task(profiles, forecasts, sla, clusters)
    load_ml_results_task(profiles, forecasts, sla, clusters, recos)


ml_inference_dag()
