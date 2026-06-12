"""Zip-bomb guard for document text extraction (documents.py)."""

from __future__ import annotations

import io
import zipfile

import pytest

from app.api.documents import _extract_text_from_bytes
from app.core.config import settings


def _make_docx_zip(xml_body: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", xml_body)
    return buf.getvalue()


async def test_oversized_zip_falls_back_without_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _make_docx_zip(b"<w:t>" + b"A" * 4096 + b"</w:t>")
    monkeypatch.setattr(settings, "zip_max_uncompressed_bytes", 16)
    text, method = await _extract_text_from_bytes("report.docx", content)
    assert method == "zip_error_fallback"


async def test_normal_docx_extracts_text() -> None:
    content = _make_docx_zip(b"<w:t>Quarterly close analysis</w:t>")
    text, method = await _extract_text_from_bytes("report.docx", content)
    assert method == "zip_xml"
    assert "Quarterly close analysis" in text
