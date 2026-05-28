import asyncio
import hashlib
import json
import re
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.core.upload_validation import validate_document_upload
from app.db.models import User
from app.db.session import get_db
from app.services.cache import cache_service
from app.services.storage import ensure_workspace, workspace_path

router = APIRouter()

_SAFE_PROJECT_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_project_id_param(project_id: str) -> None:
    if not project_id or not _SAFE_PROJECT_ID.match(project_id):
        raise HTTPException(status_code=400, detail="Invalid project_id")


def _normalize_upload_filename(name: str | None) -> str:
    raw = name or "upload.bin"
    if "\x00" in raw or "/" in raw or "\\" in raw:
        raise HTTPException(status_code=400, detail="Invalid filename")
    p = Path(raw)
    if ".." in p.parts or p.is_absolute():
        raise HTTPException(status_code=400, detail="Invalid filename")
    base = p.name
    if not base or base in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    return base


async def _extract_text_from_bytes(filename: str, content: bytes, timeout_sec: int = 30) -> tuple[str, str]:
    """Extract text from various document formats with timeout protection."""
    lower = (filename or "").lower()

    if lower.endswith((".txt", ".md", ".csv", ".json")):
        return content.decode("utf-8", errors="ignore"), "utf8_text"

    if lower.endswith(".docx") or lower.endswith(".pptx"):
        try:
            def _extract_zip():
                import io
                text_parts: list[str] = []
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    for name in zf.namelist():
                        if lower.endswith(".docx") and not name.startswith("word/"):
                            continue
                        if lower.endswith(".pptx") and not name.startswith("ppt/"):
                            continue
                        if not name.endswith(".xml"):
                            continue
                        raw = zf.read(name).decode("utf-8", errors="ignore")
                        cleaned = re.sub(r"<[^>]+>", " ", raw)
                        cleaned = re.sub(r"\s+", " ", cleaned).strip()
                        if cleaned:
                            text_parts.append(cleaned)
                return "\n".join(text_parts)

            text = await asyncio.wait_for(
                asyncio.to_thread(_extract_zip),
                timeout=timeout_sec
            )
            return text, "zip_xml"
        except TimeoutError:
            # Timeout during extraction, fallback to binary
            return content.decode("utf-8", errors="ignore"), "zip_timeout_fallback"
        except Exception:
            return content.decode("utf-8", errors="ignore"), "zip_error_fallback"

    if lower.endswith(".pdf"):
        try:
            def _extract_pdf():
                import io

                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(content))
                pages = []
                # Limit pages to first 50 for very large PDFs
                for idx, page in enumerate(reader.pages[:50]):
                    if idx > 50:
                        break
                    try:
                        text = page.extract_text() or ""
                        if text.strip():
                            pages.append(text)
                    except Exception:  # noqa: S112 — best-effort, non-fatal
                        # Skip pages that fail extraction
                        continue
                return "\n".join(pages)

            text = await asyncio.wait_for(
                asyncio.to_thread(_extract_pdf),
                timeout=timeout_sec
            )
            return text, "pypdf"
        except TimeoutError:
            # PDF extraction timeout, return empty text
            return f"[PDF extraction timeout for {filename}]", "pdf_timeout_fallback"
        except Exception:
            return f"[Unable to extract PDF for {filename}]", "pdf_error_fallback"

    if lower.endswith(".xlsx"):
        try:
            def _extract_xlsx():
                import io

                from openpyxl import load_workbook

                wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
                text_parts: list[str] = []
                for sheet_name in wb.sheetnames:
                    ws = wb[sheet_name]
                    sheet_text: list[str] = [sheet_name]
                    for row in ws.iter_rows(values_only=True):
                        row_text = " ".join(str(cell or "").strip() for cell in row if cell is not None)
                        if row_text.strip():
                            sheet_text.append(row_text)
                    if len(sheet_text) > 1:
                        text_parts.append("\n".join(sheet_text))
                return "\n\n".join(text_parts)

            text = await asyncio.wait_for(
                asyncio.to_thread(_extract_xlsx),
                timeout=timeout_sec
            )
            return text, "openpyxl"
        except TimeoutError:
            return f"[XLSX extraction timeout for {filename}]", "xlsx_timeout_fallback"
        except Exception:
            return f"[Unable to extract XLSX for {filename}]", "xlsx_error_fallback"

    return content.decode("utf-8", errors="ignore"), "binary_fallback"


