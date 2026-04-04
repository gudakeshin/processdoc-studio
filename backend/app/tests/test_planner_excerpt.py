"""BM25-aligned planner excerpt from parsed chunks."""

import pytest

from app.services.retrieval import TieredContextEngine


def test_planner_excerpt_includes_query_relevant_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    eng = TieredContextEngine()
    monkeypatch.setattr(
        eng,
        "_load_all_parsed_chunks",
        lambda _pid: [
            "generic boilerplate about meetings",
            "The KEYWORD_PHRASE appears in this procurement step description.",
        ],
    )
    text = eng.planner_excerpt("any_project", "Find KEYWORD_PHRASE for planning", char_cap=4000)
    assert "Planner retrieval excerpt" in text
    assert "KEYWORD_PHRASE" in text
