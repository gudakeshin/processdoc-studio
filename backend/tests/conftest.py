"""Pytest defaults for tests under backend/tests/."""

import os

import pytest

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-min-16chars")


@pytest.fixture(autouse=True)
def _disable_slowapi_rate_limits_for_tests() -> None:
    from app.core.rate_limit import limiter

    prev = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = prev
