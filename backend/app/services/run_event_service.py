"""Dedicated run-event persistence and resume helpers."""

from __future__ import annotations

import json
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RunEvent
from app.services.langfuse_tracing import langfuse_event
from app.services.run_events import build_event_payload, canonical_event_aliases


class RunEventService:
    """Persists run events and exposes event-log resume helpers."""

    def __init__(self, *, publish_event: Callable[[str, int, str, str], None]) -> None:
        self._publish_event = publish_event

    def record_event(
        self,
        session: Session,
        *,
        run_id: str,
        event_type: str,
        payload_obj: Any,
    ) -> RunEvent:
        payload_obj_dict = payload_obj if isinstance(payload_obj, dict) else {"value": payload_obj}
        event_payload = build_event_payload(run_id=run_id, event_type=event_type, payload_obj=payload_obj_dict)
        payload = json.dumps(event_payload)
        ev = RunEvent(run_id=run_id, event_type=event_type, payload=payload)
        session.add(ev)
        session.flush()
        self._publish_event(run_id, ev.id, event_type, payload)
        langfuse_event(
            trace_id=run_id,
            name=f"run_event.{event_type}",
            metadata={"run_id": run_id, "payload": event_payload},
        )
        for alias in canonical_event_aliases(event_type=event_type, payload=payload_obj_dict):
            alias_payload = build_event_payload(run_id=run_id, event_type=alias, payload_obj=payload_obj_dict)
            alias_payload_str = json.dumps(alias_payload)
            alias_ev = RunEvent(run_id=run_id, event_type=alias, payload=alias_payload_str)
            session.add(alias_ev)
            session.flush()
            self._publish_event(run_id, alias_ev.id, alias, alias_payload_str)
        return ev

    @staticmethod
    def _step_status(payload_str: str | None) -> str | None:
        if not payload_str:
            return None
        try:
            obj = json.loads(payload_str)
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        inner = obj.get("payload")
        status = inner.get("status") if isinstance(inner, dict) else obj.get("status")
        return str(status).strip().lower() if status is not None else None

    def has_execution_enqueued_not_started(self, session: Session, *, run_id: str) -> bool:
        rows = session.scalars(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.id.asc())).all()
        seen_enqueued = False
        seen_started = False
        for ev in rows:
            st = self._step_status(ev.payload)
            if st == "execution_enqueued":
                seen_enqueued = True
            elif st == "execution_started":
                seen_started = True
        return seen_enqueued and not seen_started

    def load_resume_state(self, session: Session, *, run_id: str) -> dict[str, Any]:
        rows = session.scalars(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.id.asc())).all()
        if not rows:
            return {"event_count": 0, "last_event_id": 0, "last_step_status": None}
        last_status = None
        by_type: dict[str, int] = {}
        for ev in rows:
            by_type[ev.event_type] = by_type.get(ev.event_type, 0) + 1
            st = self._step_status(ev.payload)
            if st:
                last_status = st
        return {
            "event_count": len(rows),
            "last_event_id": int(rows[-1].id),
            "last_step_status": last_status,
            "event_type_counts": by_type,
        }
