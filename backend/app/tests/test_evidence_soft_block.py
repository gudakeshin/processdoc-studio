"""Phase 1 — evidence soft-block: bounded rewrite, render always proceeds."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents.agent_types import AgentContext
from app.agents.subagents import (
    _EVIDENCE_SOFT_BLOCK_DIRECTIVE,
    _critique_and_repair_docx,
    _critique_and_repair_pptx,
    _evidence_remediation_directive,
)
from app.core.evidence_validator import validate_pptx_slides_evidence, validate_text_evidence


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


def test_evidence_soft_block_directive_text() -> None:
    assert "directional estimate" in _EVIDENCE_SOFT_BLOCK_DIRECTIVE.lower()
    assert "never invent" in _EVIDENCE_SOFT_BLOCK_DIRECTIVE.lower()


def test_evidence_remediation_directive_includes_validator_suggestions() -> None:
    claims = [{"claim": "$500M", "context": "savings"}]
    directive = _evidence_remediation_directive(claims, {"process_name": "P2P"})
    assert _EVIDENCE_SOFT_BLOCK_DIRECTIVE in directive
    assert "remediation guidance" in directive.lower()
    assert "processmodel" in directive.lower()


def test_validate_text_evidence_finds_unsupported_claims() -> None:
    result = validate_text_evidence("Savings of $500M are achievable within 90 days.", None)
    validation = result["validation"]
    assert validation["status"] in ("warn", "fail")
    assert validation["unsupported_claims"]
    assert validation["unsupported_claims"][0].get("claim") == "$500M"


def test_pptx_soft_block_builds_rewrite_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "deliverable_critique_loop_enabled", False)
    monkeypatch.setattr(settings, "evidence_soft_block_enabled", True)

    slides = [
        {"slide_type": "title", "title": "Deck"},
        {"slide_type": "bullets", "title": "Impact", "bullets": ["$900M annual savings"]},
    ]
    captured: dict = {}

    def _capture_rewrite(_ctx, slide_dicts, hints, *, directive="", max_slides=6):
        captured["hints"] = hints
        captured["directive"] = directive
        return slide_dicts

    with patch("app.agents.pptx_critique_repair.targeted_slide_rewrite", side_effect=_capture_rewrite):
        out = _critique_and_repair_pptx(_ctx(), slides, None)

    assert out == slides
    assert "directional estimate" in captured["directive"].lower()
    assert "never invent" in captured["directive"].lower()
    assert captured["hints"][0]["source"] == "evidence"
    assert "$900M" in captured["hints"][0]["instruction"]


def test_pptx_soft_block_uses_source_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "deliverable_critique_loop_enabled", False)
    monkeypatch.setattr(settings, "evidence_soft_block_enabled", True)

    registry = [
        {
            "source_id": "S1",
            "text": "Revenue | 1200 | 1450",
            "filename": "model.xlsx",
            "sheet": "Revenue",
        }
    ]
    slides = [
        {"slide_type": "title", "title": "Deck"},
        {
            "slide_type": "stat_cards",
            "title": "Revenue",
            "stat_cards": [{"stat": "1200", "label": "Annual revenue"}],
        },
    ]
    ctx = _ctx(compaction_snapshot={"source_registry": registry})

    with patch("app.agents.pptx_critique_repair.targeted_slide_rewrite", side_effect=lambda *_a, **_k: slides):
        out = _critique_and_repair_pptx(ctx, slides, None)

    assert out[1]["footer_note"].startswith("Source: model.xlsx")


def test_pptx_soft_block_render_proceeds_when_rewrite_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "deliverable_critique_loop_enabled", False)
    monkeypatch.setattr(settings, "evidence_soft_block_enabled", True)

    slides = [
        {"slide_type": "title", "title": "Deck"},
        {"slide_type": "stat_cards", "title": "ROI", "stat_cards": [
            {"stat": "$2B", "label": "Savings", "description": "Unverified"},
        ]},
    ]
    before = validate_pptx_slides_evidence(slides, None)["unsupported_claims_count"]
    assert before >= 1

    with patch("app.agents.pptx_critique_repair.targeted_slide_rewrite", side_effect=RuntimeError("llm down")):
        out = _critique_and_repair_pptx(_ctx(), slides, None)

    assert out == slides
    assert len(out) == 2


def test_docx_soft_block_preserves_sections_on_rewrite_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "deliverable_critique_loop_enabled", False)
    monkeypatch.setattr(settings, "evidence_soft_block_enabled", True)

    md = "# Brief\n\n## Value\n\nWe project $750M in savings.\n"
    with patch("app.agents.docx_critique_repair.targeted_section_rewrite", side_effect=RuntimeError("llm down")):
        out = _critique_and_repair_docx(_ctx(output_type="docx"), md, None, "narrative")
    assert out == md


def test_docx_soft_block_emits_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "deliverable_critique_loop_enabled", False)
    monkeypatch.setattr(settings, "evidence_soft_block_enabled", True)

    md = "# Brief\n\n## Value\n\nWe project $750M in savings.\n"
    events: list[tuple[str, dict]] = []

    def emit(name: str, payload: dict) -> None:
        events.append((name, payload))

    revised = md.replace("$750M", "material savings (directional estimate)")
    with patch("app.agents.docx_critique_repair.targeted_section_rewrite", return_value=revised):
        out = _critique_and_repair_docx(
            _ctx(output_type="docx", emit_event=emit), md, None, "narrative"
        )

    assert out == revised
    ev_events = [p for n, p in events if n == "evidence_soft_block"]
    assert ev_events
    assert ev_events[0]["soft_block_applied"] is True
    assert ev_events[0]["claims_before"] >= 1
    assert ev_events[0]["claims_after"] <= ev_events[0]["claims_before"]
