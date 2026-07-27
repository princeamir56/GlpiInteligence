"""Tests for the Redis cache wrapper using fakeredis."""
from __future__ import annotations

import pytest

fakeredis = pytest.importorskip("fakeredis")

from etl.cache import GLPICache
from etl.config import ETLConfig


@pytest.fixture()
def cache() -> GLPICache:
    fake = fakeredis.FakeRedis(decode_responses=True)
    cfg = ETLConfig(postgres_url="sqlite://", redis_url="redis://fake/0",
                    cache_ttl_live=5, cache_ttl_aggregate=60)
    return GLPICache(client=fake, config=cfg)


def test_miss_then_hit(cache: GLPICache):
    assert cache.get("open_tickets") is None
    cache.set("open_tickets", {"count": 42})
    assert cache.get("open_tickets") == {"count": 42}
    assert cache.stats() == {"hits": 1, "misses": 1}


def test_tier_namespacing(cache: GLPICache):
    cache.set("totals", [1, 2], tier="aggregate")
    assert cache.get("totals", tier="live") is None
    assert cache.get("totals", tier="aggregate") == [1, 2]


def test_invalidate(cache: GLPICache):
    cache.set("k", "v")
    cache.invalidate("k")
    assert cache.get("k") is None
