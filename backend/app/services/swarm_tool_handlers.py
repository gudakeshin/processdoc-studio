"""Registry tool handlers for swarm task board and messaging (TeammateTool analogue)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.db.models import Run, RunTask
from app.db.session import SessionLocal
from app.services.run_tasks import serialize_run_task
from app.services.swarm import (
    ensure_swarm_team,
    list_swarm_messages,
    send_swarm_message,
    serialize_message,
    validate_task_dag,
)
from app.services.swarm_scheduler import SwarmScheduler


def _swarm_gate() -> str | None:
    if not bool(getattr(settings, "swarm_orchestration_enabled", False)):
        return "Swarm orchestration is disabled"
    return None


def _run_and_project_ok(session: Any, *, project_id: str, run_id: str) -> str | None:
    run = session.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        return "Run not found"
    return None


def swarm_list_tasks(*_: Any, **kwargs: Any) -> dict[str, Any]:
    err = _swarm_gate()
    if err:
        return {"ok": False, "error": err}
    project_id = str(kwargs.get("project_id") or "")
    run_id = str(kwargs.get("run_id") or "")
    if not project_id or not run_id:
        return {"ok": False, "error": "project_id and run_id are required"}
    st = kwargs.get("status")
    ph = kwargs.get("phase")
    st_filter = str(st).strip().lower() if st is not None and str(st).strip() else None
    ph_filter = str(ph).strip().lower() if ph is not None and str(ph).strip() else None
    db = SessionLocal()
    try:
        bad = _run_and_project_ok(db, project_id=project_id, run_id=run_id)
        if bad:
            return {"ok": False, "error": bad}
        rows = SwarmScheduler.list_run_tasks(db, run_id)
        out: list[dict[str, Any]] = []
        for t in rows:
            if st_filter and str(t.status or "").lower() != st_filter:
                continue
            if ph_filter and str(t.phase or "").lower() != ph_filter:
                continue
            out.append(serialize_run_task(t))
        return {"ok": True, "items": out}
    finally:
        db.close()


def swarm_create_task(*_: Any, **kwargs: Any) -> dict[str, Any]:
    from app.services.run_worker import append_run_event

    err = _swarm_gate()
    if err:
        return {"ok": False, "error": err}
    project_id = str(kwargs.get("project_id") or "")
    run_id = str(kwargs.get("run_id") or "")
    title = str(kwargs.get("title") or "").strip()
    if not project_id or not run_id:
        return {"ok": False, "error": "project_id and run_id are required"}
    if not title:
        return {"ok": False, "error": "title is required"}
    description = kwargs.get("description")
    desc_val = None if description is None else str(description)
    depends_raw = kwargs.get("depends_on") or []
    if isinstance(depends_raw, list):
        depends_on = [str(x).strip() for x in depends_raw if str(x).strip()]
    else:
        depends_on = []
    phase = str(kwargs.get("phase") or "act")[:16]
    assigned = kwargs.get("assigned_teammate_id")
    assign_val = None if assigned is None or str(assigned).strip() == "" else str(assigned).strip()
    priority = int(kwargs.get("priority") or 0)
    tid = str(kwargs.get("task_id") or kwargs.get("id") or "").strip() or uuid.uuid4().hex[:16]

    db = SessionLocal()
    try:
        bad = _run_and_project_ok(db, project_id=project_id, run_id=run_id)
        if bad:
            return {"ok": False, "error": bad}
        team = ensure_swarm_team(db, project_id=project_id, run_id=run_id)
        existing = db.scalar(select(RunTask).where(RunTask.id == tid, RunTask.run_id == run_id))
        if existing:
            return {"ok": False, "error": f"Task id {tid!r} already exists"}
        all_tasks = SwarmScheduler.list_run_tasks(db, run_id)
        id_set = {t.id for t in all_tasks} | {tid}
        depends_map = {t.id: json.loads(t.depends_on_json or "[]") for t in all_tasks}
        depends_map[tid] = list(depends_on)
        try:
            validate_task_dag(id_set, depends_map)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        now = datetime.utcnow()
        row = RunTask(
            id=tid,
            run_id=run_id,
            project_id=project_id,
            title=title,
            description=desc_val,
            phase=phase,
            status="queued",
            depends_on_json=json.dumps(depends_on),
            swarm_team_id=team.id,
            assigned_teammate_id=assign_val,
            priority=priority,
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.flush()
        append_run_event(db, run_id, "swarm.task_created", {"task_id": tid, "title": row.title})
        db.commit()
        db.refresh(row)
        return {"ok": True, "task": serialize_run_task(row)}
    finally:
        db.close()


def swarm_update_task(*_: Any, **kwargs: Any) -> dict[str, Any]:
    from app.services.run_worker import append_run_event

    err = _swarm_gate()
    if err:
        return {"ok": False, "error": err}
    project_id = str(kwargs.get("project_id") or "")
    run_id = str(kwargs.get("run_id") or "")
    task_id = str(kwargs.get("task_id") or "").strip()
    if not project_id or not run_id or not task_id:
        return {"ok": False, "error": "project_id, run_id, and task_id are required"}
    db = SessionLocal()
    try:
        bad = _run_and_project_ok(db, project_id=project_id, run_id=run_id)
        if bad:
            return {"ok": False, "error": bad}
        task = db.scalar(select(RunTask).where(RunTask.id == task_id, RunTask.run_id == run_id))
        if not task:
            return {"ok": False, "error": "Task not found"}
        if kwargs.get("status") is not None:
            task.status = str(kwargs.get("status") or "")[:16]
        if kwargs.get("blocked_reason") is not None:
            task.blocked_reason = str(kwargs.get("blocked_reason") or "")
        if kwargs.get("assigned_teammate_id") is not None:
            raw = kwargs.get("assigned_teammate_id")
            task.assigned_teammate_id = None if raw is None or str(raw).strip() == "" else str(raw).strip()
        if kwargs.get("priority") is not None:
            task.priority = int(kwargs.get("priority") or 0)
        task.updated_at = datetime.utcnow()
        db.flush()
        append_run_event(db, run_id, "swarm.task_updated", {"task_id": task_id, "status": task.status})
        db.commit()
        db.refresh(task)
        return {"ok": True, "task": serialize_run_task(task)}
    finally:
        db.close()


def swarm_list_messages(*_: Any, **kwargs: Any) -> dict[str, Any]:
    err = _swarm_gate()
    if err:
        return {"ok": False, "error": err}
    project_id = str(kwargs.get("project_id") or "")
    run_id = str(kwargs.get("run_id") or "")
    if not project_id or not run_id:
        return {"ok": False, "error": "project_id and run_id are required"}
    limit = int(kwargs.get("limit") or 50)
    limit = max(1, min(limit, 200))
    db = SessionLocal()
    try:
        bad = _run_and_project_ok(db, project_id=project_id, run_id=run_id)
        if bad:
            return {"ok": False, "error": bad}
        rows = list_swarm_messages(db, run_id=run_id, limit=limit)
        items = [serialize_message(m) for m in reversed(rows)]
        return {"ok": True, "items": items}
    finally:
        db.close()


def swarm_send_message(*_: Any, **kwargs: Any) -> dict[str, Any]:
    from app.services.run_worker import append_run_event

    err = _swarm_gate()
    if err:
        return {"ok": False, "error": err}
    project_id = str(kwargs.get("project_id") or "")
    run_id = str(kwargs.get("run_id") or "")
    from_teammate = str(kwargs.get("from_teammate") or "").strip()
    body = str(kwargs.get("body") or "").strip()
    if not project_id or not run_id:
        return {"ok": False, "error": "project_id and run_id are required"}
    if not from_teammate or not body:
        return {"ok": False, "error": "from_teammate and body are required"}
    to_raw = kwargs.get("to_teammate")
    to_teammate = None if to_raw is None or str(to_raw).strip() == "" else str(to_raw).strip()
    correlation_id = kwargs.get("correlation_id")
    corr = None if correlation_id is None else str(correlation_id)[:64]

    db = SessionLocal()
    try:
        bad = _run_and_project_ok(db, project_id=project_id, run_id=run_id)
        if bad:
            return {"ok": False, "error": bad}
        team = ensure_swarm_team(db, project_id=project_id, run_id=run_id)
        msg = send_swarm_message(
            db,
            run_id=run_id,
            project_id=project_id,
            from_teammate=from_teammate,
            body=body,
            to_teammate=to_teammate,
            team_id=team.id,
            correlation_id=corr,
        )
        payload = serialize_message(msg)
        append_run_event(db, run_id, "swarm_message", payload)
        db.commit()
        db.refresh(msg)
        return {"ok": True, "message": payload}
    finally:
        db.close()


def swarm_broadcast(*_: Any, **kwargs: Any) -> dict[str, Any]:
    from app.services.run_worker import append_run_event

    err = _swarm_gate()
    if err:
        return {"ok": False, "error": err}
    project_id = str(kwargs.get("project_id") or "")
    run_id = str(kwargs.get("run_id") or "")
    from_teammate = str(kwargs.get("from_teammate") or "").strip()
    body = str(kwargs.get("body") or "").strip()
    if not project_id or not run_id:
        return {"ok": False, "error": "project_id and run_id are required"}
    if not from_teammate or not body:
        return {"ok": False, "error": "from_teammate and body are required"}
    db = SessionLocal()
    try:
        bad = _run_and_project_ok(db, project_id=project_id, run_id=run_id)
        if bad:
            return {"ok": False, "error": bad}
        team = ensure_swarm_team(db, project_id=project_id, run_id=run_id)
        msg = send_swarm_message(
            db,
            run_id=run_id,
            project_id=project_id,
            from_teammate=from_teammate,
            body=body,
            to_teammate=None,
            team_id=team.id,
        )
        payload = serialize_message(msg)
        append_run_event(db, run_id, "swarm_message", {**payload, "broadcast": True})
        db.commit()
        db.refresh(msg)
        return {"ok": True, "message": payload}
    finally:
        db.close()
