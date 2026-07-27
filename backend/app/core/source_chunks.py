"""Provenance-aware source document chunks for retrieval and evidence validation."""

from __future__ import annotations

import re
from typing import Any

_PAGE_MARKER_RE = re.compile(r"^\[Page (\d+)\]\s*$")
_SHEET_MARKER_RE = re.compile(r"^\[Sheet:\s*([^\]]+)\]\s*$")

# Numeric token for evidence matching — requires at least two digits to avoid
# spurious "1" ↔ "1200" substring passes.
_NUMERIC_TOKEN_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?!\d)"
)


def chunk_text(raw: str | dict[str, Any]) -> str:
    """Return searchable text from a legacy string or provenance chunk dict."""
    if isinstance(raw, str):
        return raw.strip()
    return str(raw.get("text") or "").strip()


def normalize_chunk(
    raw: str | dict[str, Any],
    *,
    doc_id: str = "",
    filename: str = "",
) -> dict[str, Any]:
    """Convert a legacy ``list[str]`` entry or partial dict to a full chunk record."""
    if isinstance(raw, str):
        text = raw.strip()
        return {
            "text": text,
            "doc_id": doc_id,
            "filename": filename,
            "page": None,
            "sheet": None,
            "char_start": 0,
            "char_end": len(text),
        }
    text = str(raw.get("text") or "").strip()
    page = raw.get("page")
    sheet = raw.get("sheet")
    return {
        "text": text,
        "doc_id": str(raw.get("doc_id") or doc_id),
        "filename": str(raw.get("filename") or filename),
        "page": int(page) if isinstance(page, int) or (isinstance(page, str) and str(page).isdigit()) else None,
        "sheet": str(sheet).strip() if sheet else None,
        "char_start": int(raw.get("char_start") or 0),
        "char_end": int(raw.get("char_end") or len(text)),
        **({"source_id": str(raw["source_id"])} if raw.get("source_id") else {}),
    }


def _split_sections(text: str) -> list[tuple[int | None, str | None, str]]:
    """Split extracted text on ``[Page N]`` / ``[Sheet: X]`` boundary markers."""
    sections: list[tuple[int | None, str | None, str]] = []
    current_page: int | None = None
    current_sheet: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        page_m = _PAGE_MARKER_RE.match(line.strip())
        sheet_m = _SHEET_MARKER_RE.match(line.strip())
        if page_m:
            if buf:
                body = "\n".join(buf).strip()
                if body:
                    sections.append((current_page, current_sheet, body))
                buf = []
            current_page = int(page_m.group(1))
            current_sheet = None
            continue
        if sheet_m:
            if buf:
                body = "\n".join(buf).strip()
                if body:
                    sections.append((current_page, current_sheet, body))
                buf = []
            current_sheet = sheet_m.group(1).strip()
            current_page = None
            continue
        buf.append(line)
    if buf:
        body = "\n".join(buf).strip()
        if body:
            sections.append((current_page, current_sheet, body))
    if not sections and text.strip():
        sections.append((None, None, text.strip()))
    return sections


def _window_chunk(
    body: str,
    *,
    doc_id: str,
    filename: str,
    page: int | None,
    sheet: str | None,
    chunk_chars: int,
    overlap_chars: int,
    base_offset: int,
) -> list[dict[str, Any]]:
    """Fixed-size overlapping windows within one section."""
    out: list[dict[str, Any]] = []
    t = body.strip()
    if not t:
        return out
    start = 0
    while start < len(t):
        end = min(len(t), start + chunk_chars)
        piece = t[start:end].strip()
        if piece:
            abs_start = base_offset + start
            abs_end = base_offset + end
            out.append({
                "text": piece,
                "doc_id": doc_id,
                "filename": filename,
                "page": page,
                "sheet": sheet,
                "char_start": abs_start,
                "char_end": abs_end,
            })
        if end >= len(t):
            break
        start = max(0, end - overlap_chars)
    return out


def build_chunks_from_text(
    text: str,
    *,
    doc_id: str,
    filename: str,
    chunk_chars: int = 1200,
    overlap_chars: int = 120,
) -> list[dict[str, Any]]:
    """Section-aware chunking that preserves page/sheet provenance from ingest markers."""
    sections = _split_sections(text or "")
    chunks: list[dict[str, Any]] = []
    cursor = 0
    for page, sheet, body in sections:
        section_chunks = _window_chunk(
            body,
            doc_id=doc_id,
            filename=filename,
            page=page,
            sheet=sheet,
            chunk_chars=chunk_chars,
            overlap_chars=overlap_chars,
            base_offset=cursor,
        )
        chunks.extend(section_chunks)
        cursor += len(body) + 1
    return chunks


def format_chunk_citation(chunk: dict[str, Any], source_id: str) -> str:
    """Inline context marker, e.g. ``[S3] (file.xlsx · Sheet: Revenue) …``."""
    filename = str(chunk.get("filename") or "source").strip()
    loc_parts: list[str] = []
    if chunk.get("sheet"):
        loc_parts.append(f"Sheet: {chunk['sheet']}")
    if chunk.get("page"):
        loc_parts.append(f"Page {chunk['page']}")
    loc = " · ".join(loc_parts)
    header = f"[{source_id}] ({filename}{(' · ' + loc) if loc else ''})"
    body = chunk_text(chunk)
    return f"{header}\n{body}" if body else header


def assign_source_ids(chunks: list[dict[str, Any]], *, prefix: str = "S") -> list[dict[str, Any]]:
    """Return copies with sequential ``source_id`` fields (``S1``, ``S2``, …)."""
    out: list[dict[str, Any]] = []
    for i, chunk in enumerate(chunks, start=1):
        c = dict(chunk)
        c["source_id"] = f"{prefix}{i}"
        out.append(c)
    return out


def normalize_numeric(value: str) -> float | None:
    """Parse a numeric claim or evidence token; returns None if not a number."""
    raw = re.sub(r"[^\d.\-]", "", str(value or ""))
    if not raw or raw in {".", "-", "-."}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def extract_numeric_tokens(text: str) -> list[str]:
    """Extract normalized numeric strings suitable for evidence matching."""
    tokens: list[str] = []
    for m in _NUMERIC_TOKEN_RE.finditer(text or ""):
        tok = m.group(1).replace(",", "")
        if len(re.sub(r"[^\d]", "", tok)) >= 1:
            tokens.append(tok)
    return tokens


def citation_label(chunk: dict[str, Any]) -> str:
    """Human-readable source label for footnotes."""
    filename = str(chunk.get("filename") or "source")
    if chunk.get("sheet"):
        return f"{filename}, Sheet: {chunk['sheet']}"
    if chunk.get("page"):
        return f"{filename}, Page {chunk['page']}"
    return filename
