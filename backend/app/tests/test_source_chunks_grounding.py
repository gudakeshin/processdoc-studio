"""Phase 1 grounding: provenance chunks, source-aware evidence validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.evidence_validator import (
    apply_source_citations_to_slides,
    load_source_registry,
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


def test_apply_source_citations_sets_footer_note() -> None:
    slides = [
        {
            "slide_type": "stat_cards",
            "title": "Revenue",
            "stat_cards": [{"stat": "1200", "label": "Annual revenue"}],
        }
    ]
    source_chunks = [
        {
            "source_id": "S1",
            "text": "Revenue | 1200 | 1450",
            "filename": "model.xlsx",
            "sheet": "Revenue",
        }
    ]
    out = apply_source_citations_to_slides(slides, source_chunks, None)
    assert out[0]["footer_note"] == "Source: model.xlsx, Sheet: Revenue"
    assert "Source:" in out[0]["notes"]


def test_load_source_registry_from_disk_top_level(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    registry = [{"source_id": "S1", "text": "Revenue | 99", "filename": "a.xlsx", "sheet": "S1"}]
    (run_dir / "compaction_snapshot.json").write_text(
        json.dumps({"source_registry": registry, "char_cap": 32000}),
        encoding="utf-8",
    )
    loaded = load_source_registry({}, run_dir)
    assert loaded == registry


def test_render_grounds_number_and_blocks_fabrication(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.core.pptx_artifact_renderer import render_pptx_with_artifact_tool
    from app.core.pptx_qa import _extract_pptx_text

    monkeypatch.setattr(settings, "pptx_evidence_hard_fail_enabled", True)
    monkeypatch.setattr(settings, "pptx_editorial_theme_enabled", True)

    branding = {
        "primary_color": "#86BC25",
        "company_name": "Deloitte",
        "font_family": "Calibri",
        "font_family_header": "Calibri Light",
    }
    registry = [
        {
            "source_id": "S1",
            "text": "Revenue | 1200 | 1450",
            "filename": "model.xlsx",
            "sheet": "Revenue",
        }
    ]

    grounded_payload = {
        "pptx_slides": [
            {"slide_type": "title", "title": "Deck"},
            {
                "slide_type": "bullets",
                "title": "Revenue outlook",
                "bullets": ["Annual revenue reached 1200 in the latest period."],
            },
        ],
        "compaction_snapshot": {"source_registry": registry},
    }
    (tmp_path / "grounded").mkdir()
    grounded = render_pptx_with_artifact_tool(grounded_payload, tmp_path / "grounded", branding)
    assert grounded["status"] == "success"
    text_by_slide = _extract_pptx_text(tmp_path / "grounded" / "output.pptx")
    flat = " ".join(" ".join(v) for v in text_by_slide.values()).lower()
    assert "source:" in flat
    assert "model.xlsx" in flat

    (tmp_path / "fabricated").mkdir()
    fabricated = render_pptx_with_artifact_tool(
        {
            "pptx_slides": [
                {"slide_type": "title", "title": "Deck"},
                {
                    "slide_type": "stat_cards",
                    "title": "Impact",
                    "stat_cards": [{"stat": "$900M", "label": "Savings"}],
                },
            ],
            "compaction_snapshot": {"source_registry": registry},
        },
        tmp_path / "fabricated",
        branding,
    )
    assert fabricated["status"] == "failed"
    assert fabricated["qa_report"]["status"] == "fail"
    assert fabricated["qa_report"].get("evidence_hard_fail") is True
