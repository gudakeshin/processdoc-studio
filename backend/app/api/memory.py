import json
import logging
import uuid
from datetime import datetime, timezone
from app.core.tz import IST

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.core.config import settings
from app.db.models import MemoryEvent, MemoryItem, ProjectMemoryProfile, User
from app.db.session import get_db
from app.services.observability import increment

router = APIRouter()

logger = logging.getLogger(__name__)


class UpsertMemoryItemRequest(BaseModel):
    memory_type: str
    key: str
    value: str
    confidence: str = "medium"
    source: str = "chat"
    consent_state: str = "allowed"
    principal_id: str | None = None
    is_archived: bool = False


class MemoryBatchItem(BaseModel):
    memory_type: str = "fact"
    key: str
    value: str
    confidence: str = "medium"
    source: str = "batch"
    consent_state: str = "allowed"
    principal_id: str | None = None


class MemoryBatchRequest(BaseModel):
    items: list[MemoryBatchItem] = Field(default_factory=list, max_length=50)


def _parse_profile_row(row: ProjectMemoryProfile | None) -> dict | None:
    if row is None:
        return None
    try:
        data = json.loads(row.summary_json)
        return data if isinstance(data, dict) else None
    except Exception:
        logger.warning("could not parse memory profile for project %s", getattr(row, "project_id", "?"), exc_info=True)
        return None


