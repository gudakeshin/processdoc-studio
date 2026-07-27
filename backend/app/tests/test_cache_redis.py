"""Exercises CacheService against fakeredis instead of its in-memory fallback."""

import time

import pytest

from app.services.cache import CacheService


@pytest.mark.redis
def test_cache_set_get_uses_redis(fake_redis) -> None:
    svc = CacheService()
    assert svc._redis is not None

    svc.set("k1", {"a": 1}, ttl_seconds=60)
    assert svc.get("k1") == {"a": 1}
    # Confirm it actually went to fakeredis, not the in-memory dict.
    assert svc._mem == {}


@pytest.mark.redis
def test_cache_get_missing_key_returns_none(fake_redis) -> None:
    svc = CacheService()
    assert svc.get("missing") is None


@pytest.mark.redis
def test_cache_ttl_expiry(fake_redis) -> None:
    svc = CacheService()
    svc.set("expiring", {"v": 1}, ttl_seconds=1)
    assert svc.get("expiring") == {"v": 1}
    fake_redis.pexpire("expiring", 1)
    time.sleep(0.05)
    assert svc.get("expiring") is None
