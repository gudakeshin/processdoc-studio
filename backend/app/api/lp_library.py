import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.db.models import User
from app.db.session import get_db
from app.services.leading_practices import leading_practice_library_service
from app.services.storage import workspace_path

router = APIRouter()

logger = logging.getLogger(__name__)


class BookmarkRequest(BaseModel):
    project_id: str
    item_id: str
    note: str = ""


def _bookmarks_path(project_id: str) -> Path:
    return workspace_path(project_id) / "lp_bookmarks.json"


def _read_bookmarks(project_id: str) -> list[dict[str, Any]]:
    p = _bookmarks_path(project_id)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except Exception:
        logger.warning("could not read lp bookmarks for project %s; treating as empty", project_id, exc_info=True)
        return []


def _write_bookmarks(project_id: str, items: list[dict[str, Any]]) -> None:
    p = _bookmarks_path(project_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, indent=2), encoding="utf-8")


@router.get("/search")
def search_lp_library(
    project_id: str,
    q: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    results = leading_practice_library_service.search(q, project_id=project_id)
    return {"project_id": project_id, "query": q, "items": results}


@router.post("/refresh")
def refresh_lp_index(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    leading_practice_library_service.ensure_index(force=True)
    return {"project_id": project_id, "status": "refreshed"}


@router.get("/bookmarks")
def list_bookmarks(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    return {"project_id": project_id, "items": _read_bookmarks(project_id)}


@router.post("/bookmarks")
def add_bookmark(
    body: BookmarkRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(body.project_id, {"Owner", "Editor"}, user, db)
    items = _read_bookmarks(body.project_id)
    items = [x for x in items if x.get("item_id") != body.item_id]
    items.append({"item_id": body.item_id, "note": body.note, "added_by": user.email})
    _write_bookmarks(body.project_id, items)
    return {"project_id": body.project_id, "status": "saved", "item_id": body.item_id}


@router.delete("/bookmarks/{item_id}")
def delete_bookmark(
    item_id: str,
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    items = _read_bookmarks(project_id)
    before = len(items)
    items = [x for x in items if x.get("item_id") != item_id]
    _write_bookmarks(project_id, items)
    if len(items) == before:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return {"project_id": project_id, "status": "deleted", "item_id": item_id}

