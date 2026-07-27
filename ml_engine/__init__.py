"""Layer 3 — ML Engine for the GLPI intelligence pipeline.

Reads clean data written by layer 2 into PostgreSQL, trains/applies models
(user classification, volume & SLA forecasting, NLP clustering), and writes
predictions & recommendations back into new `ml_*` tables for layer 4.

Design rules (see project spec):
  * `features.py` and every `models/*.py` have ZERO Airflow imports.
  * Heavy deps (prophet, sentence-transformers, spacy, mlflow) are imported
    lazily inside functions so the light modules import fast and stay testable.
  * Every model module exposes the same interface:
        train(df) -> model
        predict(model, df) -> DataFrame
        evaluate(model, df) -> dict[str, float]
"""
from __future__ import annotations

__all__ = ["__version__"]
__version__ = "0.1.0"
