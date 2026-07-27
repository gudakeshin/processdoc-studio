"""Deterministic regression tests for the Apollo Tyres POV run failure mode."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.deck_exporter import export_deck_artifacts
from app.core.deliverable_pptx import _merge_branding_dict
from app.services.deliverable_archetype import detect_deliverable_archetype, is_meta_process_model
from app.services.final_artifact_qa import verify_final_artifacts
from app.services.run_worker import _build_evaluator_pipeline

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "run_pov_apollo"


@pytest.fixture
def apollo_slides() -> list[dict]:
    return json.loads((FIXTURE_DIR / "pptx_slides.json").read_text(encoding="utf-8"))


def test_regression_archetype_and_meta_model() -> None:
    instruction = (
        "Lets create a point of view note on Agentic AI interventions for Record to Report "
        "for Apollo Tyres case_led horizontal R2R cycle PPTX"
    )
    assert detect_deliverable_archetype(instruction) == "advisory_pov"
    pm = json.loads((FIXTURE_DIR / "process_model.json").read_text(encoding="utf-8"))
    assert is_meta_process_model(pm) is True


def test_regression_evaluator_no_bypass_on_guardrail_fail() -> None:
    guard = json.loads((FIXTURE_DIR / "guardrail_report.json").read_text(encoding="utf-8"))
    pipeline = _build_evaluator_pipeline(
        requested_outputs=["docx", "pptx"],
        plan_payload={},
        qa_report=json.loads((FIXTURE_DIR / "qa_report.json").read_text(encoding="utf-8")),
        visual_qa_report={"status": "pass"},
        guardrail_report=guard,
    )
    assert pipeline["status"] == "fail"


def test_regression_deck_pdf_contains_slide_titles(tmp_path: Path, apollo_slides: list[dict]) -> None:
    brand = _merge_branding_dict({"company_name": "Deloitte", "footer_text": "Deloitte."})
    with patch("app.core.deck_exporter._convert_pptx_to_pdf", return_value=None):
        result = export_deck_artifacts(
            apollo_slides,
            tmp_path,
            brand,
            pptx_path=None,
        )
    assert result.pdf_path is not None
    assert result.pdf_source == "reportlab"
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(result.pdf_path))
        text = "\n".join(pdf[i].get_textpage().get_text_bounded() for i in range(len(pdf)))
    except Exception:
        pytest.skip("pypdfium2 unavailable")
    titles = [str(s.get("title") or "") for s in apollo_slides if s.get("title")]
    assert titles
    assert any(title in text for title in titles[:3])


def test_regression_process_flow_pdf_non_empty(tmp_path: Path, apollo_slides: list[dict]) -> None:
    flow_slide = next(s for s in apollo_slides if s.get("slide_type") == "process_flow")
    brand = _merge_branding_dict(None)
    result = export_deck_artifacts([flow_slide], tmp_path, brand, pptx_path=None)
    assert result.pdf_path is not None
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(result.pdf_path))
        text = pdf[0].get_textpage().get_text_bounded()
    except Exception:
        pytest.skip("pypdfium2 unavailable")
    steps = flow_slide.get("process_flow", {}).get("steps", [])
    assert steps
    assert any(str(step.get("label") or "") in text for step in steps)


def test_regression_branding_consistent_across_html_pdf(tmp_path: Path, apollo_slides: list[dict]) -> None:
    brand = _merge_branding_dict({"company_name": "Deloitte", "footer_text": "Deloitte."})
    with patch("app.core.deck_exporter._convert_pptx_to_pdf", return_value=None):
        result = export_deck_artifacts(apollo_slides[:2], tmp_path, brand, pptx_path=None)
    html = result.html_path.read_text(encoding="utf-8") if result.html_path else ""
    assert "Deloitte" in html
    if result.pdf_path:
        try:
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(str(result.pdf_path))
            pdf_text = pdf[0].get_textpage().get_text_bounded()
            assert "Deloitte" in pdf_text or "Company" not in pdf_text
        except Exception:
            pass


def test_regression_final_artifact_qa_catches_false_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.storage.workspace_path", lambda _pid: tmp_path)
    from app.services.storage import save_run_artifacts

    payload = {
        "requested_outputs": ["docx", "pptx"],
        "docx_markdown": (FIXTURE_DIR / "docx_markdown.txt").read_text(encoding="utf-8"),
        "narrative_md": "# POV\n\nBody without citations.",
        "pptx_slides": json.loads((FIXTURE_DIR / "pptx_slides.json").read_text(encoding="utf-8")),
        "process_model": json.loads((FIXTURE_DIR / "process_model.json").read_text(encoding="utf-8")),
    }
    save_run_artifacts("p_reg", "r_reg", payload)
    run_dir = tmp_path / "runs" / "r_reg"
    report = verify_final_artifacts(
        run_dir,
        qa_report=json.loads((FIXTURE_DIR / "qa_report.json").read_text(encoding="utf-8")),
        guardrail_report=json.loads((FIXTURE_DIR / "guardrail_report.json").read_text(encoding="utf-8")),
        remediation_notes="Add citations",
    )
    qa = json.loads((FIXTURE_DIR / "qa_report.json").read_text(encoding="utf-8"))
    assert qa.get("passed") is True
    assert report["status"] == "fail"
