"""Phase A — storyline contract + action-title heuristics + model tiering.

Pure-logic tests: no Redis, no Anthropic. The LLM-authored contract is fail-open,
so we exercise the deterministic surface (validation, render, persist/load) and the
fallback path with the contract disabled.
"""
from __future__ import annotations

import json

import pytest

from app.core.action_title import classify_title, score_titles
from app.core import model_tiers
from app.services import storyline_builder as sb


# ── action titles ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "title",
    [
        "Manual reconciliation consumes 40% of finance capacity",
        "Four failure modes derail programs like this",
        "$400M left on the table annually",
        "A five-layer operating model eliminates the bottleneck",
    ],
)
def test_assertions_pass(title: str) -> None:
    assert classify_title(title).is_assertion, title


@pytest.mark.parametrize(
    "title",
    ["Current State", "Overview", "Process Overview", "Next Steps", "Our Team", "Background"],
)
def test_topic_labels_flagged(title: str) -> None:
    assert not classify_title(title).is_assertion, title


def test_score_titles_fails_label_heavy_deck() -> None:
    titles = ["Overview", "Current State", "Approach", "Next Steps", "$2M saved annually"]
    score, passed = score_titles(titles, max_label_ratio=0.2)
    assert score.labels == 4
    assert not passed


def test_score_titles_passes_assertion_heavy_deck() -> None:
    titles = [
        "Costs climb 18% without intervention",
        "Three levers collapse the bottleneck",
        "Automation frees 12 FTEs",
        "Pilot proves the model in 90 days",
        "Overview",
    ]
    _, passed = score_titles(titles, max_label_ratio=0.2)
    assert passed


# ── model tiering ────────────────────────────────────────────────────────────

def test_model_tiering_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "model_tiering_enabled", True)
    monkeypatch.setattr(settings, "anthropic_planning_model", "claude-opus-4-8")
    monkeypatch.setattr(settings, "anthropic_critique_model", "claude-sonnet-4-6")
    assert model_tiers.planning_model() == "claude-opus-4-8"
    assert model_tiers.critique_model() == "claude-sonnet-4-6"


def test_model_tiering_disabled_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "model_tiering_enabled", False)
    monkeypatch.setattr(settings, "anthropic_claude_model", "claude-haiku-4-5")
    assert model_tiers.planning_model() == "claude-haiku-4-5"
    assert model_tiers.critique_model() == "claude-haiku-4-5"


# ── storyline contract ───────────────────────────────────────────────────────

def _sample_contract() -> dict:
    return {
        "arc": "pyramid",
        "governing_thought": "Automating P2P frees 40% of finance capacity",
        "slides": [
            {
                "slide_number": 1,
                "action_title": "Manual hand-offs add 11 days to every close",
                "role_in_arc": "governing thought",
                "key_message": "The status quo is unsustainable",
                "required_evidence": "11-day cycle time from process model",
                "suggested_visual": "big_number",
            },
            {
                "slide_number": 2,
                "action_title": "Three levers collapse the bottleneck",
                "role_in_arc": "supporting argument",
                "key_message": "Governance, quality gates, automation",
                "required_evidence": "assumption — to validate",
                "suggested_visual": "column_cards",
            },
        ],
    }


def test_validate_contract_ok() -> None:
    ok, issues = sb.validate_storyline_contract(_sample_contract())
    assert ok, issues


def test_validate_contract_rejects_bad_visual_and_missing_title() -> None:
    bad = _sample_contract()
    bad["slides"][0]["suggested_visual"] = "hologram"
    bad["slides"][1]["action_title"] = ""
    ok, issues = sb.validate_storyline_contract(bad)
    assert not ok
    assert any("hologram" in i for i in issues)
    assert any("action_title" in i for i in issues)


def test_render_contract_for_prompt_includes_titles_and_visuals() -> None:
    block = sb.render_contract_for_prompt(_sample_contract())
    assert "APPROVED STORYLINE" in block
    assert "Manual hand-offs add 11 days" in block
    assert "big_number" in block
    assert "column_cards" in block


def test_render_contract_emits_slide_type_directive_and_field_hints() -> None:
    contract = _sample_contract()
    contract["slides"][1]["suggested_visual"] = "two_by_two"
    block = sb.render_contract_for_prompt(contract)
    assert "slide_type" in block  # imperative directive, not just advisory text
    assert "two_by_two → fields: quadrants" in block  # cheat-sheet for the rich type used
    assert "value_chain" not in block  # only rich types present in the spine appear


def test_render_contract_document_mode_omits_visual_vocab() -> None:
    block = sb.render_contract_for_prompt(_sample_contract(), mode="document")
    assert "APPROVED STORYLINE" in block
    assert "H2 section" in block
    assert "topic sentence" in block
    assert "Manual hand-offs add 11 days" in block
    assert "big_number" not in block
    assert "slide_type" not in block


def test_tone_directive_compliance_vs_transformation() -> None:
    compliance = sb.tone_directive("banking audit compliance controls")
    transformation = sb.tone_directive("digital transformation automation savings")
    assert "control" in compliance.lower() or "regulat" in compliance.lower()
    assert "outcome" in transformation.lower() or "prize" in transformation.lower()
    assert sb.tone_directive("") == ""


def test_render_empty_contract_returns_blank() -> None:
    assert sb.render_contract_for_prompt({"arc": "pyramid", "slides": []}) == ""


def test_persist_and_load_roundtrip(tmp_path) -> None:
    contract = _sample_contract()
    path = sb.persist_storyline_contract(tmp_path, contract)
    assert path and (tmp_path / "storyline.json").exists()
    loaded = sb.load_storyline_contract(tmp_path)
    assert loaded == contract


def test_load_missing_returns_none(tmp_path) -> None:
    assert sb.load_storyline_contract(tmp_path) is None


def test_build_contract_failopen_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "storyline_contract_enabled", False)
    contract = sb.build_storyline_contract(
        arc_key="pyramid",
        discovery_slots={},
        process_summary="Process: P2P\nSteps (2):\n  1. Create PR\n  2. Approve",
    )
    assert contract["arc"] == "pyramid"
    assert contract["degraded"] is True
    assert contract["slides"] == []
