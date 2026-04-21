"""Conversation-time memory event recording and profile aggregation."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import MemoryEvent, ProjectMemoryProfile, Run


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _normalize_user_profile(summary: dict[str, Any], user_id: str) -> dict[str, Any]:
    users = summary.get("users")
    if not isinstance(users, dict):
        users = {}
        summary["users"] = users
    user_block = users.get(user_id)
    if not isinstance(user_block, dict):
        user_block = {"aggregated_slots": {}, "decision_outcomes": {}, "updated_at": _now_iso()}
        users[user_id] = user_block
    if not isinstance(user_block.get("aggregated_slots"), dict):
        user_block["aggregated_slots"] = {}
    if not isinstance(user_block.get("decision_outcomes"), dict):
        user_block["decision_outcomes"] = {}
    return user_block


def _load_profile(session: Session, *, project_id: str) -> tuple[ProjectMemoryProfile | None, dict[str, Any]]:
    row = session.scalar(select(ProjectMemoryProfile).where(ProjectMemoryProfile.project_id == project_id))
    if row is None or not row.summary_json:
        return row, {}
    try:
        data = json.loads(row.summary_json)
        return row, data if isinstance(data, dict) else {}
    except Exception:
        return row, {}


def _save_profile(session: Session, *, project_id: str, row: ProjectMemoryProfile | None, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, sort_keys=True)
    if row is None:
        session.add(ProjectMemoryProfile(project_id=project_id, summary_json=text))
    else:
        row.summary_json = text
        row.updated_at = datetime.utcnow()
    session.flush()


def _latest_project_run_id(session: Session, *, project_id: str) -> str | None:
    row = session.scalar(
        select(Run.id)
        .where(Run.project_id == project_id)
        .order_by(Run.created_at.desc())
        .limit(1)
    )
    return str(row).strip() if row else None


def _append_event_if_possible(
    session: Session,
    *,
    project_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    run_id = _latest_project_run_id(session, project_id=project_id)
    if not run_id:
        return
    canonical = json.dumps(payload, sort_keys=True)
    fingerprint = hashlib.sha256(f"{project_id}|{run_id}|{event_type}|{canonical}".encode("utf-8")).hexdigest()
    existing = session.scalar(
        select(MemoryEvent).where(
            MemoryEvent.project_id == project_id,
            MemoryEvent.run_id == run_id,
            MemoryEvent.event_type == event_type,
            MemoryEvent.fingerprint == fingerprint,
        )
    )
    if existing:
        return
    session.add(
        MemoryEvent(
            project_id=project_id,
            run_id=run_id,
            event_type=event_type,
            fingerprint=fingerprint,
            payload=canonical,
        )
    )
    session.flush()


def record_discovery_answer(
    session: Session,
    *,
    project_id: str,
    user_id: str,
    slot_key: str,
    value: Any,
) -> None:
    key = str(slot_key or "").strip()
    if not key:
        return
    row, summary = _load_profile(session, project_id=project_id)
    block = _normalize_user_profile(summary, user_id)
    slots = block["aggregated_slots"]
    slots[key] = value
    block["updated_at"] = _now_iso()
    _save_profile(session, project_id=project_id, row=row, payload=summary)
    _append_event_if_possible(
        session,
        project_id=project_id,
        event_type="discovery_answer_recorded",
        payload={"user_id": user_id, "slot_key": key, "value": value},
    )


def record_routing_decision(
    session: Session,
    *,
    project_id: str,
    user_id: str,
    decision_type: str,
    confidence: float,
    outcome: str,
) -> None:
    dkey = str(decision_type or "").strip() or "unknown"
    row, summary = _load_profile(session, project_id=project_id)
    block = _normalize_user_profile(summary, user_id)
    outcomes = block["decision_outcomes"]
    current = outcomes.get(dkey) if isinstance(outcomes.get(dkey), dict) else {}
    count = int(current.get("count", 0)) + 1
    prev_avg = float(current.get("avg_confidence", 0.0))
    avg = ((prev_avg * (count - 1)) + float(confidence)) / max(1, count)
    outcomes[dkey] = {
        "count": count,
        "avg_confidence": round(avg, 4),
        "last_outcome": str(outcome or "").strip()[:200],
        "last_updated_at": _now_iso(),
    }
    block["updated_at"] = _now_iso()
    _save_profile(session, project_id=project_id, row=row, payload=summary)
    _append_event_if_possible(
        session,
        project_id=project_id,
        event_type="routing_decision_recorded",
        payload={
            "user_id": user_id,
            "decision_type": dkey,
            "confidence": float(confidence),
            "outcome": str(outcome or "")[:200],
        },
    )


def get_aggregated_profile(
    session: Session,
    *,
    project_id: str,
    user_id: str,
) -> dict[str, Any]:
    _row, summary = _load_profile(session, project_id=project_id)
    users = summary.get("users")
    if not isinstance(users, dict):
        return {"aggregated_slots": {}, "decision_outcomes": {}}
    block = users.get(user_id)
    if not isinstance(block, dict):
        return {"aggregated_slots": {}, "decision_outcomes": {}}
    slots = block.get("aggregated_slots") if isinstance(block.get("aggregated_slots"), dict) else {}
    decisions = block.get("decision_outcomes") if isinstance(block.get("decision_outcomes"), dict) else {}
    return {"aggregated_slots": slots, "decision_outcomes": decisions}
