"""Zip-bomb guard for document text extraction (documents.py → wiki_ingest)."""

from __future__ import annotations

import io
import zipfile

import pytest
from docx import Document

from app.api.documents import _extract_text_from_bytes
from app.core.config import settings


def _make_docx_bytes(text: str) -> bytes:
    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _make_pptx_zip(xml_body: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", b'<?xml version="1.0"?><Types/>')
        zf.writestr("ppt/slides/slide1.xml", xml_body)
    return buf.getvalue()


async def test_oversized_zip_falls_back_without_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _make_pptx_zip(b"<a:t>" + b"A" * 4096 + b"</a:t>")
    monkeypatch.setattr(settings, "zip_max_uncompressed_bytes", 16)
    text, method = await _extract_text_from_bytes("report.pptx", content)
    assert method == "wiki_ingest_pptx"
    assert "Rejected PPTX archive" in text or "failed safety checks" in text


async def test_normal_docx_extracts_text() -> None:
    content = _make_docx_bytes("Quarterly close analysis")
    text, method = await _extract_text_from_bytes("report.docx", content)
    assert method == "wiki_ingest_docx"
    assert "Quarterly close analysis" in text
