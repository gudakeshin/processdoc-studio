import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.db.models import User
from app.db.session import get_db

router = APIRouter()
_OUTPUT_TYPES_CACHE: list[dict] | None = None
_OUTPUT_TYPES_CACHE_MTIME_NS: int | None = None


def _load_output_types() -> list[dict]:
    backend_dir = Path(__file__).resolve().parents[2]  # .../backend
    formats_path = backend_dir / "config" / "output_types.json"
    global _OUTPUT_TYPES_CACHE
    global _OUTPUT_TYPES_CACHE_MTIME_NS

    try:
        stat = formats_path.stat()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="output_types.json missing") from exc

    if _OUTPUT_TYPES_CACHE is not None and stat.st_mtime_ns == _OUTPUT_TYPES_CACHE_MTIME_NS:
        return _OUTPUT_TYPES_CACHE

    try:
        raw = formats_path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="output_types.json invalid JSON") from exc

    if not isinstance(parsed, list):
        raise HTTPException(status_code=500, detail="output_types.json must be a JSON array")
    _OUTPUT_TYPES_CACHE = parsed
    _OUTPUT_TYPES_CACHE_MTIME_NS = stat.st_mtime_ns
    return parsed


@router.get("/output-types")
def list_output_types(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    return {"project_id": pid, "items": _load_output_types()}

