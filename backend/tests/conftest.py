"""Pytest defaults for tests under backend/tests/."""

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-32-chars-long-ok!")
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"


@pytest.fixture(autouse=True)
def _auth_allow_self_signup_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "auth_allow_self_signup", True)


@pytest.fixture(autouse=True)
def _disable_slowapi_rate_limits_for_tests() -> None:
    from app.core.rate_limit import limiter

    prev = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = prev
