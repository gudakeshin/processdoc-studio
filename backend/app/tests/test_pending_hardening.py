"""Tests for pending-item hardening across grounding, ingest, and evaluator gates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.evidence_validator import validate_claims_against_evidence
from app.core.pdf_extract import citation_overlap_score
from app.services.process_extraction import _is_valid_step_name
from app.services.run_worker import _build_evaluator_pipeline, _pptx_evidence_gate_from_run_dir
from app.services.wiki_query import _extract_citations


def test_wiki_citations_do_not_fabricate_top_five() -> None:
    pages = [
        {"page_id": "p1", "title": "Revenue Model", "content": "Annual revenue 1200"},
        {"page_id": "p2", "title": "Unrelated Topic", "content": "cats and dogs"},
    ]
    cited = _extract_citations("We reviewed the revenue model assumptions.", pages)
    assert len(cited) <= 3
    assert all(c.get("page_title") != "Unrelated Topic" or len(cited) == 1 for c in cited)


def test_citation_overlap_score_prefers_relevant_page() -> None:
    pages = [
        {"title": "Revenue Model", "content": "annual revenue assumptions"},
        {"title": "Cats", "content": "unrelated"},
    ]
    assert citation_overlap_score("revenue model assumptions", pages[0]) > citation_overlap_score(
        "revenue model assumptions", pages[1]
    )


def test_process_step_validation_rejects_entity_labels() -> None:
    assert _is_valid_step_name("Indus Apex Bank Ltd") is False
    assert _is_valid_step_name("Validate source document against client records") is True


def test_evidence_ignores_process_model_when_sources_present(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "evidence_ignore_process_model_when_sources_present", True)
    source_chunks = [{"source_id": "S1", "text": "Revenue | 1200", "filename": "m.xlsx", "sheet": "Rev"}]
    pm = {"kpis": [{"value": "9999"}]}
    claims = [{"value": "9999", "type": "Financial value", "context": "", "has_assumption_label": False}]
    result = validate_claims_against_evidence(claims, pm, source_chunks=source_chunks)
    assert result["unsupported_claims"]


def test_guardrails_fail_closed_by_default() -> None:
    pipeline = _build_evaluator_pipeline(
        requested_outputs=["pptx"],
        plan_payload={},
        qa_report={"passed": True},
        visual_qa_report={"status": "pass"},
        guardrail_report={"status": "fail", "failed_gate": "gate_1_source_grounding"},
        evidence_gate={"passed": True, "hard_fail": False},
    )
    guardrails_only = (
        not pipeline.get("guardrails_passed")
        and pipeline.get("qa_passed", True)
        and pipeline.get("visual_qa_passed", True)
        and pipeline.get("final_artifact_qa_passed", True)
        and pipeline.get("evidence_passed", True)
    )
    assert pipeline["status"] == "fail"
    assert guardrails_only is True


def test_pptx_evidence_gate_reads_hard_fail_flag(tmp_path: Path) -> None:
    (tmp_path / "render_status.json").write_text(json.dumps({"pptx": "degraded"}), encoding="utf-8")
    (tmp_path / "pptx_render_quality.json").write_text(
        json.dumps({"status": "fail", "evidence_hard_fail": True, "evidence": {"unsupported_claims_count": 2}}),
        encoding="utf-8",
    )
    gate = _pptx_evidence_gate_from_run_dir(tmp_path)
    assert gate["passed"] is False
    assert gate["hard_fail"] is True
