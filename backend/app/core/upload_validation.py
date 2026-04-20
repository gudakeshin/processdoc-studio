"""Shared upload validation (size, extension, minimal magic-byte checks)."""

from __future__ import annotations

from app.core.config import settings
from app.core.exceptions import PayloadTooLargeError, UnsupportedMediaError

# Documents: common source formats for text extraction pipeline
DOCUMENT_UPLOAD_EXTENSIONS = frozenset(
    {
        ".txt",
        ".md",
        ".csv",
        ".json",
        ".pdf",
        ".docx",
        ".pptx",
        ".xlsx",
        ".xls",
    }
)

EXCEL_EXTENSIONS = frozenset({".xlsx", ".xls"})

IMAGE_ICON_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"})


def _suffix(name: str) -> str:
    n = (name or "").lower().strip()
    if "." not in n:
        return ""
    return "." + n.rsplit(".", 1)[-1]


def validate_upload_bytes(
    *,
    filename: str,
    content: bytes,
    allowed_suffixes: frozenset[str],
    max_bytes: int | None = None,
) -> None:
    limit = max_bytes if max_bytes is not None else settings.upload_max_bytes
    if len(content) > limit:
        raise PayloadTooLargeError(f"File exceeds limit of {limit} bytes")
    suf = _suffix(filename)
    if not suf or suf not in allowed_suffixes:
        raise UnsupportedMediaError(f"Allowed types: {', '.join(sorted(allowed_suffixes))}")
    _magic_check(filename, content, suf)


def _magic_check(filename: str, content: bytes, suf: str) -> None:
    if len(content) < 8:
        return
    if suf == ".pdf" and not content.startswith(b"%PDF"):
        raise UnsupportedMediaError("File does not look like a PDF")
    if suf in {".xlsx", ".docx", ".pptx"} and content[:2] != b"PK":
        raise UnsupportedMediaError(f"File does not look like a valid {suf} archive")
    if suf == ".png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise UnsupportedMediaError("File does not look like a PNG")
    if suf in {".jpg", ".jpeg"} and not content.startswith(b"\xff\xd8\xff"):
        raise UnsupportedMediaError("File does not look like a JPEG")
    # .xls is legacy OLE; skip magic check (parser will fail safely)


def validate_document_upload(filename: str, content: bytes) -> None:
    validate_upload_bytes(filename=filename, content=content, allowed_suffixes=DOCUMENT_UPLOAD_EXTENSIONS)


def validate_excel_upload(filename: str, content: bytes) -> None:
    validate_upload_bytes(filename=filename, content=content, allowed_suffixes=EXCEL_EXTENSIONS)


def validate_icon_upload(filename: str, content: bytes, *, max_bytes: int = 2 * 1024 * 1024) -> None:
    validate_upload_bytes(
        filename=filename, content=content, allowed_suffixes=IMAGE_ICON_EXTENSIONS, max_bytes=max_bytes
    )
