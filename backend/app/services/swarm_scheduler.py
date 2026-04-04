"""Scheduler facade: ready tasks from persisted RunTask rows."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RunTask
from app.services.swarm import ready_task_ids


class SwarmScheduler:
    """Pull-model scheduler over the shared task board (DB-backed)."""

    @staticmethod
    def list_run_tasks(session: Session, run_id: str) -> list[RunTask]:
        return list(session.scalars(select(RunTask).where(RunTask.run_id == run_id).order_by(RunTask.created_at.asc())).all())

    @staticmethod
    def ready_task_ids(session: Session, run_id: str) -> list[str]:
        return ready_task_ids(SwarmScheduler.list_run_tasks(session, run_id))
