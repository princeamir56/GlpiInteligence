"""Redis cache wrapper with two TTL tiers: live (5 min) and aggregate (1 h)."""
from __future__ import annotations

import json
import logging
from typing import Any, Literal

import redis

from .config import ETLConfig

logger = logging.getLogger(__name__)

TierName = Literal["live", "aggregate"]


class GLPICache:
    """Thin Redis JSON cache. Tier selects TTL; key namespace is `glpi:<tier>:<key>`."""

    def __init__(self, client: "redis.Redis | None" = None, config: ETLConfig | None = None) -> None:
        self.config = config or ETLConfig.from_env()
        self.client = client or redis.Redis.from_url(self.config.redis_url, decode_responses=True)
        self.hits = 0
        self.misses = 0

    def _ttl(self, tier: TierName) -> int:
        return self.config.cache_ttl_live if tier == "live" else self.config.cache_ttl_aggregate

    def _ns(self, tier: TierName, key: str) -> str:
        return f"glpi:{tier}:{key}"

    def get(self, key: str, tier: TierName = "live") -> Any | None:
        full = self._ns(tier, key)
        raw = self.client.get(full)
        if raw is None:
            self.misses += 1
            logger.debug("cache MISS %s", full)
            return None
        self.hits += 1
        logger.debug("cache HIT %s", full)
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return raw

    def set(self, key: str, value: Any, tier: TierName = "live") -> None:
        full = self._ns(tier, key)
        payload = json.dumps(value, default=str)
        self.client.setex(full, self._ttl(tier), payload)
        logger.debug("cache SET %s ttl=%ss", full, self._ttl(tier))

    def invalidate(self, key: str, tier: TierName = "live") -> None:
        self.client.delete(self._ns(tier, key))

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}
