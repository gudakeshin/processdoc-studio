import json
import uuid
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.projects._router import router  # shared: see _router.py
from app.core.auth import get_current_user, require_project_role
from app.core.tz import IST
from app.db.models import (
    Run,
    ScheduledTask,
    ScheduledTaskRun,
    User,
)
from app.db.session import get_db
from app.services.run_worker import append_run_event


class ScheduledTaskCreateBody(BaseModel):
    name: str
    instruction: str
    output_types: list[str] = []
    custom_output_types: list[str] = []
    output_type_representations: dict[str, str] = {}
    trigger_type: str = "interval"
    cadence_minutes: int = 60
    run_at: str | None = None
    timezone: str = "UTC"
    retry_limit: int = 3


class ScheduledTaskUpdateBody(BaseModel):
    name: str | None = None
    instruction: str | None = None
    output_types: list[str] | None = None
    custom_output_types: list[str] | None = None
    output_type_representations: dict[str, str] | None = None
    trigger_type: str | None = None
    cadence_minutes: int | None = None
    run_at: str | None = None
    timezone: str | None = None
    retry_limit: int | None = None
    status: str | None = None


@router.get("/{pid}/scheduled-tasks")
def list_scheduled_tasks(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    rows = db.scalars(select(ScheduledTask).where(ScheduledTask.project_id == pid).order_by(ScheduledTask.created_at.desc())).all()
    items: list[dict] = []
    for row in rows:
        items.append(
            {
                "id": row.id,
                "name": row.name,
                "instruction": row.instruction,
                "status": row.status,
                "trigger_type": row.trigger_type,
                "cadence_minutes": row.cadence_minutes,
                "run_at": row.run_at.isoformat() if row.run_at else None,
                "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
                "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
                "last_run_status": row.last_run_status,
                "output_types": json.loads(row.output_types_json or "[]"),
                "custom_output_types": json.loads(row.custom_output_types_json or "[]"),
                "output_type_representations": json.loads(row.output_type_representations_json or "{}"),
            }
        )
    return {"project_id": pid, "items": items}


@router.post("/{pid}/scheduled-tasks")
def create_scheduled_task(
    pid: str,
    body: ScheduledTaskCreateBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    run_at_dt = None
    if body.run_at:
        try:
            run_at_dt = datetime.fromisoformat(body.run_at.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid run_at ISO timestamp") from None
    task = ScheduledTask(
        id=f"task_{uuid.uuid4().hex[:10]}",
        project_id=pid,
        created_by=user.id,
        name=(body.name or "").strip()[:255],
        instruction=(body.instruction or "").strip()[:6000],
        output_types_json=json.dumps(list(dict.fromkeys(body.output_types or []))),
        custom_output_types_json=json.dumps(body.custom_output_types or []),
        output_type_representations_json=json.dumps(body.output_type_representations or {}),
        trigger_type=body.trigger_type if body.trigger_type in {"interval", "once"} else "interval",
        cadence_minutes=max(1, int(body.cadence_minutes or 60)),
        run_at=run_at_dt,
        timezone=(body.timezone or "UTC").strip()[:64],
        retry_limit=max(0, int(body.retry_limit or 3)),
        status="active",
    )
    task.next_run_at = task.run_at if task.trigger_type == "once" else (datetime.now(IST).replace(tzinfo=None) + timedelta(minutes=task.cadence_minutes))
    db.add(task)
    db.commit()
    return {"project_id": pid, "task_id": task.id, "status": "created"}


@router.patch("/{pid}/scheduled-tasks/{task_id}")
def update_scheduled_task(
    pid: str,
    task_id: str,
    body: ScheduledTaskUpdateBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.project_id == pid))
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if body.name is not None:
        row.name = body.name.strip()[:255]
    if body.instruction is not None:
        row.instruction = body.instruction.strip()[:6000]
    if body.output_types is not None:
        row.output_types_json = json.dumps(list(dict.fromkeys(body.output_types)))
    if body.custom_output_types is not None:
        row.custom_output_types_json = json.dumps(body.custom_output_types)
    if body.output_type_representations is not None:
        row.output_type_representations_json = json.dumps(body.output_type_representations)
    if body.trigger_type in {"interval", "once"}:
        row.trigger_type = body.trigger_type
    if body.cadence_minutes is not None:
        row.cadence_minutes = max(1, int(body.cadence_minutes))
    if body.timezone is not None:
        row.timezone = body.timezone.strip()[:64]
    if body.retry_limit is not None:
        row.retry_limit = max(0, int(body.retry_limit))
    if body.status in {"active", "paused", "archived"}:
        row.status = body.status
    if body.run_at is not None:
        row.run_at = datetime.fromisoformat(body.run_at.replace("Z", "+00:00")).replace(tzinfo=None) if body.run_at else None
    row.next_run_at = row.run_at if row.trigger_type == "once" else (datetime.now(IST).replace(tzinfo=None) + timedelta(minutes=row.cadence_minutes))
    if row.status != "active":
        row.next_run_at = None
    row.updated_at = datetime.now(IST).replace(tzinfo=None)
    db.commit()
    return {"project_id": pid, "task_id": task_id, "status": "updated"}


@router.post("/{pid}/scheduled-tasks/{task_id}/pause")
def pause_scheduled_task(
    pid: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.project_id == pid))
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    row.status = "paused"
    row.next_run_at = None
    row.updated_at = datetime.now(IST).replace(tzinfo=None)
    db.commit()
    return {"project_id": pid, "task_id": task_id, "status": "paused"}


@router.post("/{pid}/scheduled-tasks/{task_id}/resume")
def resume_scheduled_task(
    pid: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.project_id == pid))
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    row.status = "active"
    row.next_run_at = row.run_at if row.trigger_type == "once" else (datetime.now(IST).replace(tzinfo=None) + timedelta(minutes=row.cadence_minutes))
    row.updated_at = datetime.now(IST).replace(tzinfo=None)
    db.commit()
    return {"project_id": pid, "task_id": task_id, "status": "active"}


@router.post("/{pid}/scheduled-tasks/{task_id}/run-now")
def run_scheduled_task_now(
    pid: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.project_id == pid))
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    plan = {
        "skill_card": "auto_selected",
        "sub_agents": json.loads(row.output_types_json or "[]"),
        "custom_output_types": json.loads(row.custom_output_types_json or "[]"),
        "output_type_representations": json.loads(row.output_type_representations_json or "{}"),
        "scheduled_task_id": row.id,
    }
    run = Run(
        id=run_id,
        project_id=pid,
        status="plan_ready",
        output_types=row.output_types_json,
        instruction=row.instruction,
        plan_payload=json.dumps(plan),
    )
    db.add(run)
    append_run_event(db, run_id, "scheduled_task.run_started", {"task_id": row.id, "project_id": pid})
    append_run_event(db, run_id, "plan_ready", plan)
    append_run_event(db, run_id, "step", {"status": "awaiting_hitl_approval", "source": "scheduled_task"})
    db.add(
        ScheduledTaskRun(
            id=f"str_{uuid.uuid4().hex[:10]}",
            task_id=row.id,
            project_id=pid,
            run_id=run_id,
            status="plan_ready",
            message="Run-now created and awaiting approval",
        )
    )
    row.last_run_at = datetime.now(IST).replace(tzinfo=None)
    row.last_run_status = "queued"
    row.updated_at = datetime.now(IST).replace(tzinfo=None)
    db.commit()
    return {"project_id": pid, "task_id": task_id, "run_id": run_id, "status": "plan_ready"}