@router.get("/{project_id}")
def list_memory_items(
    project_id: str,
    memory_type: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    q: str | None = Query(default=None, description="Search key or value (substring)"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    event_type: str | None = Query(default=None, description="Filter memory events by type"),
    event_limit: int = Query(default=25, ge=1, le=200),
    event_offset: int = Query(default=0, ge=0),
    include_profile: bool = Query(default=True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    query = select(MemoryItem).where(MemoryItem.project_id == project_id)
    if memory_type:
        query = query.where(MemoryItem.memory_type == memory_type)
    if not include_archived:
        query = query.where(MemoryItem.is_archived.is_(False))
    if q and q.strip():
        pat = f"%{q.strip()}%"
        query = query.where(or_(MemoryItem.key.ilike(pat), MemoryItem.value.ilike(pat)))
    query = query.order_by(MemoryItem.updated_at.desc())
    fetch_n = limit + 1
    rows = db.scalars(query.offset(offset).limit(fetch_n)).all()
    has_more_items = len(rows) > limit
    rows = rows[:limit]

    ev_q = select(MemoryEvent).where(MemoryEvent.project_id == project_id)
    if event_type and event_type.strip():
        ev_q = ev_q.where(MemoryEvent.event_type == event_type.strip())
    ev_q = ev_q.order_by(MemoryEvent.id.desc())
    ev_fetch = event_limit + 1
    ev_rows = db.scalars(ev_q.offset(event_offset).limit(ev_fetch)).all()
    has_more_events = len(ev_rows) > event_limit
    ev_rows = ev_rows[:event_limit]

    profile_out: dict | None = None
    if include_profile:
        prof = db.scalar(select(ProjectMemoryProfile).where(ProjectMemoryProfile.project_id == project_id))
        parsed = _parse_profile_row(prof)
        profile_out = {
            "summary": parsed,
            "updated_at": prof.updated_at.isoformat() if prof and prof.updated_at else None,
        }

    return {
        "project_id": project_id,
        "items": [
            {
                "id": row.id,
                "memory_type": row.memory_type,
                "key": row.key,
                "value": row.value,
                "confidence": row.confidence,
                "source": row.source,
                "consent_state": row.consent_state,
                "principal_id": row.principal_id,
                "is_archived": bool(row.is_archived),
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ],
        "items_has_more": has_more_items,
        "items_limit": limit,
        "items_offset": offset,
        "recent_events": [
            {
                "id": ev.id,
                "run_id": ev.run_id,
                "event_type": ev.event_type,
                "payload": ev.payload,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
            }
            for ev in reversed(ev_rows)
        ],
        "events_has_more": has_more_events,
        "events_limit": event_limit,
        "events_offset": event_offset,
        "project_memory_profile": profile_out,
        "settings": {
            "memory_compaction_v1_enabled": settings.memory_compaction_v1_enabled,
            "memory_respect_consent_in_context": settings.memory_respect_consent_in_context,
            "memory_enforce_consent_ledger": settings.memory_enforce_consent_ledger,
        },
    }


@router.post("/{project_id}")
def create_memory_item(
    project_id: str,
    body: UpsertMemoryItemRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    mem_type = (body.memory_type or "fact").strip()[:32]
    key = (body.key or "").strip()[:128]
    value = (body.value or "").strip()[:5000]
    if not key or not value:
        raise HTTPException(status_code=400, detail="key and value are required")
    existing = db.scalar(
        select(MemoryItem).where(
            MemoryItem.project_id == project_id,
            MemoryItem.memory_type == mem_type,
            MemoryItem.key == key,
        )
    )
    if existing:
        existing.value = value
        existing.confidence = (body.confidence or existing.confidence).strip()[:16]
        existing.source = (body.source or existing.source).strip()[:64]
        existing.consent_state = (body.consent_state or existing.consent_state).strip()[:16]
        if body.principal_id is not None:
            existing.principal_id = body.principal_id.strip()[:128] or None
        existing.is_archived = bool(body.is_archived)
        existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        return {"project_id": project_id, "id": existing.id, "status": "updated"}
    item = MemoryItem(
        id=f"mem_{uuid.uuid4().hex[:10]}",
        project_id=project_id,
        memory_type=mem_type,
        key=key,
        value=value,
        confidence=(body.confidence or "medium").strip()[:16],
        source=(body.source or "chat").strip()[:64],
        consent_state=(body.consent_state or "allowed").strip()[:16],
        principal_id=(body.principal_id.strip()[:128] if body.principal_id else None),
        is_archived=bool(body.is_archived),
    )
    db.add(item)
    db.commit()
    return {"project_id": project_id, "id": item.id, "status": "created"}


@router.post("/{project_id}/batch")
def create_memory_items_batch(
    project_id: str,
    body: MemoryBatchRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not settings.memory_batch_create_enabled:
        raise HTTPException(status_code=404, detail="batch create disabled")
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    if not body.items:
        raise HTTPException(status_code=400, detail="items must not be empty")
    created: list[str] = []
    updated: list[str] = []
    for entry in body.items:
        mem_type = (entry.memory_type or "fact").strip()[:32]
        key = (entry.key or "").strip()[:128]
        value = (entry.value or "").strip()[:5000]
        if not key or not value:
            raise HTTPException(status_code=400, detail="each item requires key and value")
        existing = db.scalar(
            select(MemoryItem).where(
                MemoryItem.project_id == project_id,
                MemoryItem.memory_type == mem_type,
                MemoryItem.key == key,
            )
        )
        if existing:
            existing.value = value
            existing.confidence = (entry.confidence or existing.confidence).strip()[:16]
            existing.source = (entry.source or existing.source).strip()[:64]
            existing.consent_state = (entry.consent_state or existing.consent_state).strip()[:16]
            if entry.principal_id is not None:
                existing.principal_id = entry.principal_id.strip()[:128] or None
            existing.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            updated.append(existing.id)
        else:
            item = MemoryItem(
                id=f"mem_{uuid.uuid4().hex[:10]}",
                project_id=project_id,
                memory_type=mem_type,
                key=key,
                value=value,
                confidence=(entry.confidence or "medium").strip()[:16],
                source=(entry.source or "batch").strip()[:64],
                consent_state=(entry.consent_state or "allowed").strip()[:16],
                principal_id=(entry.principal_id.strip()[:128] if entry.principal_id else None),
                is_archived=False,
            )
            db.add(item)
            created.append(item.id)
    db.commit()
    all_ids = created + updated
    increment("memory_batch_create_total", len(created))
    return {
        "project_id": project_id,
        "ids": all_ids,
        "count": len(all_ids),
        "created": len(created),
        "updated": len(updated),
        "status": "ok",
    }


@router.patch("/{project_id}/{item_id}")
def update_memory_item(
    project_id: str,
    item_id: str,
    body: UpsertMemoryItemRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(MemoryItem).where(MemoryItem.id == item_id, MemoryItem.project_id == project_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Memory item not found")
    row.memory_type = (body.memory_type or row.memory_type).strip()[:32]
    row.key = (body.key or row.key).strip()[:128]
    row.value = (body.value or row.value).strip()[:5000]
    row.confidence = (body.confidence or row.confidence).strip()[:16]
    row.source = (body.source or row.source).strip()[:64]
    row.consent_state = (body.consent_state or row.consent_state).strip()[:16]
    if body.principal_id is not None:
        row.principal_id = body.principal_id.strip()[:128] or None
    row.is_archived = bool(body.is_archived)
    row.updated_at = datetime.now(IST).replace(tzinfo=None)
    db.commit()
    return {"project_id": project_id, "id": item_id, "status": "updated"}


@router.delete("/{project_id}/{item_id}")
def delete_memory_item(
    project_id: str,
    item_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(MemoryItem).where(MemoryItem.id == item_id, MemoryItem.project_id == project_id))
    if row is None:
        return {"project_id": project_id, "id": item_id, "status": "not_found"}
    db.delete(row)
    db.commit()
    return {"project_id": project_id, "id": item_id, "status": "deleted"}
