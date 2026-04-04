import time
from unittest.mock import MagicMock, patch

from app.services.cache import CacheService


def test_memory_cache_expires_entries(monkeypatch) -> None:
    calls = {"n": 0.0}

    def fake_mono() -> float:
        return calls["n"]

    monkeypatch.setattr(time, "monotonic", fake_mono)

    with patch("app.services.cache.redis.Redis") as R:
        R.from_url.side_effect = RuntimeError("no redis")
        c = CacheService()
        assert c._redis is None

    c.set("k1", {"a": 1}, ttl_seconds=10)
    assert c.get("k1") == {"a": 1}

    calls["n"] = 11.0
    assert c.get("k1") is None
