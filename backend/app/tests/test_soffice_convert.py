"""Tests for LibreOffice conversion helper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.soffice_convert import convert_office_to_pdf, soffice_path


def test_soffice_path_returns_none_or_string() -> None:
    path = soffice_path()
    assert path is None or isinstance(path, str)


def test_convert_fail_open_when_binary_missing(tmp_path: Path) -> None:
    with patch("app.core.soffice_convert.soffice_path", return_value=None):
        assert convert_office_to_pdf(tmp_path / "x.pptx", tmp_path) is None


@pytest.mark.skipif(not soffice_path(), reason="LibreOffice not installed")
def test_convert_real_pptx_when_soffice_available(tmp_path: Path) -> None:
    from pptx import Presentation

    src = tmp_path / "mini.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.shapes.title.text = "Soffice smoke"
    prs.save(str(src))
    out = convert_office_to_pdf(src, tmp_path, timeout_sec=120.0)
    assert out is not None and out.exists() and out.stat().st_size > 0
