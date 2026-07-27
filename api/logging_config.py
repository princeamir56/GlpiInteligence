"""Structured JSON logging with request-id correlation.

Every request gets a request_id (from the incoming X-Request-ID header or a fresh
uuid4), stored in a ContextVar so any log line emitted during the request carries
it, plus the route, user, and duration when available.
"""
from __future__ import annotations

import json
import logging
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
user_var: ContextVar[str] = ContextVar("user", default="-")
route_var: ContextVar[str] = ContextVar("route", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
            "user": user_var.get(),
            "route": route_var.get(),
        }
        if hasattr(record, "duration_ms"):
            payload["duration_ms"] = record.duration_ms  # type: ignore[attr-defined]
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
