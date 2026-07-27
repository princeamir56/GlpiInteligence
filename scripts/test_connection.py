"""Smoke test: open a GLPI session, count tickets, close the session.

Usage:
    python scripts/test_connection.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from glpi_connector import GLPIClient, GLPIConfig
from glpi_connector.extractors import TICKET_FIELD_MAP


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    log = logging.getLogger("test_connection")

    try:
        config = GLPIConfig.from_env()
    except RuntimeError as e:
        log.error("%s", e)
        return 2

    log.info("Connecting to %s", config.base_url)
    try:
        with GLPIClient(config) as client:
            count = 0
            # Just consume the search iterator to get the total count quickly.
            # We request a single field to minimize payload size.
            for _ in client.search("Ticket", forcedisplay=[2], page_size=config.page_size):
                count += 1
            log.info("OK — %d tickets available", count)
            log.info("Field map in use (%d fields): %s",
                     len(TICKET_FIELD_MAP), list(TICKET_FIELD_MAP.values()))
    except Exception as exc:
        log.exception("Connection test failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
