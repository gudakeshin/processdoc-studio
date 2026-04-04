from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RunTask

TERMINAL_STATUSES = {"completed", "failed", "skipped"}


def _phase_for_task(task_id: str) -> str:
    tid = str(task_id or "").strip().lower()
    if tid in {"context", "process_model"}:
        return "observe"
    if tid in {"plan"}:
        return "plan"
    if tid.startswith("out:"):
        return "act"
    return "report"


def _map_status(status: str) -> str:
    raw = str(status or "").strip().lower()
    if raw == "pending":
        return "queued"
    if raw == "running":
        return "in_progress"
    if raw == "done":
        return "completed"
    if raw in {"failed", "skipped", "blocked", "queued", "in_progress", "completed"}:
        return raw
    return "queued"


def sync_run_tasks_from_snapshot(
    session: Session,
    *,
    project_id: str,
    run_id: str,
    todos: list[dict[str, Any]],
    swarm_team_id: str | None = None,
) -> list[dict[str, Any]]:
    now = datetime.utcnow()
    existing = session.scalars(select(RunTask).where(RunTask.run_id == run_id)).all()
    by_id = {row.id: row for row in existing}
    out: list[dict[str, Any]] = []

    for row in todos:
        tid = str(row.get("id") or "").strip()
        if not tid:
            continue
        status = _map_status(str(row.get("status") or "queued"))
        deps_raw = row.get("depends_on")
        dep_json = (
            json.dumps([str(x) for x in deps_raw])
            if isinstance(deps_raw, list)
            else None
        )
        item = by_id.get(tid)
        if item is None:
            item = RunTask(
                id=tid,
                run_id=run_id,
                project_id=project_id,
                title=str(row.get("label") or tid),
                phase=_phase_for_task(tid),
                status=status,
                depends_on_json=dep_json if dep_json is not None else "[]",
                swarm_team_id=swarm_team_id,
                created_at=now,
                updated_at=now,
            )
            if status == "in_progress":
                item.started_at = now
            if status in TERMINAL_STATUSES:
                item.completed_at = now
            session.add(item)
            event_name = "task.started" if status == "in_progress" else ("task.completed" if status == "completed" else "task.blocked" if status == "blocked" else None)
            out.append(
                {
                    "event": event_name,
                    "task_id": tid,
                    "title": item.title,
                    "status": status,
                    "phase": item.phase,
                }
            )
            continue

        prev = item.status
        item.title = str(row.get("label") or item.title)
        item.updated_at = now
        item.phase = _phase_for_task(tid)
        item.status = status
        if dep_json is not None:
            item.depends_on_json = dep_json
        if swarm_team_id and getattr(item, "swarm_team_id", None) is None:
            item.swarm_team_id = swarm_team_id
        if prev != "in_progress" and status == "in_progress" and item.started_at is None:
            item.started_at = now
            out.append({"event": "task.started", "task_id": tid, "title": item.title, "status": status, "phase": item.phase})
        if prev != status and status == "completed":
            item.completed_at = now
            if item.started_at:
                item.duration_ms = int((item.completed_at - item.started_at).total_seconds() * 1000)
            out.append({"event": "task.completed", "task_id": tid, "title": item.title, "status": status, "phase": item.phase, "duration_ms": item.duration_ms})
        elif prev != status and status == "failed":
            item.completed_at = now
            out.append({"event": "task.failed", "task_id": tid, "title": item.title, "status": status, "phase": item.phase})
        elif prev != status and status == "blocked":
            out.append({"event": "task.blocked", "task_id": tid, "title": item.title, "status": status, "phase": item.phase})
        elif prev != status and status == "skipped":
            item.completed_at = now
            out.append({"event": "task.skipped", "task_id": tid, "title": item.title, "status": status, "phase": item.phase})
        elif status == "in_progress":
            out.append({"event": "task.progress", "task_id": tid, "title": item.title, "status": status, "phase": item.phase})

    session.flush()
    return out


def serialize_run_task(row: RunTask) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "description": row.description,
        "status": row.status,
        "phase": row.phase,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "duration_ms": row.duration_ms,
        "swarm_team_id": getattr(row, "swarm_team_id", None),
        "assigned_teammate_id": getattr(row, "assigned_teammate_id", None),
        "priority": int(getattr(row, "priority", 0) or 0),
        "depends_on": json.loads(row.depends_on_json or "[]"),
        "skills_used": json.loads(row.skills_used_json or "[]"),
        "tools_invoked": json.loads(row.tools_invoked_json or "[]"),
        "output": json.loads(row.output_json or "{}"),
        "blocked_reason": row.blocked_reason,
        "requires_approval": bool(row.requires_approval),
        "retry_count": int(row.retry_count or 0),
        "estimated_duration_sec": row.estimated_duration_sec,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
