"""Swarm orchestration HTTP API (task board, teammates, messaging)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from app.core.tz import IST

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.core.config import settings
from app.db.models import Run, RunTask, User
from app.db.session import get_db
from app.services.observability import increment
from app.services.run_tasks import serialize_run_task, validate_task_status_transition
from app.services.run_worker import append_run_event
from app.services.swarm import (
    ensure_swarm_team,
    lead_plan_with_optional_llm,
    list_swarm_messages,
    list_teammates,
    send_swarm_message,
    serialize_message,
    validate_task_dag,
)
from app.services.swarm_scheduler import SwarmScheduler

router = APIRouter()


def _swarm_enabled() -> None:
    if not bool(getattr(settings, "swarm_orchestration_enabled", False)):
        raise HTTPException(status_code=403, detail="Swarm orchestration is disabled (set SWARM_ORCHESTRATION_ENABLED=true)")


class SwarmCreateTaskBody(BaseModel):
    id: str | None = Field(default=None, description="Stable task id (default: generated)")
    title: str
    description: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    phase: str = "act"
    assigned_teammate_id: str | None = None
    priority: int = 0


class SwarmPatchTaskBody(BaseModel):
    status: str | None = None
    blocked_reason: str | None = None
    assigned_teammate_id: str | None = None
    priority: int | None = None


class SwarmMessageBody(BaseModel):
    from_teammate: str
    body: str
    to_teammate: str | None = None
    correlation_id: str | None = None


class SwarmBroadcastBody(BaseModel):
    from_teammate: str
    body: str


@router.get("/{project_id}/{run_id}/swarm")
def swarm_summary(
    project_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    _swarm_enabled()
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    team = ensure_swarm_team(db, project_id=project_id, run_id=run_id)
    mates = list_teammates(db, run_id=run_id)
    ready = SwarmScheduler.ready_task_ids(db, run_id)
    increment("swarm_summary_total")
    return {
        "run_id": run_id,
        "team": {"id": team.id, "name": team.name, "status": team.status},
        "teammates": [
            {"id": m.id, "teammate_id": m.teammate_id, "role": m.role, "status": m.status} for m in mates
        ],
        "ready_task_ids": ready,
    }


@router.get("/{project_id}/{run_id}/swarm/tasks")
def swarm_list_tasks(
    project_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    status: str | None = Query(default=None, description="Filter by task status"),
    phase: str | None = Query(default=None, description="Filter by phase"),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    _swarm_enabled()
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    rows = SwarmScheduler.list_run_tasks(db, run_id)
    st_filter = (status or "").strip().lower() or None
    ph_filter = (phase or "").strip().lower() or None
    out: list[dict] = []
    for t in rows:
        if st_filter and str(t.status or "").lower() != st_filter:
            continue
        if ph_filter and str(t.phase or "").lower() != ph_filter:
            continue
        out.append(serialize_run_task(t))
    increment("swarm_task_list_total")
    return {"run_id": run_id, "items": out}


@router.get("/{project_id}/{run_id}/swarm/tasks/ready")
def swarm_ready_tasks(
    project_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    _swarm_enabled()
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {"run_id": run_id, "ready_task_ids": SwarmScheduler.ready_task_ids(db, run_id)}


@router.post("/{project_id}/{run_id}/swarm/tasks")
def swarm_create_task(
    project_id: str,
    run_id: str,
    body: SwarmCreateTaskBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    _swarm_enabled()
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    team = ensure_swarm_team(db, project_id=project_id, run_id=run_id)
    tid = (body.id or "").strip() or uuid.uuid4().hex[:16]
    existing = db.scalar(select(RunTask).where(RunTask.id == tid, RunTask.run_id == run_id))
    if existing:
        raise HTTPException(status_code=409, detail="Task id already exists")
    all_tasks = SwarmScheduler.list_run_tasks(db, run_id)
    id_set = {t.id for t in all_tasks} | {tid}
    depends_map = {t.id: json.loads(t.depends_on_json or "[]") for t in all_tasks}
    depends_map[tid] = list(body.depends_on)
    try:
        validate_task_dag(id_set, depends_map)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.now(IST).replace(tzinfo=None)
    row = RunTask(
        id=tid,
        run_id=run_id,
        project_id=project_id,
        title=body.title.strip(),
        description=body.description,
        phase=body.phase[:16],
        status="queued",
        depends_on_json=json.dumps(body.depends_on),
        swarm_team_id=team.id,
        assigned_teammate_id=body.assigned_teammate_id,
        priority=int(body.priority),
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    increment("swarm_task_create_total")
    append_run_event(db, run_id, "swarm.task_created", {"task_id": tid, "title": row.title})
    db.commit()
    db.refresh(row)
    return {"task": serialize_run_task(row)}


@router.patch("/{project_id}/{run_id}/swarm/tasks/{task_id}")
def swarm_patch_task(
    project_id: str,
    run_id: str,
    task_id: str,
    body: SwarmPatchTaskBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    _swarm_enabled()
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    task = db.scalar(select(RunTask).where(RunTask.id == task_id, RunTask.run_id == run_id))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if body.status is not None:
        # Validate status transition
        new_status = body.status[:16]
        is_valid, error_msg = validate_task_status_transition(task.status, new_status)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error_msg)
        task.status = new_status
    if body.blocked_reason is not None:
        task.blocked_reason = body.blocked_reason
    if body.assigned_teammate_id is not None:
        task.assigned_teammate_id = body.assigned_teammate_id or None
    if body.priority is not None:
        task.priority = int(body.priority)
    task.updated_at = datetime.now(IST).replace(tzinfo=None)
    db.flush()
    increment("swarm_task_patch_total")
    append_run_event(db, run_id, "swarm.task_updated", {"task_id": task_id, "status": task.status})
    db.commit()
    db.refresh(task)
    return {"task": serialize_run_task(task)}


@router.get("/{project_id}/{run_id}/swarm/messages")
def swarm_list_messages(
    project_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    _swarm_enabled()
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    rows = list_swarm_messages(db, run_id=run_id)
    return {"run_id": run_id, "items": [serialize_message(m) for m in reversed(rows)]}


@router.post("/{project_id}/{run_id}/swarm/messages")
def swarm_post_message(
    project_id: str,
    run_id: str,
    body: SwarmMessageBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    _swarm_enabled()
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    team = ensure_swarm_team(db, project_id=project_id, run_id=run_id)
    msg = send_swarm_message(
        db,
        run_id=run_id,
        project_id=project_id,
        from_teammate=body.from_teammate.strip(),
        body=body.body,
        to_teammate=body.to_teammate.strip() if body.to_teammate else None,
        team_id=team.id,
        correlation_id=body.correlation_id,
    )
    increment("swarm_message_total")
    payload = serialize_message(msg)
    append_run_event(db, run_id, "swarm_message", payload)
    db.commit()
    db.refresh(msg)
    return {"message": payload}


@router.post("/{project_id}/{run_id}/swarm/broadcast")
def swarm_broadcast(
    project_id: str,
    run_id: str,
    body: SwarmBroadcastBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    _swarm_enabled()
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    team = ensure_swarm_team(db, project_id=project_id, run_id=run_id)
    msg = send_swarm_message(
        db,
        run_id=run_id,
        project_id=project_id,
        from_teammate=body.from_teammate.strip(),
        body=body.body,
        to_teammate=None,
        team_id=team.id,
    )
    increment("swarm_broadcast_total")
    payload = serialize_message(msg)
    append_run_event(db, run_id, "swarm_message", {**payload, "broadcast": True})
    db.commit()
    db.refresh(msg)
    return {"message": payload}


@router.get("/{project_id}/{run_id}/swarm/lead/plan-preview")
def swarm_lead_plan_preview(
    project_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Deterministic task graph the lead would materialize from this run's output types."""
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    _swarm_enabled()
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        wanted = json.loads(run.output_types or "[]")
    except json.JSONDecodeError:
        wanted = []
    if not isinstance(wanted, list):
        wanted = []
    plan = lead_plan_with_optional_llm(wanted=[str(x) for x in wanted])
    increment("swarm_lead_preview_total")
    return {
        "run_id": run_id,
        "rationale": plan.rationale,
        "used_llm": plan.used_llm,
        "tasks": plan.tasks,
    }
