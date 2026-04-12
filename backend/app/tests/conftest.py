"""Use in-memory SQLite for tests (StaticPool in session.py shares one DB across threads)."""

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
# Prevent optional localhost Redis from connecting during tests (draw.io collab fan-out / timing).
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"


@pytest.fixture(autouse=True)
def _auth_allow_self_signup_for_integration_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty in-memory DB has no users; login must be able to create the first user per test."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "auth_allow_self_signup", True)


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

    import app.api.projects as projects_module

    monkeypatch.setattr(projects_module, "_recommend_output_types", fake_recommend)
