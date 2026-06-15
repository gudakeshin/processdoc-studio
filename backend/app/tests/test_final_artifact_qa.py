"""Tests for post-render artifact verification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.deliverable_docx import DOCXDeliverable
from app.services.final_artifact_qa import verify_final_artifacts
from app.services.storage import save_run_artifacts

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "run_pov_apollo"


def test_verify_final_artifacts_fails_on_apollo_fixture_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.storage.workspace_path", lambda _pid: tmp_path)
    run_dir = tmp_path / "runs" / "r_apollo"
    run_dir.mkdir(parents=True)
    for name in ("qa_report.json", "guardrail_report.json", "docx_markdown.txt"):
        (run_dir / name).write_bytes((FIXTURE_DIR / name).read_bytes())

    qa = json.loads((FIXTURE_DIR / "qa_report.json").read_text(encoding="utf-8"))
    guard = json.loads((FIXTURE_DIR / "guardrail_report.json").read_text(encoding="utf-8"))

    payload = {
        "requested_outputs": ["docx", "pptx"],
        "docx_markdown": (FIXTURE_DIR / "docx_markdown.txt").read_text(encoding="utf-8"),
        "narrative_md": "# Apollo Tyres R2R\n\nIllustrative advisory note.",
        "pptx_slides": json.loads((FIXTURE_DIR / "pptx_slides.json").read_text(encoding="utf-8")),
        "process_model": json.loads((FIXTURE_DIR / "process_model.json").read_text(encoding="utf-8")),
    }
    save_run_artifacts("p_apollo", "r_apollo", payload)

    report = verify_final_artifacts(
        run_dir,
        qa_report=qa,
        guardrail_report=guard,
        remediation_notes="Add citations and Sources and assumptions",
    )
    assert report["status"] == "fail"
    assert report["issues"]


def test_docx_render_rejects_js_fixture_body(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r_docx"
    run_dir.mkdir(parents=True)
    js_body = (FIXTURE_DIR / "docx_markdown.txt").read_text(encoding="utf-8")
    DOCXDeliverable().render(
        {
            "docx_markdown": js_body,
            "narrative_md": "# Apollo R2R POV\n\n## Sources and assumptions\n\n(source: illustrative)",
            "process_model": {"process_name": "R2R"},
        },
        run_dir,
        branding={"company_name": "Deloitte"},
    )
    out = run_dir / "output.docx"
    assert out.is_file()
    from docx import Document

    text = "\n".join(p.text for p in Document(str(out)).paragraphs)
    assert "require('docx')" not in text
    assert "R2R" in text or "Apollo" in text
