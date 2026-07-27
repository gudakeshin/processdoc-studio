"""Phase 3 — reviewer trust: evidence claim HITL, canvas Office regen, PDF preview artifact."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.evidence_claims import (
    apply_claim_decisions,
    build_claims_from_evidence_report,
    load_claims_dossier,
    pending_unsupported_count,
    write_claims_dossier,
)


def _sample_evidence_report() -> dict:
    return {
        "slide_validations": [
            {
                "slide_title": "Cycle time",
                "validation": {
                    "unsupported_claims": [
                        {
                            "claim": "40%",
                            "type": "Percentage",
                            "context": "Manual work burns 40% of capacity",
                        }
                    ],
                    "grounded_claims": [
                        {
                            "claim": "11 days",
                            "citation": "S1",
                        }
                    ],
                },
            }
        ]
    }


def test_build_claims_marks_unsupported_pending_and_grounded_accepted() -> None:
    claims = build_claims_from_evidence_report(_sample_evidence_report(), source="pptx")
    assert len(claims) == 2
    unsupported = [c for c in claims if c["status"] == "unsupported"]
    grounded = [c for c in claims if c["status"] == "grounded"]
    assert len(unsupported) == 1
    assert unsupported[0]["decision"] == "pending"
    assert unsupported[0]["claim"] == "40%"
    assert grounded[0]["decision"] == "accept"


def test_write_merge_preserves_prior_decisions(tmp_path: Path) -> None:
    report = _sample_evidence_report()
    first = write_claims_dossier(tmp_path, report, source="pptx")
    cid = next(c["id"] for c in first["claims"] if c["status"] == "unsupported")
    apply_claim_decisions(tmp_path, [{"id": cid, "decision": "accept"}], actor="tester@example.com")

    # Re-write from the same report — accept must stick.
    second = write_claims_dossier(tmp_path, report, source="pptx")
    kept = next(c for c in second["claims"] if c["id"] == cid)
    assert kept["decision"] == "accept"
    assert pending_unsupported_count(second) == 0


def test_pending_unsupported_count_ignores_grounded_and_decided(tmp_path: Path) -> None:
    dossier = write_claims_dossier(tmp_path, _sample_evidence_report(), source="pptx")
    assert pending_unsupported_count(dossier) == 1
    cid = next(c["id"] for c in dossier["claims"] if c["status"] == "unsupported")
    apply_claim_decisions(tmp_path, [{"id": cid, "decision": "reject"}])
    loaded = load_claims_dossier(tmp_path)
    assert pending_unsupported_count(loaded) == 0
    assert loaded["summary"]["rejected"] == 1


def test_canvas_regen_invokes_docx_and_xlsx_for_narrative(tmp_path: Path) -> None:
    from app.api.run_artifacts import _regenerate_office_from_canvas

    (tmp_path / "narrative.md").write_text("# Hello\n\nUpdated narrative.", encoding="utf-8")
    docx = MagicMock()
    docx.render.return_value = tmp_path / "output.docx"
    xlsx = MagicMock()
    xlsx.render.return_value = tmp_path / "output.xlsx"

    with (
        patch("app.core.deliverable._init_default_deliverables"),
        patch("app.core.deliverable.DeliverableRegistry.get", side_effect=lambda k: {"docx": docx, "xlsx": xlsx}[k]),
        patch("app.services.branding_service.BrandingService") as branding_cls,
    ):
        branding_cls.return_value.get_branding_for_run.return_value = None
        result = _regenerate_office_from_canvas(
            project_id="p1",
            run_id="r1",
            run_dir=tmp_path,
            artifact_key="narrative_md",
            content="# Hello\n\nUpdated narrative.",
            db=MagicMock(),
        )

    assert "docx" in result["regenerated"]
    assert "xlsx" in result["regenerated"]
    assert docx.render.called
    assert xlsx.render.called


def test_canvas_regen_sop_only_docx(tmp_path: Path) -> None:
    from app.api.run_artifacts import _regenerate_office_from_canvas

    (tmp_path / "sop.md").write_text("## SOP", encoding="utf-8")
    docx = MagicMock()
    docx.render.return_value = tmp_path / "output.docx"
    xlsx = MagicMock()
    xlsx.render.return_value = tmp_path / "output.xlsx"

    with (
        patch("app.core.deliverable._init_default_deliverables"),
        patch("app.core.deliverable.DeliverableRegistry.get", side_effect=lambda k: {"docx": docx, "xlsx": xlsx}[k]),
        patch("app.services.branding_service.BrandingService") as branding_cls,
    ):
        branding_cls.return_value.get_branding_for_run.return_value = None
        result = _regenerate_office_from_canvas(
            project_id="p1",
            run_id="r1",
            run_dir=tmp_path,
            artifact_key="sop_markdown",
            content="## SOP",
            db=MagicMock(),
        )

    assert result["regenerated"] == ["docx"]
    assert not xlsx.render.called


def test_artifacts_bag_exposes_deck_pdf_and_evidence_claims(tmp_path: Path) -> None:
    """Smoke: keys expected by Deck tab fidelity mode + HITL panel."""
    from app.api import run_artifacts as ra

    (tmp_path / "deck.pdf").write_bytes(b"%PDF-1.4 fake")
    write_claims_dossier(tmp_path, _sample_evidence_report(), source="pptx")

    # _read_base64 / _read_json are module helpers — exercise via direct reads mirroring collect.
    pdf_b64 = ra._read_base64(tmp_path / "deck.pdf")
    claims = ra._read_json(tmp_path / "evidence_claims.json")
    assert isinstance(pdf_b64, str) and len(pdf_b64) > 8
    assert isinstance(claims, dict)
    assert claims.get("claims")
    assert pending_unsupported_count(claims) == 1