@router.post("/upload")
async def upload_document(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    request: Request = None,
) -> dict:
    """Upload and parse a document.

    Timeout: 60 seconds for file reading + parsing.
    Supports: txt, md, csv, json, pdf, docx, pptx, xlsx, xls
    """
    _validate_project_id_param(project_id)
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    ensure_workspace(project_id)

    try:
        # Read file with timeout (30 sec for up to 100MB)
        content = await asyncio.wait_for(file.read(), timeout=30.0)
    except TimeoutError:
        raise HTTPException(
            status_code=408,
            detail="File upload timeout. File may be too large or network too slow. Try smaller file (< 50MB)."
        ) from None

    safe_name = _normalize_upload_filename(file.filename)
    validate_document_upload(safe_name, content)
    if safe_name.lower().endswith(".pdf"):
        import io as _io

        from pypdf import PdfReader

        try:
            page_count = len(PdfReader(_io.BytesIO(content)).pages)
        except Exception:
            page_count = 0
        if page_count > 50:
            raise HTTPException(
                status_code=400,
                detail=f"PDF has {page_count} pages; maximum allowed is 50",
            )
    digest = hashlib.sha256(content).hexdigest()

    cached = cache_service.get(f"parse:{digest}")
    text, parse_mode = None, None

    if cached and isinstance(cached.get("chunks"), list):
        text = cached.get("text", "")
        parse_mode = cached.get("parse_mode", "cached")
        chunks = cached.get("chunks", [])
    else:
        try:
            # Extract text with 30-second timeout
            text, parse_mode = await asyncio.wait_for(
                _extract_text_from_bytes(safe_name, content, timeout_sec=30),
                timeout=35.0  # Slightly longer than internal timeout for margin
            )
        except TimeoutError:
            # Fall back to basic decode on timeout
            text = content.decode("utf-8", errors="ignore")
            parse_mode = "timeout_fallback"

        def chunk_text(t: str, *, chunk_chars: int = 1200, overlap_chars: int = 120) -> list[str]:
            t = t.strip()
            if not t:
                return []
            out: list[str] = []
            start = 0
            while start < len(t):
                end = min(len(t), start + chunk_chars)
                chunk = t[start:end].strip()
                if chunk:
                    out.append(chunk)
                if end >= len(t):
                    break
                start = max(0, end - overlap_chars)
            return out

        chunks = chunk_text(text)
        cached = {
            "status": "chunked",
            "chars": len(text),
            "chunk_count": len(chunks),
            "chunks": chunks,
            "text": text,
            "parse_mode": parse_mode,
        }
        cache_service.set(f"parse:{digest}", cached, ttl_seconds=3600)

    target = workspace_path(project_id) / "source_docs" / safe_name
    target.write_bytes(content)

    parsed_path = workspace_path(project_id) / "parsed_docs" / f"{digest}.json"
    parsed_payload = {
        "sha256": digest,
        "filename": safe_name,
        "chars": len(text or ""),
        "parse_mode": parse_mode,
        "text": text or "",
        "chunks": chunks,
    }
    parsed_path.write_text(json.dumps(parsed_payload, indent=2), encoding="utf-8")

    return {
        "filename": safe_name,
        "sha256": digest,
        "parse": {
            "status": cached.get("status"),
            "chars": cached.get("chars"),
            "chunk_count": len(chunks),
            "mode": parse_mode
        },
        "path": str(target),
        "parsed_path": str(parsed_path),
    }


@router.get("/list")
def list_documents(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    _validate_project_id_param(project_id)
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    ensure_workspace(project_id)
    docs = sorted((workspace_path(project_id) / "source_docs").glob("*"))
    return {"items": [str(d) for d in docs if d.is_file()]}


@router.delete("/delete")
def delete_document(
    project_id: str,
    filename: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _validate_project_id_param(project_id)
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    ensure_workspace(project_id)
    source_dir = workspace_path(project_id) / "source_docs"
    safe_fn = _normalize_upload_filename(filename)
    target = source_dir / safe_fn
    try:
        resolved_target = target.resolve()
        resolved_source = source_dir.resolve()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found") from None
    if resolved_source not in resolved_target.parents:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not resolved_target.exists() or not resolved_target.is_file():
        raise HTTPException(status_code=404, detail="Document not found")
    # Best effort cleanup of parsed chunk file via content hash.
    content = resolved_target.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    parsed_path = workspace_path(project_id) / "parsed_docs" / f"{digest}.json"
    resolved_target.unlink(missing_ok=True)
    parsed_path.unlink(missing_ok=True)
    return {"deleted": True, "filename": safe_fn}
