from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings
from app.services.run_worker import _persist_pptx_visual_critic_signals
from app.services.visual_qa import _evaluate_pptx


def test_persist_pptx_visual_critic_signals_preserves_existing_content(tmp_path: Path) -> None:
    run_dir = tmp_path
    signals_path = run_dir / "pptx_render_signals.json"
    signals_path.write_text(
        json.dumps({"content_pending": [{"slide_index": 2, "reason": "Missing body"}]}),
        encoding="utf-8",
    )
    report = {
        "per_artifact": {
            "pptx": {
                "status": "warn",
                "summary": "One slide needs adjustment.",
                "per_slide_findings": [{"index": 2, "issue": "Low density", "severity": "medium"}],
                "remediation_hints": [{"slide_index": 2, "instruction": "Add one more metric card."}],
            }
        }
    }
    _persist_pptx_visual_critic_signals(run_dir, report)
    stored = json.loads(signals_path.read_text(encoding="utf-8"))
    assert "content_pending" in stored
    assert "visual_critic" in stored
    assert stored["visual_critic"]["status"] == "warn"
    assert stored["visual_critic"]["remediation_hints"]


def test_evaluate_pptx_respects_feature_flag(monkeypatch, tmp_path: Path) -> None:
    pptx_path = tmp_path / "output.pptx"
    pptx_path.write_bytes(b"placeholder")
    monkeypatch.setattr(settings, "pptx_visual_critic_enabled", False, raising=False)
    out = _evaluate_pptx(pptx_path, "p1", "r1")
    assert out["status"] == "skip"
    assert "disabled" in str(out["summary"]).lower()


def test_evaluate_pptx_fail_open_on_model_error(monkeypatch, tmp_path: Path) -> None:
    pptx_path = tmp_path / "output.pptx"
    pptx_path.write_bytes(b"placeholder")
    monkeypatch.setattr(settings, "pptx_visual_critic_enabled", True, raising=False)
    # Force the metadata path explicitly — this test targets the metadata fallback's
    # own fail-open behavior, not pixel-path selection.
    monkeypatch.setattr(settings, "pptx_visual_critic_mode", "metadata", raising=False)
    monkeypatch.setattr("app.services.visual_qa.is_claude_enabled", lambda: True)
    monkeypatch.setattr(
        "app.services.visual_qa._extract_pptx_metadata",
        lambda _: {"slide_count": 1, "slides": [{"index": 1, "shape_count": 4, "text_blocks": 3, "fill_colors": []}]},
    )

    def _boom(**_: object) -> dict:
        raise RuntimeError("network")

    monkeypatch.setattr("app.services.visual_qa.claude_generate_json", _boom)
    out = _evaluate_pptx(pptx_path, "p1", "r1")
    assert out["status"] == "skip"
    assert "failed" in str(out["summary"]).lower()


def test_evaluate_pptx_prompt_avoids_hardcoded_brand_bias(monkeypatch, tmp_path: Path) -> None:
    pptx_path = tmp_path / "output.pptx"
    pptx_path.write_bytes(b"placeholder")
    monkeypatch.setattr(settings, "pptx_visual_critic_enabled", True, raising=False)
    # Force the metadata path explicitly — this test inspects the metadata prompt
    # text, not pixel-path selection.
    monkeypatch.setattr(settings, "pptx_visual_critic_mode", "metadata", raising=False)
    monkeypatch.setattr("app.services.visual_qa.is_claude_enabled", lambda: True)
    monkeypatch.setattr(
        "app.services.visual_qa._extract_pptx_metadata",
        lambda _: {"slide_count": 1, "canvas_w_inches": 13.333, "canvas_h_inches": 7.5, "slides": []},
    )

    seen_user = {"text": ""}

    def _ok(**kwargs: object) -> dict:
        seen_user["text"] = str(kwargs.get("user") or "")
        return {"status": "pass", "summary": "ok", "per_slide_findings": [], "remediation_hints": []}

    monkeypatch.setattr("app.services.visual_qa.claude_generate_json", _ok)
    out = _evaluate_pptx(pptx_path, "p1", "r1")
    assert out["status"] == "pass"
    assert "10.0" not in seen_user["text"]
    assert "#86BC25" not in seen_user["text"]


def test_evaluate_pptx_uses_pixel_path_when_deps_present(monkeypatch, tmp_path: Path) -> None:
    """When soffice + pypdfium2 + vision model all succeed, the report is tagged pixel."""
    pptx_path = tmp_path / "output.pptx"
    pptx_path.write_bytes(b"placeholder")
    monkeypatch.setattr(settings, "pptx_visual_critic_enabled", True, raising=False)
    monkeypatch.setattr(settings, "pptx_visual_critic_mode", "auto", raising=False)
    monkeypatch.setattr("app.services.visual_qa.is_claude_enabled", lambda: True)

    def _fake_pdf(_src: Path, outdir: Path) -> Path:
        pdf = Path(outdir) / "out.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        return pdf

    monkeypatch.setattr("app.services.visual_qa._convert_office_to_pdf", _fake_pdf)
    monkeypatch.setattr("app.services.visual_qa._render_pdf_pages_to_png", lambda *a, **k: [b"img"])
    monkeypatch.setattr(
        "app.services.visual_qa.claude_generate_json_with_images",
        lambda **_: {
            "status": "warn",
            "summary": "uneven density",
            "per_slide_findings": [{"index": 1, "issue": "cramped", "severity": "medium"}],
            "remediation_hints": [{"slide_index": 1, "instruction": "add whitespace"}],
        },
    )

    out = _evaluate_pptx(pptx_path, "p1", "r1")
    assert out["critic_path"] == "pixel"
    assert out["status"] == "warn"
    assert out["remediation_hints"]


def test_evaluate_pptx_marks_metadata_degradation_when_soffice_missing(monkeypatch, tmp_path: Path) -> None:
    """Auto mode that cannot run the pixel path must label the metadata fallback and say why."""
    pptx_path = tmp_path / "output.pptx"
    pptx_path.write_bytes(b"placeholder")
    monkeypatch.setattr(settings, "pptx_visual_critic_enabled", True, raising=False)
    monkeypatch.setattr(settings, "pptx_visual_critic_mode", "auto", raising=False)
    monkeypatch.setattr("app.services.visual_qa.is_claude_enabled", lambda: True)
    monkeypatch.setattr("app.services.visual_qa._convert_office_to_pdf", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.services.visual_qa._extract_pptx_metadata",
        lambda _: {"slide_count": 1, "slides": [{"index": 1, "shape_count": 4, "text_blocks": 3, "fill_colors": []}]},
    )
    monkeypatch.setattr(
        "app.services.visual_qa.claude_generate_json",
        lambda **_: {"status": "pass", "summary": "ok", "per_slide_findings": [], "remediation_hints": []},
    )

    out = _evaluate_pptx(pptx_path, "p1", "r1")
    assert out["critic_path"] == "metadata"
    assert "soffice" in str(out.get("critic_degraded_reason", "")).lower()
