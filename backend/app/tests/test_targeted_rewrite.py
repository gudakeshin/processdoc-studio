"""Phase 1 — targeted slide/section rewrite helpers (pure + mocked LLM)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.agents.agent_types import AgentContext
from app.agents.subagents import (
    _critique_slides,
    _merge_pptx_slides_repair,
    _normalize_pptx_slide_identities,
    _pptx_visual_feedback_indices,
    _section_hint_indices,
    _targeted_section_rewrite,
    _targeted_slide_rewrite,
)
from app.services.design_review import split_h2_sections


def _ctx(**overrides) -> AgentContext:
    base = dict(
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
        skill_card={},
        plan_payload={},
        prior_artifacts_excerpt="",
        emit_event=None,
    )
    base.update(overrides)
    return AgentContext(**base)


def test_pptx_visual_feedback_indices_groups_by_slide() -> None:
    hints = [
        {"slide_index": 2, "instruction": "Fix title"},
        {"slide_index": "3", "instruction": "Add evidence"},
        {"slide_index": 2, "instruction": "Tighten bullets"},
    ]
    assert _pptx_visual_feedback_indices(hints) == {2, 3}


def test_merge_pptx_slides_repair_idempotent_when_no_fix_set() -> None:
    prior = [{"title": "A", "slide_type": "title"}, {"title": "B", "slide_type": "bullets"}]
    repaired = [{"title": "A2", "slide_type": "title"}, {"title": "B2", "slide_type": "bullets"}]
    assert _merge_pptx_slides_repair(prior, repaired, set()) == repaired


def test_normalize_pptx_slide_identities_stable_on_second_pass() -> None:
    slides = [
        {"title": "One", "slide_type": "bullets", "bullets": ["a", "b"]},
        {"title": "Two", "slide_type": "stat_cards", "stat_cards": [{"stat": "1", "label": "X"}]},
    ]
    once = _normalize_pptx_slide_identities(slides)
    twice = _normalize_pptx_slide_identities(once)
    assert once == twice
    assert once[0]["slide_id"] == "slide_01"
    assert once[0]["bullet_ids"] == ["slide_01_bullets_01", "slide_01_bullets_02"]
    assert once[1]["stat_cards"][0]["card_id"] == "slide_02_stat_cards_01"


def test_split_h2_sections_round_trip() -> None:
    md = (
        "# Title\n\nPreamble stays.\n\n"
        "## First\n\nBody one.\n\n"
        "## Second\n\nBody two.\n"
    )
    sections = split_h2_sections(md)
    assert len(sections) == 2
    assert sections[0]["heading"] == "First"
    preamble = md[: len(md) - sum(len(s["body"]) for s in sections)]
    reassembled = preamble + "".join(s["body"] for s in sections)
    assert reassembled == md


def test_section_hint_indices_respects_bounds() -> None:
    hints = [{"section_index": 1}, {"section_index": 99}, {"section_index": "2"}]
    assert _section_hint_indices(hints, 3) == [1, 2]


def test_targeted_slide_rewrite_preserves_unflagged_slides(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "deliverable_critique_loop_enabled", True)
    prior = [
        {"title": "Keep", "slide_type": "title", "slide_id": "slide_01"},
        {"title": "Overview", "slide_type": "bullets", "slide_id": "slide_02", "bullets": ["x"]},
        {"title": "Also keep", "slide_type": "bullets", "slide_id": "slide_03", "bullets": ["y"]},
    ]
    hints = [{"slide_index": 2, "instruction": "Rewrite as assertion title", "source": "action_title"}]

    with patch(
        "app.agents.pptx_critique_repair.claude_generate_json",
        return_value={
            "slides": [
                {
                    "title": "Manual work consumes 40% of capacity",
                    "slide_type": "bullets",
                    "bullets": ["x"],
                    "slide_id": "slide_02",
                }
            ]
        },
    ):
        out = _targeted_slide_rewrite(_ctx(), prior, hints)

    assert out[0]["title"] == prior[0]["title"]
    assert out[0]["slide_type"] == prior[0]["slide_type"]
    assert out[2]["title"] == prior[2]["title"]
    assert out[2]["bullets"] == prior[2]["bullets"]
    assert "40%" in out[1]["title"]


def test_targeted_slide_rewrite_returns_input_on_llm_failure() -> None:
    prior = [{"title": "A", "slide_type": "title"}]
    hints = [{"slide_index": 1, "instruction": "fix", "source": "action_title"}]
    with patch("app.agents.pptx_critique_repair.claude_generate_json", side_effect=RuntimeError("down")):
        assert _targeted_slide_rewrite(_ctx(), prior, hints) == prior


def test_targeted_section_rewrite_reassembles_only_flagged() -> None:
    md = "# Doc\n\n## Alpha\n\nOne.\n\n## Beta\n\nTwo.\n\n## Gamma\n\nThree.\n"
    hints = [{"section_index": 2, "instruction": "Tighten argument", "source": "placeholder"}]
    with patch(
        "app.agents.subagents.claude_generate_json",
        return_value={"sections": [{"index": 2, "markdown": "## Beta\n\nRevised two.\n"}]},
    ):
        out = _targeted_section_rewrite(_ctx(output_type="docx"), md, hints)
    assert "## Alpha" in out and "One." in out
    assert "Revised two." in out
    assert "## Gamma" in out and "Three." in out


def test_critique_slides_merges_design_review_hints() -> None:
    slides = [
        {"slide_type": "title", "title": "P2P"},
        {"slide_type": "bullets", "title": "Overview"},
    ]
    hints, review = _critique_slides(_ctx(), slides, None, None)
    assert review["status"] in ("warn", "fail")
    assert any(h.get("source") == "action_title" for h in hints)
    assert all(h.get("slide_index", 0) > 0 for h in hints if h.get("source") == "action_title")
