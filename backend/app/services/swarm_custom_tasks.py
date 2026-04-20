"""Coordinator hook: run queued `RunTask` rows with phase=custom (DAG order)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.db.models import RunTask
from app.db.session import SessionLocal
from app.services.claude import claude_generate, is_claude_enabled

_LOG = logging.getLogger(__name__)

_TERMINAL = {"completed", "failed", "skipped"}


def _deps_satisfied(task: RunTask, by_id: dict[str, RunTask]) -> bool:
    try:
        deps = json.loads(task.depends_on_json or "[]")
    except json.JSONDecodeError:
        deps = []
    if not isinstance(deps, list):
        return False
    for d in deps:
        did = str(d).strip()
        if not did:
            continue
        dep = by_id.get(did)
        if dep is None or dep.status not in _TERMINAL:
            return False
    return True


def execute_custom_swarm_tasks_sync(
    *,
    project_id: str,
    run_id: str,
    emit_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> None:
    if not bool(getattr(settings, "swarm_execute_custom_tasks_enabled", False)):
        return
    if not str(project_id).strip() or not str(run_id).strip():
        return

    db = SessionLocal()
    try:
        max_rounds = 16
        for _ in range(max_rounds):
            tasks = list(db.scalars(select(RunTask).where(RunTask.run_id == run_id)).all())
            by_id = {t.id: t for t in tasks}
            candidates = [
                t
                for t in tasks
                if str(t.phase or "").lower() == "custom"
                and t.status == "queued"
                and _deps_satisfied(t, by_id)
            ]
            if not candidates:
                break
            candidates.sort(key=lambda x: (-int(x.priority or 0), x.created_at or datetime.min))
            t = candidates[0]
            t.status = "in_progress"
            now = datetime.utcnow()
            t.started_at = now
            t.updated_at = now
            db.commit()
            if emit_event:
                emit_event("swarm.custom_task_started", {"task_id": t.id, "title": t.title})
            db.commit()

            summary = ""
            ok = True
            if is_claude_enabled():
                try:
                    summary = (
                        claude_generate(
                            system="You complete short workflow tasks for a document run. Reply concisely.",
                            user=f"Task: {t.title}\n\n{(t.description or '').strip()}\n\n"
                            "Summarize what was done or decided in 2–6 sentences.",
                            max_tokens=1200,
                        )
                        or ""
                    ).strip()
                except Exception as exc:  # noqa: BLE001
                    _LOG.warning("custom swarm task LLM failed %s: %s", t.id, exc)
                    summary = f"error:{exc}"[:800]
                    ok = False
            else:
                summary = "Claude disabled; no LLM execution for this custom task."

            end = datetime.utcnow()
            t.output_json = json.dumps({"summary": summary[:12000]})
            t.updated_at = end
            if ok and summary.startswith("error:"):
                ok = False
            if ok:
                t.status = "completed"
                t.completed_at = end
                if t.started_at:
                    t.duration_ms = int((t.completed_at - t.started_at).total_seconds() * 1000)
            else:
                t.status = "failed"
                t.completed_at = end
            db.commit()
            if emit_event:
                emit_event(
                    "swarm.custom_task_completed",
                    {"task_id": t.id, "status": t.status, "summary_excerpt": summary[:240]},
                )
            db.commit()
    finally:
        db.close()
