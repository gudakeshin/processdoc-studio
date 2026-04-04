import hashlib
import json
import re
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.core.upload_validation import validate_document_upload
from app.db.models import User
from app.db.session import get_db
from app.services.cache import cache_service
from app.services.storage import ensure_workspace, workspace_path

router = APIRouter()


def _extract_text_from_bytes(filename: str, content: bytes) -> tuple[str, str]:
    lower = (filename or "").lower()
    if lower.endswith((".txt", ".md", ".csv", ".json")):
        return content.decode("utf-8", errors="ignore"), "utf8_text"
    if lower.endswith(".docx") or lower.endswith(".pptx"):
        try:
            import io

            zf = zipfile.ZipFile(io.BytesIO(content))
            text_parts: list[str] = []
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
            return "\n".join(text_parts), "zip_xml"
        except Exception:
            return content.decode("utf-8", errors="ignore"), "binary_fallback"
    if lower.endswith(".pdf"):
        try:
            import io
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            pages = []
            for page in reader.pages:
                pages.append(page.extract_text() or "")
            return "\n".join(pages), "pypdf"
        except Exception:
            return content.decode("utf-8", errors="ignore"), "binary_fallback"
    return content.decode("utf-8", errors="ignore"), "binary_fallback"


@router.post("/upload")
async def upload_document(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    ensure_workspace(project_id)
    content = await file.read()
    validate_document_upload(file.filename or "upload.bin", content)
    digest = hashlib.sha256(content).hexdigest()

    cached = cache_service.get(f"parse:{digest}")
    text, parse_mode = _extract_text_from_bytes(file.filename or "", content)

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

    chunks: list[str]
    if cached and isinstance(cached.get("chunks"), list) and all(isinstance(x, str) for x in cached["chunks"]):
        chunks = cached["chunks"]
    else:
        chunks = chunk_text(text)
        cached = {"status": "chunked", "chars": len(text), "chunk_count": len(chunks), "chunks": chunks}
        cache_service.set(f"parse:{digest}", cached, ttl_seconds=3600)

    target = workspace_path(project_id) / "source_docs" / (file.filename or "upload.bin")
    target.write_bytes(content)

    parsed_path = workspace_path(project_id) / "parsed_docs" / f"{digest}.json"
    parsed_payload = {
        "sha256": digest,
        "filename": file.filename,
        "chars": len(text),
        "parse_mode": parse_mode,
        "chunks": chunks,
    }
    parsed_path.write_text(json.dumps(parsed_payload, indent=2), encoding="utf-8")

    return {
        "filename": file.filename,
        "sha256": digest,
        "parse": {"status": cached.get("status"), "chars": cached.get("chars"), "chunk_count": len(chunks), "mode": parse_mode},
        "path": str(target),
        "parsed_path": str(parsed_path),
    }


@router.get("/list")
def list_documents(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
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
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    ensure_workspace(project_id)
    source_dir = workspace_path(project_id) / "source_docs"
    target = source_dir / filename
    try:
        resolved_target = target.resolve()
        resolved_source = source_dir.resolve()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Document not found")
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
    return {"deleted": True, "filename": Path(filename).name}
