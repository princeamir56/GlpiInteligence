"""Async Redis cache wrapper.

Mirrors the namespacing of `etl/cache.py` (`glpi:<tier>:<key>`) but uses
`redis.asyncio` so it never blocks the event loop. Two TTL tiers are configured
from settings: `overview` (60s) and `heavy` (5 min). Cache failures are swallowed
and logged — a Redis outage degrades to always-miss, never a 500.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal, Optional

import redis.asyncio as aioredis

from .config import get_settings

logger = logging.getLogger("api.cache")

Tier = Literal["overview", "heavy"]

_client: Optional[aioredis.Redis] = None


def get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            get_settings().redis_url, decode_responses=True
        )
    return _client


def _ttl(tier: Tier) -> int:
    s = get_settings()
    return s.cache_ttl_overview if tier == "overview" else s.cache_ttl_heavy


def _ns(tier: Tier, key: str) -> str:
    return f"glpi:api:{tier}:{key}"


async def cache_get(key: str, tier: Tier) -> Any | None:
    try:
        raw = await get_client().get(_ns(tier, key))
    except Exception as exc:  # pragma: no cover - redis down
        logger.warning("cache get failed: %s", exc)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


async def cache_set(key: str, value: Any, tier: Tier) -> None:
    try:
        payload = json.dumps(value, default=str)
        await get_client().setex(_ns(tier, key), _ttl(tier), payload)
    except Exception as exc:  # pragma: no cover - redis down
        logger.warning("cache set failed: %s", exc)


async def cache_bust_prefix(*tiers: Tier) -> None:
    """Delete every key in the given tier namespaces (used by write endpoints)."""
    client = get_client()
    for tier in tiers:
        try:
            pattern = f"glpi:api:{tier}:*"
            keys = [k async for k in client.scan_iter(match=pattern)]
            if keys:
                await client.delete(*keys)
        except Exception as exc:  # pragma: no cover
            logger.warning("cache bust failed: %s", exc)


async def close_cache() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None
