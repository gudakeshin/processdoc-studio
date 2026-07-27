"""Wiki schema, synthesis, storyline, refresh, source-freshness, and health routes.

Moved verbatim from the former single-module app/api/wiki.py.
"""

from datetime import datetime
from typing import Any
import json

from fastapi import Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.wiki._common import _wiki_dir_for, _wiki_require_access
from app.api.wiki._router import router
from app.core.auth import get_current_user
from app.core.config import settings
from app.core.tz import IST
from app.db.models import User
from app.db.session import get_db


# ===== Schema, synthesis & refresh =====

@router.get("/{wiki_type}/schema/analyze")
async def analyze_wiki_schema(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Analyze wiki content against schema conventions and suggest evolution."""
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
    from app.services.wiki_schema_analyzer import analyze_schema

    return analyze_schema(wiki_type, project_id)


@router.get("/{wiki_type}/schema", response_class=PlainTextResponse)
async def get_wiki_schema_markdown(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """Return ``WIKI_SCHEMA.md`` for editing in the UI."""
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    from app.services.storage import workspace_path
    from app.services.wiki_ingest import _ensure_wiki_schema

    if wiki_type == "leading_practice":
        wiki_dir = workspace_path("leading_practices") / "wiki"
    else:
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id required for project wiki")
        wiki_dir = workspace_path(project_id) / "wiki"

    wiki_dir.mkdir(parents=True, exist_ok=True)
    _ensure_wiki_schema(wiki_dir)
    schema_path = wiki_dir / "WIKI_SCHEMA.md"
    text = schema_path.read_text(encoding="utf-8") if schema_path.exists() else ""
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")


@router.put("/{wiki_type}/schema")
async def put_wiki_schema_markdown(
    wiki_type: str,
    payload: dict[str, Any],
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Replace ``WIKI_SCHEMA.md`` (conventions for ingest/query)."""
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
    content = payload.get("content")
    if not isinstance(content, str):
        raise HTTPException(status_code=400, detail="JSON body must include string 'content'")

    from app.services.storage import workspace_path
    from app.services.wiki_ingest import _ensure_wiki_schema

    if wiki_type == "leading_practice":
        wiki_dir = workspace_path("leading_practices") / "wiki"
    else:
        if not project_id:
            raise HTTPException(status_code=400, detail="project_id required for project wiki")
        wiki_dir = workspace_path(project_id) / "wiki"

    wiki_dir.mkdir(parents=True, exist_ok=True)
    _ensure_wiki_schema(wiki_dir)
    (wiki_dir / "WIKI_SCHEMA.md").write_text(content, encoding="utf-8")
    return {"status": "success"}


@router.get("/{wiki_type}/synthesis/insights")
async def get_wiki_synthesis_insights(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    from app.services.wiki_synthesis import get_synthesis_insights

    data = get_synthesis_insights(wiki_type, project_id)
    if data.get("status") == "error":
        raise HTTPException(status_code=500, detail=data.get("error", "synthesis failed"))
    return data


@router.post("/{wiki_type}/synthesis/create")
async def create_wiki_synthesis_pages(
    wiki_type: str,
    project_id: str | None = None,
    max_pages: int = Query(5, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
    from app.services.wiki_synthesis import create_synthesis_pages

    data = create_synthesis_pages(wiki_type, project_id, max_pages=max_pages)
    if data.get("status") == "error":
        raise HTTPException(status_code=500, detail=data.get("error", "synthesis create failed"))
    return data


@router.get("/{wiki_type}/storyline/draft")
async def get_storyline_draft(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    if not bool(getattr(settings, "wiki_storyline_canvas_enabled", False)):
        raise HTTPException(status_code=404, detail="Storyline canvas is disabled")
    wiki_dir = _wiki_dir_for(wiki_type, project_id)
    draft_file = wiki_dir / ".meta" / "storyline_draft.json"
    if not draft_file.exists():
        return {"status": "success", "draft": {"sections": []}}
    payload = json.loads(draft_file.read_text(encoding="utf-8"))
    if "data" in payload and isinstance(payload.get("data"), dict):
        payload = payload["data"]
    return {"status": "success", "draft": payload}


@router.put("/{wiki_type}/storyline/draft")
async def save_storyline_draft(
    wiki_type: str,
    payload: dict[str, Any],
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _wiki_require_access(wiki_type, project_id, user, db, mutating=True)
    if not bool(getattr(settings, "wiki_storyline_canvas_enabled", False)):
        raise HTTPException(status_code=404, detail="Storyline canvas is disabled")
    draft = payload.get("draft")
    if not isinstance(draft, dict):
        raise HTTPException(status_code=400, detail="Expected 'draft' object")
    sections = draft.get("sections", [])
    if not isinstance(sections, list):
        raise HTTPException(status_code=400, detail="draft.sections must be an array")
    order_values = [s.get("order") for s in sections if isinstance(s, dict)]
    if any(not isinstance(v, int) for v in order_values):
        raise HTTPException(status_code=400, detail="Each section must include integer 'order'")
    if sorted(order_values) != list(range(1, len(order_values) + 1)):
        raise HTTPException(status_code=400, detail="Section order must be contiguous starting at 1")
    wiki_dir = _wiki_dir_for(wiki_type, project_id)
    meta_dir = wiki_dir / ".meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    draft_file = meta_dir / "storyline_draft.json"
    record = {
        "schema_version": 1,
        "data": {
            **draft,
            "updated_at": datetime.now(IST).isoformat(),
            "updated_by": user.id,
        },
    }
    draft_file.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {"status": "success"}


@router.get("/{wiki_type}/refresh/schedule")
async def get_wiki_refresh_schedule(
    wiki_type: str,
    project_id: str | None = None,
    batch_size: int = Query(10, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    from app.services.wiki_refresh import get_refresh_schedule

    return get_refresh_schedule(wiki_type, project_id, batch_size=batch_size)


@router.post("/{wiki_type}/sources/check-freshness")
async def post_wiki_check_source_freshness(
    wiki_type: str,
    project_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _wiki_require_access(wiki_type, project_id, user, db, mutating=False)
    from app.services.wiki_refresh import check_wiki_source_freshness

    data = check_wiki_source_freshness(wiki_type, project_id)
    if data.get("status") == "error":
        raise HTTPException(status_code=500, detail=data.get("error", "freshness check failed"))
    return data


# ===== Health Check =====

@router.get("/health")
async def health_check(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "wiki",
        "version": "1.0.0",
    }


# Register router in main app
