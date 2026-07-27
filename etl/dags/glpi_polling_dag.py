"""GLPI polling DAG — runs every 10 minutes.

Extract (parallel) -> Transform (Celery) -> Load (Celery).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from airflow.decorators import dag, task

logger = logging.getLogger(__name__)

DEFAULT_ARGS = {
    "owner": "data-platform",
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
    "depends_on_past": False,
}

CELERY_TIMEOUT = 600  # seconds to wait on a celery task before giving up


def _wait_celery(async_result, timeout: int = CELERY_TIMEOUT) -> Any:
    return async_result.get(timeout=timeout, disable_sync_subtasks=False)


@dag(
    dag_id="glpi_polling",
    description="Poll GLPI every 10 min, transform tickets, upsert to warehouse.",
    schedule="*/10 * * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["glpi", "etl", "layer2"],
)
def glpi_polling_dag() -> None:

    @task()
    def extract_tickets_task() -> list[dict[str, Any]]:
        from etl.config import get_glpi_config
        from glpi_connector.client import GLPIClient
        from glpi_connector.extractors import extract_tickets

        with GLPIClient(get_glpi_config()) as client:
            rows = extract_tickets(client)
        logger.info("extracted %d tickets", len(rows))
        return rows

    @task()
    def extract_dims_task() -> dict[str, list[dict[str, Any]]]:
        from etl.config import get_glpi_config
        from glpi_connector.client import GLPIClient
        from glpi_connector.extractors import (
            extract_categories,
            extract_entities,
            extract_groups,
            extract_users,
        )

        with GLPIClient(get_glpi_config()) as client:
            payload = {
                "dim_users": extract_users(client),
                "dim_entities": extract_entities(client),
                "dim_categories": extract_categories(client),
                "dim_groups": extract_groups(client),
            }
        for table, rows in payload.items():
            logger.info("extracted %d rows for %s", len(rows), table)
        return payload

    @task()
    def extract_followups_task() -> list[dict[str, Any]]:
        from etl.config import get_glpi_config
        from glpi_connector.client import GLPIClient
        from glpi_connector.extractors import extract_ticket_followups

        with GLPIClient(get_glpi_config()) as client:
            rows = extract_ticket_followups(client)
        logger.info("extracted %d followups", len(rows))
        return rows

    @task()
    def transform_task(
        tickets: list[dict[str, Any]],
        dims: dict[str, list[dict[str, Any]]],
        followups: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from etl.tasks import transform_tickets_task as celery_transform

        logger.info("dispatching transform to Celery (%d tickets)", len(tickets))
        async_res = celery_transform.delay(tickets)
        result = _wait_celery(async_res)
        # Pass dims through untouched; followups currently stored only for ML layer.
        result["dims"] = dims
        result["followup_count"] = len(followups)
        return result

    @task()
    def load_postgres_task(payload: dict[str, Any], execution_date: str | None = None) -> dict[str, int]:
        from etl.tasks import load_dimensions_task, load_kpis_task, load_tickets_task

        ticket_rows = _wait_celery(load_tickets_task.delay(payload["records"]))
        dim_counts = _wait_celery(load_dimensions_task.delay(payload["dims"]))
        day_iso = (execution_date or datetime.utcnow().date().isoformat())[:10]
        _wait_celery(load_kpis_task.delay(payload["kpis"], day_iso))

        result = {"tickets": ticket_rows, **dim_counts, "followups": payload["followup_count"]}
        logger.info("load summary: %s", result)
        return result

    tickets = extract_tickets_task()
    dims = extract_dims_task()
    followups = extract_followups_task()
    transformed = transform_task(tickets, dims, followups)
    load_postgres_task(transformed)


glpi_polling_dag()
