"""FastAPI application factory: middleware, error handling, routers, lifespan.

Run in dev:   uvicorn api.main:app --reload --port 8000
Run in prod:  gunicorn api.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.exceptions import HTTPException as StarletteHTTPException

from .alerts.broadcaster import broadcaster
from .cache import close_cache
from .config import get_settings
from .database import dispose_engine
from .logging_config import configure_logging, request_id_var, route_var, user_var
from .routers import (
    auth,
    categories,
    demandeurs,
    health,
    overview,
    predictions,
    recommendations,
    repetitifs,
    services,
    sites,
    techniciens,
    websocket,
)

logger = logging.getLogger("api")


def _key_func(request: Request) -> str:
    """Rate-limit key: authenticated user if present, else client IP."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header
    return get_remote_address(request)


# Rate limiting: the key is the Bearer token for authenticated callers, else the
# client IP — so each user (and each anonymous IP) gets its own bucket. The default
# limit applies to every route; authenticated endpoints raise it via the
# `authed_limit` decorator where a higher ceiling is wanted.
limiter = Limiter(
    key_func=_key_func,
    default_limits=[get_settings().rate_limit_anon],
    headers_enabled=True,
)


def authed_limit():
    """Decorator applying the higher authenticated rate limit to a route."""
    return limiter.limit(get_settings().rate_limit_auth)


def _error(status_code: int, code: str, message: str, details: dict | None = None):
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    broadcaster.start()
    logger.info("api startup complete")
    try:
        yield
    finally:
        await broadcaster.stop()
        await close_cache()
        await dispose_engine()
        logger.info("api shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Sartex GLPI Intelligence API",
        description="Layer 4 — REST + WebSocket backend for the IT dashboard.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    # ---- request-id + structured access logging + rate-limit tagging ----
    @app.middleware("http")
    async def context_middleware(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request_id_var.set(rid)
        route_var.set(f"{request.method} {request.url.path}")
        user_var.set("-")
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration = (time.perf_counter() - start) * 1000
            logger.exception("unhandled error", extra={"duration_ms": round(duration, 2)})
            resp = _error(500, "internal_error", "Internal server error")
            resp.headers["X-Request-ID"] = rid
            return resp
        duration = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = rid
        logger.info(
            "request complete", extra={"duration_ms": round(duration, 2)}
        )
        return response

    # CORS is added LAST so it ends up the OUTERMOST middleware (Starlette wraps
    # in reverse registration order). Registered before `context_middleware`, the
    # 500 that middleware synthesizes bypasses CORS and reaches the browser with
    # no Access-Control-Allow-Origin header — the request is then blocked and the
    # frontend can only report an opaque "0 Unknown Error" instead of the status.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- consistent JSON error envelope ----
    @app.exception_handler(StarletteHTTPException)
    async def http_exc_handler(request: Request, exc: StarletteHTTPException):
        return _error(exc.status_code, f"http_{exc.status_code}", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        return _error(
            422, "validation_error", "Request validation failed",
            {"errors": exc.errors()},
        )

    @app.exception_handler(RateLimitExceeded)
    async def ratelimit_handler(request: Request, exc: RateLimitExceeded):
        return _error(429, "rate_limited", "Too many requests")

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        logger.exception("unhandled exception")
        return _error(500, "internal_error", "Internal server error")

    # ---- routers ----
    for module in (
        auth, overview, demandeurs, services, sites, repetitifs,
        techniciens, categories, predictions, recommendations,
        websocket, health,
    ):
        app.include_router(module.router)

    # ---- Prometheus metrics at /metrics ----
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    return app


app = create_app()
