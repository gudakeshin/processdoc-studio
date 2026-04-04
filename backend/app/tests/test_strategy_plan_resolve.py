from app.services.strategy_plan import resolve_selected_strategy


def test_resolve_selected_strategy_returns_matching_option() -> None:
    dossier = {
        "options": [
            {"id": "fast", "title": "Fast path"},
            {"id": "deep", "title": "Deep analysis"},
        ]
    }
    out = resolve_selected_strategy(dossier, {"execution_strategy": ["deep"]})
    assert out is not None
    assert out["option_id"] == "deep"
    assert out["option"]["title"] == "Deep analysis"


def test_resolve_selected_strategy_unknown_id_returns_stub() -> None:
    dossier = {"options": [{"id": "a", "title": "A"}]}
    out = resolve_selected_strategy(dossier, {"execution_strategy": ["missing"]})
    assert out == {"option_id": "missing"}


def test_resolve_selected_strategy_empty_answers_returns_none() -> None:
    dossier = {"options": [{"id": "a", "title": "A"}]}
    assert resolve_selected_strategy(dossier, {}) is None
    assert resolve_selected_strategy(dossier, {"execution_strategy": []}) is None
