"""Create the layer-3 `ml_*` + `recommendations` tables.

Runs `ml_engine/schema.sql` against the warehouse. Idempotent and it touches
NONE of the layer-2 tables. Use it to bootstrap a fresh DB before the first
inference run:

    python -m ml_engine.migrate
"""
from __future__ import annotations

import logging

from .config import MLConfig
from .data_access import get_engine
from .load import ensure_schema


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = MLConfig.from_env()
    engine = get_engine(cfg)
    ensure_schema(engine)
    logging.getLogger(__name__).info("ml_engine schema ensured on %s", cfg.postgres_url)
    print("ml_engine tables created/verified.")


if __name__ == "__main__":
    main()
