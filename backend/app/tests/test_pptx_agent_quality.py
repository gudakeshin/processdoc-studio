"""Tests for PPTX prompt enrichment, coordinator hints, quality gate, and fallback deck."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.agents.agent_types import AgentContext, build_agent_context
from app.agents.coordinator import Coordinator
from app.agents.subagents import (
    _apply_quality_gate,
    _merge_pptx_slides_repair,
    _pptx_deterministic_slides,
    _shared_user_context_appendix,
)
from app.services.skill_document import load_builtin_skills


def test_build_agent_context_prior_artifacts_excerpt() -> None:
    state = {
        "raw_text": "x",
        "narrative_md": "# Exec brief\n\nStory body " + ("word " * 500),
        "docx_markdown": "## Draft\n\n" + ("line " * 400),
        "assembled_context": "tier0",
    }
    ctx = build_agent_context(state, "pptx")  # type: ignore[arg-type]
    ex = ctx.prior_artifacts_excerpt
    assert "## Narrative or executive briefing" in ex
    assert "## Related Word document draft" in ex
    assert len(ex) <= 7000


def test_shared_user_context_appendix_includes_user_and_context() -> None:
    state = {
        "raw_text": "",
        "user_instruction": "Focus on compliance gates.",
        "assembled_context": "Project: Acme onboarding " * 50,
        "narrative_md": "## Prior narrative\nKey risks discussed.",
        "process_model": {"process_name": "P", "steps": []},
    }
    ctx = build_agent_context(state, "pptx")  # type: ignore[arg-type]
    appendix = _shared_user_context_appendix(ctx)
    assert "User instruction" in appendix
    assert "compliance gates" in appendix
    assert "Assembled project context" in appendix
    assert "Acme onboarding" in appendix
    assert "Prior narrative" in appendix
    assert "User instruction" in appendix
    assert "Assembled project context" in appendix
    assert "<untrusted" in appendix and "</untrusted>" in appendix
    assert "---" in appendix


def test_pptx_deterministic_slides_mandatory_sequence() -> None:
    pm = {
        "process_name": "Invoice Reconciliation",
        "roles": ["AP Lead", "Controller"],
        "steps": [
            {"name": "Intake", "role": "AP Lead", "inputs": "Email", "outputs": "Ticket"},
            {"name": "Match", "role": "AP Lead", "inputs": "Ticket", "outputs": "Match set"},
        ],
    }
    slides = _pptx_deterministic_slides(pm)
    assert len(slides) == 8
    types = [s.get("slide_type") for s in slides]
    assert types == [
        "title",
        "stat_cards",
        "column_cards",
        "stack_layers",
        "bullets",
        "table",
        "stat_cards",
        "bullets",
    ]
    assert slides[0].get("title") == "Invoice Reconciliation"
    # Stat cards must include descriptions (renderer uses them)
    for key in (1, 6):
        for card in slides[key]["stat_cards"]:
            assert card.get("description"), f"stat_cards slide {key} missing description"
    assert slides[5]["table"]["headers"] == ["Step", "Owner", "Inputs → Outputs"]
    assert len(slides[5]["table"]["rows"]) >= 1


def test_coordinator_deck_sets_pptx_narrative_v2_hint() -> None:
    c = Coordinator()
    st = c.run(
        {
            "raw_text": "1. Step one\n2. Step two\nRole: Ops",
            "requested_outputs": ["deck"],
            "dpdp_flags": {"enabled": True},
        }
    )
    assert isinstance(st.get("pptx_slides"), list) and len(st["pptx_slides"]) >= 1
    hints = st.get("content_skill_hints") or {}
    assert hints.get("pptx") == "narrative_v2", "deck must set narrative_v2 content skill hint for pptx"


def test_coordinator_brd_deck_sets_brd_v1_hint() -> None:
    c = Coordinator()
    st = c.run(
        {
            "raw_text": "1. A\n2. B\nRole: R",
            "requested_outputs": ["brd_deck"],
            "dpdp_flags": {"enabled": True},
        }
    )
    hints = st.get("content_skill_hints") or {}
    assert hints.get("pptx") == "brd_v1"


@pytest.mark.parametrize(
    "deliverable,expected_skill",
    [
        ("proposal_deck", "proposal_finance_transformation_v1"),
        ("executive_deck", "narrative_v2"),
    ],
)
def test_coordinator_deck_variants_content_hints(deliverable: str, expected_skill: str) -> None:
    c = Coordinator()
    st = c.run(
        {
            "raw_text": "1. X\nRole: Y",
            "requested_outputs": [deliverable],
            "dpdp_flags": {"enabled": True},
        }
    )
    hints = st.get("content_skill_hints") or {}
    assert hints.get("pptx") == expected_skill


def test_merge_pptx_slides_repair_keeps_unflagged_slides() -> None:
    prior = [
        {"title": "A", "slide_type": "title"},
        {"title": "B", "slide_type": "bullets", "bullets": ["x"]},
        {"title": "C", "slide_type": "bullets", "bullets": ["y"]},
    ]
    repaired = [
        {"title": "A2", "slide_type": "title"},
        {"title": "B2", "slide_type": "bullets", "bullets": ["fixed"]},
        {"title": "C2", "slide_type": "bullets", "bullets": ["z"]},
    ]
    out = _merge_pptx_slides_repair(prior, repaired, {2})
    assert out[0] == prior[0]
    assert out[1]["title"] == "B2"
    assert out[1]["bullets"] == ["fixed"]
    assert out[2] == prior[2]


def test_pptx_quality_gate_invokes_json_remediation_when_score_low() -> None:
    skills = load_builtin_skills()
    pptx_card = next((s for s in skills if s.get("id") == "frontend_design_pptx_v1"), None)
    assert pptx_card is not None

    thin = json.dumps(
        {
            "slides": [
                {"title": "Only three", "slide_type": "title", "subtitle": "S"},
                {"title": "A", "slide_type": "bullets", "bullets": ["a"]},
                {"title": "B", "slide_type": "bullets", "bullets": ["b"]},
            ]
        }
    )
    fixed_slides = _pptx_deterministic_slides(
        {"process_name": "Gated", "steps": [{"name": "S1", "role": "R"}], "roles": ["R"]}
    )
    ctx = AgentContext(
        output_type="pptx",
        project_id=None,
        run_id=None,
        user_id=None,
        raw_text="",
        user_instruction="",
        user_intent_original="",
        process_model={},
        assembled_context="",
        output_type_representations={},
        skill_instructions_by_output={},
        skill_card={"primary_skill_by_output_type": {"pptx": pptx_card}},
        plan_payload={},
        prior_artifacts_excerpt="",
        emit_event=None,
    )

    with (
        patch("app.agents.subagents.is_claude_enabled", return_value=True),
        patch(
            "app.agents.subagents.claude_generate_json",
            return_value={"slides": fixed_slides},
        ) as mock_json,
    ):
        out = _apply_quality_gate(ctx, "pptx", thin, system="SYS", temperature=0.1)

    mock_json.assert_called_once()
    parsed = json.loads(out)
    assert len(parsed["slides"]) == 8
    assert parsed["slides"][0]["slide_type"] == "title"
