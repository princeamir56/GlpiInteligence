"""Layer 4 — FastAPI API backend for the Sartex GLPI intelligence pipeline.

Reads the warehouse (layer 2) and ML result tables (layer 3) from PostgreSQL and
exposes them as a REST API + WebSocket stream for the Angular dashboard (layer 5).
This package never writes to the layer-2/3 tables; it only adds its own
`api_users` and `recommendation_acks` tables.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
