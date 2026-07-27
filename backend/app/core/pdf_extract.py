"""Shared PDF text extraction with optional OCR fallback for scanned pages."""

from __future__ import annotations

import io
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def extract_pdf_text(
    content: bytes,
    *,
    filename: str = "document.pdf",
    max_pages: int = 200,
    ocr_enabled: bool = True,
    ocr_min_chars: int = 50,
) -> tuple[str, str]:
    """Extract text from PDF bytes.

    Returns ``(text, parse_mode)`` where parse_mode is ``pdf_text``, ``pdf_ocr``,
    or ``pdf_rejected`` when the page cap is exceeded.
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    page_count = len(reader.pages)
    if page_count > max_pages:
        logger.warning("PDF %s has %s pages; max %s", filename, page_count, max_pages)
        return f"[PDF rejected: exceeds {max_pages} page limit]", "pdf_rejected"

    text_parts: list[str] = []
    ocr_used = False
    for page_num, page in enumerate(reader.pages[:max_pages]):
        page_text = (page.extract_text() or "").strip()
        if ocr_enabled and len(page_text) < ocr_min_chars:
            ocr_text = _ocr_pdf_page(content, page_num)
            if ocr_text:
                page_text = ocr_text.strip()
                ocr_used = True
        if page_text:
            text_parts.append(f"[Page {page_num + 1}]\n{page_text}")

    if text_parts:
        return "\n".join(text_parts), "pdf_ocr" if ocr_used else "pdf_text"
    return "[No text content in PDF]", "pdf_text"


def _ocr_pdf_page(content: bytes, page_index: int) -> str:
    """Best-effort OCR for a single PDF page. Returns empty string on failure."""
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
    except ImportError:
        return ""
    try:
        images = convert_from_bytes(
            content,
            first_page=page_index + 1,
            last_page=page_index + 1,
            dpi=150,
        )
        if not images:
            return ""
        return pytesseract.image_to_string(images[0]) or ""
    except Exception as exc:  # noqa: BLE001
        logger.debug("PDF OCR skipped for page %s of %s: %s", page_index + 1, "pdf", exc)
        return ""


def citation_overlap_score(answer: str, page: dict[str, Any]) -> float:
    """Token overlap between answer and a wiki page (title + content)."""
    answer_tokens = set(re.findall(r"[a-z0-9]{3,}", (answer or "").lower()))
    if not answer_tokens:
        return 0.0
    blob = f"{page.get('title', '')} {page.get('content', '')}".lower()
    page_tokens = set(re.findall(r"[a-z0-9]{3,}", blob))
    if not page_tokens:
        return 0.0
    return len(answer_tokens & page_tokens) / max(1, len(answer_tokens))
