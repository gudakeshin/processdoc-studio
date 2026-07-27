"""Phase 1 grounding: provenance chunks, source-aware evidence validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.evidence_validator import (
    validate_claims_against_evidence,
    validate_pptx_slides_evidence,
)
from app.core.source_chunks import build_chunks_from_text, format_chunk_citation
from app.services.retrieval import TieredContextEngine


def test_build_chunks_preserves_sheet_provenance() -> None:
    text = "[Sheet: Revenue]\nRevenue | 1200 | 1450\nGrowth | 0.08 | 0.10"
    chunks = build_chunks_from_text(text, doc_id="abc123", filename="model.xlsx")
    assert chunks
    assert chunks[0]["filename"] == "model.xlsx"
    assert chunks[0]["sheet"] == "Revenue"
    assert "1200" in chunks[0]["text"]


def test_format_chunk_citation_includes_source_marker() -> None:
    chunk = {
        "text": "Revenue | 1200 | 1450",
        "filename": "model.xlsx",
        "sheet": "Revenue",
    }
    formatted = format_chunk_citation(chunk, "S1")
    assert formatted.startswith("[S1]")
    assert "model.xlsx" in formatted
    assert "Sheet: Revenue" in formatted
    assert "1200" in formatted


def test_evidence_grounds_known_xlsx_number() -> None:
    source_chunks = [
        {
            "source_id": "S1",
            "text": "Revenue | 1200 | 1450",
            "filename": "model.xlsx",
            "sheet": "Revenue",
            "doc_id": "sha",
        }
    ]
    claims = [{"value": "1200", "type": "Financial value", "context": "", "has_assumption_label": False}]
    result = validate_claims_against_evidence(claims, None, source_chunks=source_chunks)
    assert result["unsupported_claims"] == []
    assert result["grounded_claims"]
    assert result["grounded_claims"][0]["citation"] == "model.xlsx, Sheet: Revenue"


def test_evidence_flags_fabricated_number_when_sources_present() -> None:
    source_chunks = [
        {
            "source_id": "S1",
            "text": "Revenue | 1200 | 1450",
            "filename": "model.xlsx",
            "sheet": "Revenue",
        }
    ]
    claims = [{"value": "$500M", "type": "Financial value", "context": "", "has_assumption_label": False}]
    result = validate_claims_against_evidence(claims, None, source_chunks=source_chunks)
    assert result["unsupported_claims"]
    assert result["unsupported_claims"][0]["claim"] == "$500M"


def test_digit_substring_no_longer_passes() -> None:
    """Claim '1' must not pass because '1200' contains digit 1."""
    source_chunks = [{"source_id": "S1", "text": "Revenue | 1200", "filename": "m.xlsx", "sheet": "Rev"}]
    claims = [{"value": "1", "type": "Financial value", "context": "", "has_assumption_label": False}]
    result = validate_claims_against_evidence(claims, None, source_chunks=source_chunks)
    assert result["unsupported_claims"]


def test_assemble_v2_emits_source_registry(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = "p_ground"
    parsed_dir = tmp_path / project_id / "parsed_docs"
    parsed_dir.mkdir(parents=True)
    digest = "deadbeef"
    payload = {
        "sha256": digest,
        "filename": "metrics.xlsx",
        "chunks": build_chunks_from_text(
            "[Sheet: KPIs]\nAnnual savings | 2500000",
            doc_id=digest,
            filename="metrics.xlsx",
        ),
    }
    (parsed_dir / f"{digest}.json").write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr("app.services.retrieval.workspace_path", lambda pid: tmp_path / pid)

    engine = TieredContextEngine()
    bundle = engine.assemble_v2(project_id, "annual savings KPI", char_cap=8000)
    registry = bundle.metadata.get("source_registry") if bundle.metadata else []
    assert isinstance(registry, list) and registry
    assert registry[0].get("filename") == "metrics.xlsx"
    assert "2500000" in registry[0].get("text", "")
    assert "[S1]" in bundle.text


def test_pptx_evidence_hard_fail_blocks_when_sources_present() -> None:
    """Hard gate: fabricated numbers fail render QA when source registry exists."""
    from app.core.config import settings

    slides = [
        {
            "title": "Impact",
            "slide_type": "stat_cards",
            "stat_cards": [{"stat": "$900M", "label": "Savings"}],
        }
    ]
    source_chunks = [
        {"source_id": "S1", "text": "Revenue | 1200", "filename": "actual.xlsx", "sheet": "Data"}
    ]
    report = validate_pptx_slides_evidence(slides, None, source_chunks)
    assert report["unsupported_claims_count"] >= 1
    assert report["status"] in ("warn", "fail")
    assert settings.pptx_evidence_hard_fail_enabled is True
