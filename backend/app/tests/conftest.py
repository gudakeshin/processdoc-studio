"""Use in-memory SQLite for tests (StaticPool in session.py shares one DB across threads)."""

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-32-chars-long-ok!")
# Prevent optional localhost Redis from connecting during tests (draw.io collab fan-out / timing).
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch):
    """Opt-in fixture (mark a test with @pytest.mark.redis) that makes every
    `redis.Redis.from_url(...)` call in the codebase return a shared fakeredis
    instance instead of hitting the blocked REDIS_URL set above, so Redis-backed
    branches (cache, run queue, excel locks) get real coverage instead of only
    exercising their in-memory/in-process fallback paths.
    """
    fakeredis = pytest.importorskip("fakeredis")
    import redis

    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda cls, *a, **k: client))
    yield client
    client.flushall()


@pytest.fixture(autouse=True)
def _disable_slowapi_rate_limits_for_tests() -> None:
    """Many tests log in; SlowAPI's default /login cap causes flaky 429s in full suite."""
    from app.core.rate_limit import limiter

    prev = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = prev


@pytest.fixture(autouse=True)
def _auth_allow_self_signup_for_integration_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty in-memory DB has no users; login must be able to create the first user per test."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "auth_allow_self_signup", True)
    # Integration tests predate the collaborative storyline flow and only need a confirmed plan
    # to exercise downstream behaviour; the legacy discovery→plan path reaches ready_for_confirmation.
    monkeypatch.setattr(settings, "collaborative_building_enabled", False)


@pytest.fixture(autouse=True)
def _disable_narrative_llm_critique_for_tests(request, monkeypatch: pytest.MonkeyPatch) -> None:
    """Narrative coherence tests assert the deterministic score; the LLM critique
    blend (enabled by default) would add live Anthropic calls and non-deterministic
    issues. Opt out with @pytest.mark.live_llm.
    """
    if request.node.get_closest_marker("live_llm"):
        return
    from app.core.config import settings

    monkeypatch.setattr(settings, "narrative_llm_critique_enabled", False)


@pytest.fixture(autouse=True)
def _stub_output_type_recommendations_for_integration_tests(request, monkeypatch):
    """Avoid live Anthropic calls and flaky empty recommendations during plan drafting.

    Opt out with @pytest.mark.live_llm on a test module or function.
    """
    if request.node.get_closest_marker("live_llm"):
        return

    def fake_recommend(instruction: str, available_output_types: list) -> tuple:
        _ = instruction
        _ = available_output_types
        return (
            ["docx"],
            [],
            {},
            "stubbed recommendation for tests",
            None,
        )

    import app.api.projects.conversation as projects_module

    monkeypatch.setattr(projects_module, "_recommend_output_types", fake_recommend)
