from __future__ import annotations

import sys
import types
from unittest import mock

import pytest

from ml_engine import registry
from ml_engine.config import MLConfig


def _fake_mlflow():
    """A minimal fake mlflow module wired into sys.modules for registry tests."""
    m = types.SimpleNamespace()
    m.set_tracking_uri = mock.Mock()
    m.set_experiment = mock.Mock()

    class _Run:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    m.start_run = mock.Mock(return_value=_Run())
    m.log_params = mock.Mock()
    m.log_metrics = mock.Mock()
    m.set_tag = mock.Mock()

    class _Client:
        def get_experiment_by_name(self, name):
            return types.SimpleNamespace(experiment_id="1")  # already exists

        def create_experiment(self, name, artifact_location=None):
            return "1"

        def search_model_versions(self, q):
            v = types.SimpleNamespace(version="3", run_id="r1")
            return [v]

        def get_latest_versions(self, name, stages=None):
            return [types.SimpleNamespace(version="3", run_id="r1")]

        def get_run(self, run_id):
            return types.SimpleNamespace(data=types.SimpleNamespace(metrics={"f1_macro": 0.8}))

        def transition_model_version_stage(self, **kw):
            self.transitioned = kw

    m.MlflowClient = _Client
    return m


def test_configure_sets_uri(monkeypatch):
    fake = _fake_mlflow()
    monkeypatch.setattr(registry, "_mlflow", lambda: fake)
    cfg = registry.configure(MLConfig.from_env())
    fake.set_tracking_uri.assert_called_once()
    assert cfg.tracking_uri


def test_log_run_returns_version(monkeypatch):
    fake = _fake_mlflow()
    flavor = types.SimpleNamespace(log_model=mock.Mock(return_value=types.SimpleNamespace()))
    monkeypatch.setattr(registry, "_mlflow", lambda: fake)
    monkeypatch.setattr(registry, "_flavor", lambda name: flavor)

    version = registry.log_run(
        model=object(),
        registered_model_name="glpi_user_classifier",
        params={"a": 1},
        metrics={"f1_macro": 0.8},
        input_hash="abc",
        feature_schema=["x", "y"],
        config=MLConfig.from_env(),
    )
    assert version == "3"
    flavor.log_model.assert_called_once()
    fake.log_metrics.assert_called_once()


def test_get_production_metrics(monkeypatch):
    fake = _fake_mlflow()
    monkeypatch.setattr(registry, "_mlflow", lambda: fake)
    metrics = registry.get_production_metrics("glpi_user_classifier", MLConfig.from_env())
    assert metrics == {"f1_macro": 0.8}


def test_load_production_model_none_on_failure(monkeypatch):
    fake = _fake_mlflow()
    flavor = types.SimpleNamespace(load_model=mock.Mock(side_effect=RuntimeError("no prod")))
    monkeypatch.setattr(registry, "_mlflow", lambda: fake)
    monkeypatch.setattr(registry, "_flavor", lambda name: flavor)
    assert registry.load_production_model("glpi_user_classifier", config=MLConfig.from_env()) is None
