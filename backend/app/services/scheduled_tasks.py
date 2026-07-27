from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timedelta
from app.core.tz import IST

from sqlalchemy import select

from app.db.models import Run, ScheduledTask, ScheduledTaskRun
from app.db.session import SessionLocal
from app.services.observability import increment
from app.services.run_worker import append_run_event

_started = False
_lock = threading.Lock()


def _compute_next(task: ScheduledTask) -> datetime | None:
    if task.status != "active":
        return None
    if task.trigger_type == "once":
        return None
    minutes = max(1, int(task.cadence_minutes or 60))
    return datetime.now(IST).replace(tzinfo=None) + timedelta(minutes=minutes)


def _tick() -> None:
    session = SessionLocal()
    now = datetime.now(IST).replace(tzinfo=None)
    try:
        due_tasks = session.scalars(
            select(ScheduledTask).where(
                ScheduledTask.status == "active",
                ScheduledTask.next_run_at.is_not(None),
                ScheduledTask.next_run_at <= now,
            )
        ).all()
        for task in due_tasks:
            recent_runs = session.scalars(
                select(ScheduledTaskRun)
                .where(ScheduledTaskRun.task_id == task.id)
                .order_by(ScheduledTaskRun.created_at.desc())
                .limit(max(1, int(task.retry_limit or 0)))
            ).all()
            consecutive_failures = 0
            for rr in recent_runs:
                if str(rr.status or "").lower() in {"dispatch_failed", "failed"}:
                    consecutive_failures += 1
                else:
                    break
            if task.retry_limit and consecutive_failures >= int(task.retry_limit):
                task.status = "paused"
                task.last_run_status = "paused_after_retries_exhausted"
                task.next_run_at = None
                session.add(
                    ScheduledTaskRun(
                        id=f"str_{uuid.uuid4().hex[:10]}",
                        task_id=task.id,
                        project_id=task.project_id,
                        run_id=None,
                        status="dispatch_failed",
                        message="Task paused after exhausting retry_limit on prior dispatches",
                    )
                )
                increment("scheduled_task_dispatch_fail_total")
                continue

            plan = {
                "skill_card": "auto_selected",
                "sub_agents": json.loads(task.output_types_json or "[]"),
                "custom_output_types": json.loads(task.custom_output_types_json or "[]"),
                "output_type_representations": json.loads(task.output_type_representations_json or "{}"),
                "scheduled_task_id": task.id,
            }
            run_id = f"run_{uuid.uuid4().hex[:10]}"
            run = Run(
                id=run_id,
                project_id=task.project_id,
                status="plan_ready",
                output_types=task.output_types_json,
                instruction=task.instruction,
                plan_payload=json.dumps(plan),
            )
            session.add(run)
            session.flush()
            append_run_event(session, run.id, "plan_ready", plan)
            append_run_event(session, run.id, "step", {"status": "awaiting_hitl_approval", "source": "scheduler"})
            session.add(
                ScheduledTaskRun(
                    id=f"str_{uuid.uuid4().hex[:10]}",
                    task_id=task.id,
                    project_id=task.project_id,
                    run_id=run.id,
                    status="plan_ready",
                    message="Scheduled run created and awaiting approval (attempt 1)",
                )
            )
            task.last_run_at = datetime.now(IST).replace(tzinfo=None)
            task.last_run_status = "queued"
            task.next_run_at = _compute_next(task)
            increment("scheduled_task_dispatch_total")
        session.commit()
    finally:
        session.close()


def _loop() -> None:
    while True:
        try:
            _tick()
        except Exception:
            increment("scheduled_task_dispatch_fail_total")
        time.sleep(10.0)


def start_scheduler_worker() -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True
        threading.Thread(target=_loop, daemon=True).start()
