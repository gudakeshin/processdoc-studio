from __future__ import annotations

from pathlib import Path

import pytest

from app.core.deck_exporter import DeckExportResult, export_deck_artifacts


def _sample_slides() -> list[dict]:
    return [
        {
            "slide_index": 1,
            "slide_type": "title",
            "title": "Finance Transformation Roadmap",
            "subtitle": "Q3 executive briefing",
        },
        {
            "slide_index": 2,
            "slide_type": "bullets",
            "title": "Key Initiatives",
            "bullets": ["Close cycle automation", "Forecast accuracy", "Controls hygiene"],
        },
        {
            "slide_index": 3,
            "slide_type": "stat_cards",
            "title": "Signals",
            "stat_cards": [
                {"stat": "22%", "label": "ROI"},
                {"stat": "7mo", "label": "Payback"},
                {"stat": "3", "label": "Phases"},
            ],
        },
        {
            "slide_index": 4,
            "slide_type": "column_cards",
            "title": "Workstreams",
            "column_cards": [
                {"heading": "People", "body": "Upskill FP&A"},
                {"heading": "Process", "body": "Standardize MEC"},
                {"heading": "Tech", "body": "Unified model"},
            ],
        },
        {
            "slide_index": 5,
            "slide_type": "table",
            "title": "Scorecard",
            "table": {
                "headers": ["Metric", "Baseline", "Target"],
                "rows": [
                    ["Days to close", "10", "5"],
                    ["Forecast MAPE", "12%", "6%"],
                ],
            },
        },
        {
            "slide_index": 6,
            "slide_type": "section_divider",
            "title": "Appendix",
            "subtitle": "Supporting material",
        },
    ]


def test_export_deck_artifacts_writes_html_and_pdf(tmp_path: Path) -> None:
    result = export_deck_artifacts(
        _sample_slides(),
        tmp_path,
        branding={
            "primary_color": "#123456",
            "company_name": "Acme Corp",
            "font_family": "Inter, Helvetica, Arial, sans-serif",
        },
    )

    assert isinstance(result, DeckExportResult)
    assert result.html_path is not None
    assert result.html_path.exists()
    html_body = result.html_path.read_text(encoding="utf-8")
    assert "Finance Transformation Roadmap" in html_body
    assert "Acme Corp" in html_body
    assert "#123456" in html_body

    if result.pdf_path is not None:
        assert result.pdf_path.exists()
        assert result.pdf_path.stat().st_size > 0


def test_export_deck_artifacts_empty_slides_no_op(tmp_path: Path) -> None:
    result = export_deck_artifacts([], tmp_path)
    assert result.html_path is None
    assert result.pdf_path is None
    assert not (tmp_path / "deck.html").exists()
    assert not (tmp_path / "deck.pdf").exists()


def test_export_deck_artifacts_fail_open_when_pdf_renderer_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.core.deck_exporter as exporter

    def _boom(*_args, **_kwargs):
        return None

    monkeypatch.setattr(exporter, "_render_pdf", _boom)
    result = export_deck_artifacts(_sample_slides(), tmp_path)
    assert result.html_path is not None and result.html_path.exists()
    assert result.pdf_path is None
    assert any("pdf" in err for err in (result.errors or []))


def test_export_deck_artifacts_sanitizes_html_content(tmp_path: Path) -> None:
    slides = [
        {
            "slide_index": 1,
            "slide_type": "bullets",
            "title": "<script>alert('x')</script>",
            "bullets": ["<img onerror='x' src=y>"],
        }
    ]
    result = export_deck_artifacts(slides, tmp_path)
    assert result.html_path is not None
    body = result.html_path.read_text(encoding="utf-8")
    assert "<script>alert" not in body
    assert "&lt;script&gt;alert" in body
    assert "&lt;img" in body
