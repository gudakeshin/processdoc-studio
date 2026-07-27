import json
from datetime import datetime

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.projects._router import router  # shared: see _router.py
from app.core.auth import get_current_user, require_project_role
from app.core.tz import IST
from app.db.models import (
    MemoryItem,
    User,
    UserProjectPreference,
)
from app.db.session import get_db


class UserProjectPreferencesBody(BaseModel):
    """Lines merged into coordinator NonNegotiables (assemble_v2) for this user+project."""

    context_lines: list[str] | None = None
    # Optional counters for future behavioral-learning (v4 §5.1.1); stored opaque in JSON.
    learning_signals: dict[str, int] | None = None


@router.get("/{pid}/me/preferences")
def get_my_project_preferences(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    row = db.scalar(
        select(UserProjectPreference).where(
            UserProjectPreference.user_id == user.id,
            UserProjectPreference.project_id == pid,
        )
    )
    if row is None:
        return {"project_id": pid, "context_lines": [], "learning_signals": {}, "updated_at": None}
    try:
        data = json.loads(row.preferences_json) if row.preferences_json else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    lines = data.get("context_lines")
    ls = data.get("learning_signals")
    return {
        "project_id": pid,
        "context_lines": lines if isinstance(lines, list) else [],
        "learning_signals": ls if isinstance(ls, dict) else {},
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.patch("/{pid}/me/preferences")
def patch_my_project_preferences(
    pid: str,
    body: UserProjectPreferencesBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    row = db.scalar(
        select(UserProjectPreference).where(
            UserProjectPreference.user_id == user.id,
            UserProjectPreference.project_id == pid,
        )
    )
    base: dict = {}
    if row is not None:
        try:
            parsed = json.loads(row.preferences_json) if row.preferences_json else {}
            if isinstance(parsed, dict):
                base = parsed
        except Exception:
            base = {}
    if body.context_lines is not None:
        base["context_lines"] = [str(x).strip() for x in body.context_lines if str(x).strip()][:50]
    if body.learning_signals is not None:
        prev = base.get("learning_signals")
        merged = dict(prev) if isinstance(prev, dict) else {}
        for k, v in body.learning_signals.items():
            if not k or len(str(k)) > 64:
                continue
            try:
                merged[str(k)[:64]] = int(v)
            except (TypeError, ValueError):
                continue
        base["learning_signals"] = merged
    payload = json.dumps(base, sort_keys=True)
    now = datetime.now(IST).replace(tzinfo=None)
    if row is None:
        row = UserProjectPreference(user_id=user.id, project_id=pid, preferences_json=payload, updated_at=now)
        db.add(row)
    else:
        row.preferences_json = payload
        row.updated_at = now
    db.commit()
    return get_my_project_preferences(pid, user, db)


@router.get("/{pid}/admin/team-personalization")
def get_team_personalization_summary(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner"}, user, db)
    total_items = int(
        db.scalar(
            select(func.count())
            .select_from(MemoryItem)
            .where(MemoryItem.project_id == pid, MemoryItem.is_archived.is_(False))
        )
        or 0
    )
    by_type_rows = db.execute(
        select(MemoryItem.memory_type, func.count())
        .where(MemoryItem.project_id == pid, MemoryItem.is_archived.is_(False))
        .group_by(MemoryItem.memory_type)
    ).all()
    by_source_rows = db.execute(
        select(MemoryItem.source, func.count())
        .where(MemoryItem.project_id == pid, MemoryItem.is_archived.is_(False))
        .group_by(MemoryItem.source)
    ).all()
    pref_users = int(
        db.scalar(select(func.count()).select_from(UserProjectPreference).where(UserProjectPreference.project_id == pid))
        or 0
    )
    return {
        "project_id": pid,
        "memory_items_total": total_items,
        "memory_items_by_type": {str(r[0]): int(r[1]) for r in by_type_rows},
        "memory_items_by_source": {str(r[0]): int(r[1]) for r in by_source_rows},
        "users_with_saved_preferences": pref_users,
    }


