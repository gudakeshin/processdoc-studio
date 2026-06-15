"""Branding defaults align across PPTX, deck HTML, and deck PDF exporters."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.core.deck_exporter import export_deck_artifacts
from app.core.deliverable_pptx import _merge_branding_dict


def test_merge_branding_dict_defaults_to_deloitte() -> None:
    brand = _merge_branding_dict(None)
    assert brand["company_name"] == "Deloitte"


def test_deck_exporter_uses_merged_branding_footer(tmp_path: Path) -> None:
    brand = _merge_branding_dict({"company_name": "Deloitte", "footer_text": "Deloitte."})
    with patch("app.core.deck_exporter._convert_pptx_to_pdf", return_value=None):
        result = export_deck_artifacts(
            [{"slide_type": "title", "title": "Branding Test", "subtitle": "Footer check"}],
            tmp_path,
            brand,
        )
    html = result.html_path.read_text(encoding="utf-8") if result.html_path else ""
    assert "Deloitte" in html
