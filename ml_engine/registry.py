"""MLflow registry helpers.

All mlflow imports are lazy so importing this module (and therefore the model
modules that use it) does not require mlflow to be installed — tests that don't
touch the registry keep running.

`log_run` logs params, metrics, the input-DataFrame hash and the model
artifact, then registers a new model version. `load_production_model` loads the
latest version in the configured stage (never a hardcoded pickle path).
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from .config import MLConfig

logger = logging.getLogger(__name__)


def _mlflow():
    import mlflow  # lazy

    return mlflow


def _flavor(name: str):
    """Return the mlflow flavor module for a model kind."""
    import importlib

    mapping = {
        "sklearn": "mlflow.sklearn",
        "xgboost": "mlflow.xgboost",
        "pyfunc": "mlflow.pyfunc",
    }
    return importlib.import_module(mapping.get(name, "mlflow.sklearn"))


def _artifact_uri(root: str) -> str:
    """Normalise an artifact root to something MLflow accepts on any OS.

    Leaves values that already carry a scheme (``file:``, ``s3://`` …) and
    relative paths untouched; converts absolute local paths (incl. Windows
    ``C:\\...``) to a proper ``file://`` URI so they aren't misread as a scheme.
    """
    from pathlib import Path

    if "://" in root or root.startswith("file:"):
        return root
    p = Path(root)
    return p.as_uri() if p.is_absolute() else root


def configure(config: MLConfig | None = None) -> MLConfig:
    cfg = config or MLConfig.from_env()
    mlflow = _mlflow()
    mlflow.set_tracking_uri(cfg.tracking_uri)
    # Create the experiment with an explicit artifact location so every Airflow
    # worker + the MLflow UI (sharing the same volume) resolve identical paths.
    client = mlflow.MlflowClient()
    if client.get_experiment_by_name(cfg.experiment_name) is None:
        try:
            client.create_experiment(
                cfg.experiment_name, artifact_location=_artifact_uri(cfg.artifact_root)
            )
        except Exception:  # race: another worker created it first
            pass
    mlflow.set_experiment(cfg.experiment_name)
    return cfg


@contextmanager
def start_run(run_name: str, config: MLConfig | None = None) -> Iterator[Any]:
    cfg = configure(config)
    mlflow = _mlflow()
    with mlflow.start_run(run_name=run_name) as run:
        yield run
    logger.info("mlflow run finished: %s (uri=%s)", run_name, cfg.tracking_uri)


def log_run(
    *,
    model: Any,
    registered_model_name: str,
    params: dict[str, Any],
    metrics: dict[str, float],
    input_hash: str,
    feature_schema: list[str],
    flavor: str = "sklearn",
    run_name: str | None = None,
    config: MLConfig | None = None,
) -> str:
    """Log a full training run and register a new model version.

    Returns the model version string (e.g. "3"). If mlflow is unavailable the
    caller gets an ImportError — training callers decide whether to soft-fail.
    """
    cfg = configure(config)
    mlflow = _mlflow()
    flavor_mod = _flavor(flavor)
    with mlflow.start_run(run_name=run_name or registered_model_name):
        mlflow.log_params({k: str(v) for k, v in params.items()})
        mlflow.log_metrics({k: float(v) for k, v in metrics.items()})
        mlflow.set_tag("input_df_hash", input_hash)
        mlflow.set_tag("feature_schema", ",".join(feature_schema))
        info = flavor_mod.log_model(
            model, artifact_path="model", registered_model_name=registered_model_name
        )
    # find the just-registered version
    client = mlflow.MlflowClient()
    versions = client.search_model_versions(f"name='{registered_model_name}'")
    latest = max(versions, key=lambda v: int(v.version)) if versions else None
    version = latest.version if latest else "1"
    logger.info(
        "registered %s v%s (uri=%s)", registered_model_name, version, cfg.tracking_uri
    )
    return version


def promote_to_production(
    registered_model_name: str, version: str, config: MLConfig | None = None
) -> None:
    configure(config)
    mlflow = _mlflow()
    client = mlflow.MlflowClient()
    client.transition_model_version_stage(
        name=registered_model_name,
        version=version,
        stage="Production",
        archive_existing_versions=True,
    )
    logger.info("promoted %s v%s to Production", registered_model_name, version)


def load_production_model(
    registered_model_name: str, flavor: str = "sklearn", config: MLConfig | None = None
) -> Any | None:
    """Load the latest model in the configured stage. Returns None if nothing is
    registered/available so inference can fall back gracefully."""
    cfg = configure(config)
    flavor_mod = _flavor(flavor)
    uri = f"models:/{registered_model_name}/{cfg.registry_stage}"
    try:
        model = flavor_mod.load_model(uri)
        logger.info("loaded %s from stage %s", registered_model_name, cfg.registry_stage)
        return model
    except Exception as exc:  # not registered / no prod version yet
        logger.warning("could not load %s (%s): %s", registered_model_name, uri, exc)
        return None


def get_production_metrics(
    registered_model_name: str, config: MLConfig | None = None
) -> dict[str, float]:
    """Metrics of the current Production version — used by the retrain DAG to
    decide whether a newly trained model actually improved."""
    configure(config)
    mlflow = _mlflow()
    client = mlflow.MlflowClient()
    try:
        versions = client.get_latest_versions(registered_model_name, stages=["Production"])
    except Exception:
        return {}
    if not versions:
        return {}
    run = client.get_run(versions[0].run_id)
    return dict(run.data.metrics)
