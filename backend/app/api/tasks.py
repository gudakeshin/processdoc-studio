import json
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.db.models import Run, ScheduledTask, ScheduledTaskRun, User
from app.db.session import get_db
from app.services.run_worker import append_run_event

router = APIRouter()


class CreateTaskRequest(BaseModel):
    project_id: str
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


class UpdateTaskRequest(BaseModel):
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


def _next_run_for(trigger_type: str, cadence_minutes: int, run_at: datetime | None) -> datetime | None:
    now = datetime.utcnow()
    if trigger_type == "once":
        return run_at
    minutes = max(1, min(10080, int(cadence_minutes or 60)))
    return now + timedelta(minutes=minutes)


@router.get("/{project_id}")
def list_tasks(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    items = db.scalars(
        select(ScheduledTask).where(ScheduledTask.project_id == project_id).order_by(ScheduledTask.created_at.desc())
    ).all()
    out = []
    for row in items:
        out.append(
            {
                "id": row.id,
                "name": row.name,
                "instruction": row.instruction,
                "status": row.status,
                "trigger_type": row.trigger_type,
                "cadence_minutes": row.cadence_minutes,
                "retry_limit": row.retry_limit,
                "run_at": row.run_at.isoformat() if row.run_at else None,
                "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
                "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
                "last_run_status": row.last_run_status,
                "output_types": json.loads(row.output_types_json or "[]"),
                "output_type_representations": json.loads(row.output_type_representations_json or "{}"),
            }
        )
    return {"project_id": project_id, "items": out}


@router.post("")
def create_task(
    body: CreateTaskRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(body.project_id, {"Owner", "Editor"}, user, db)
    run_at_dt = None
    if body.run_at:
        try:
            run_at_dt = datetime.fromisoformat(body.run_at.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid run_at ISO timestamp")
    task = ScheduledTask(
        id=f"task_{uuid.uuid4().hex[:10]}",
        project_id=body.project_id,
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
    task.next_run_at = _next_run_for(task.trigger_type, task.cadence_minutes, task.run_at)
    db.add(task)
    db.commit()
    return {"project_id": body.project_id, "task_id": task.id, "status": "created"}


@router.patch("/{project_id}/{task_id}")
def update_task(
    project_id: str,
    task_id: str,
    body: UpdateTaskRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.project_id == project_id))
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
    row.next_run_at = _next_run_for(row.trigger_type, row.cadence_minutes, row.run_at) if row.status == "active" else None
    row.updated_at = datetime.utcnow()
    db.commit()
    return {"project_id": project_id, "task_id": task_id, "status": "updated"}


@router.delete("/{project_id}/{task_id}")
def delete_task(
    project_id: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.project_id == project_id))
    if row is None:
        return {"project_id": project_id, "task_id": task_id, "status": "not_found"}
    db.delete(row)
    db.commit()
    return {"project_id": project_id, "task_id": task_id, "status": "deleted"}


@router.post("/{project_id}/{task_id}/run-now")
def run_task_now(
    project_id: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    task = db.scalar(select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.project_id == project_id))
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    plan = {
        "skill_card": "auto_selected",
        "sub_agents": json.loads(task.output_types_json or "[]"),
        "custom_output_types": json.loads(task.custom_output_types_json or "[]"),
        "output_type_representations": json.loads(task.output_type_representations_json or "{}"),
        "scheduled_task_id": task.id,
    }
    run = Run(
        id=run_id,
        project_id=project_id,
        status="plan_ready",
        output_types=task.output_types_json,
        instruction=task.instruction,
        plan_payload=json.dumps(plan),
    )
    db.add(run)
    db.flush()
    append_run_event(db, run_id, "plan_ready", plan)
    append_run_event(db, run_id, "step", {"status": "awaiting_hitl_approval", "source": "scheduled_task"})
    task.last_run_at = datetime.utcnow()
    task.last_run_status = "queued"
    task.next_run_at = _next_run_for(task.trigger_type, task.cadence_minutes, task.run_at) if task.status == "active" else None
    db.add(
        ScheduledTaskRun(
            id=f"str_{uuid.uuid4().hex[:10]}",
            task_id=task.id,
            project_id=project_id,
            run_id=run_id,
            status="plan_ready",
            message="Manual run-now created and awaiting approval",
        )
    )
    db.commit()
    return {"project_id": project_id, "task_id": task_id, "run_id": run_id, "status": "plan_ready"}


@router.get("/{project_id}/{task_id}/runs")
def list_task_runs(
    project_id: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    rows = db.scalars(
        select(ScheduledTaskRun)
        .where(ScheduledTaskRun.project_id == project_id, ScheduledTaskRun.task_id == task_id)
        .order_by(ScheduledTaskRun.created_at.desc())
    ).all()
    return {
        "project_id": project_id,
        "task_id": task_id,
        "items": [
            {
                "id": r.id,
                "run_id": r.run_id,
                "status": r.status,
                "message": r.message,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.post("/{project_id}/{task_id}/pause")
def pause_task(
    project_id: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.project_id == project_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    row.status = "paused"
    row.next_run_at = None
    row.updated_at = datetime.utcnow()
    db.commit()
    return {"project_id": project_id, "task_id": task_id, "status": "paused"}


@router.post("/{project_id}/{task_id}/resume")
def resume_task(
    project_id: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.project_id == project_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    row.status = "active"
    row.next_run_at = _next_run_for(row.trigger_type, row.cadence_minutes, row.run_at)
    row.updated_at = datetime.utcnow()
    db.commit()
    return {"project_id": project_id, "task_id": task_id, "status": "active"}
