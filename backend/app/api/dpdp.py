import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.db.models import ConsentLedger, DPDPRightsRequest, User
from app.db.session import get_db
from app.services.dpdp import update_breach_incident_state
from app.services.storage import workspace_path

logger = logging.getLogger(__name__)

router = APIRouter()


class ConsentRequest(BaseModel):
    principal_id: str
    purpose: str


class RightsRequest(BaseModel):
    project_id: str
    principal_id: str
    request_type: str
    details: str | None = None


class IncidentUpdateRequest(BaseModel):
    state: str
    resolution_notes: str | None = None


@router.get("/{pid}/consent-ledger")
def list_consent_ledger(
    pid: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, _, db)
    rows = db.scalars(
        select(ConsentLedger)
        .where(ConsentLedger.project_id == pid)
        .order_by(ConsentLedger.created_at.desc())
    ).all()
    return {
        "project_id": pid,
        "items": [
            {
                "id": r.id,
                "principal_id": r.principal_id,
                "purpose": r.purpose,
                "granted": bool(r.granted),
                "granted_by": r.granted_by,
                "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/{pid}/consent/{principal_id}")
def get_consent(
    pid: str,
    principal_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, _, db)
    rows = db.scalars(
        select(ConsentLedger).where(ConsentLedger.project_id == pid, ConsentLedger.principal_id == principal_id)
    ).all()
    if not rows:
        return {"project_id": pid, "principal_id": principal_id, "status": "pending"}
    latest = rows[-1]
    return {
        "project_id": pid,
        "principal_id": principal_id,
        "status": "granted" if latest.granted else "revoked",
        "purpose": latest.purpose,
    }


@router.post("/{pid}/consent")
def create_consent(
    pid: str,
    body: ConsentRequest,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, _, db)
    row = ConsentLedger(
        id=f"c_{uuid.uuid4().hex[:10]}",
        project_id=pid,
        principal_id=body.principal_id,
        purpose=body.purpose,
        granted=True,
        granted_by=_.email if isinstance(_, User) else None,
    )
    db.add(row)
    db.commit()
    return {"project_id": pid, "principal_id": body.principal_id, "status": "recorded"}


@router.post("/{pid}/consent/revoke")
def revoke_consent(
    pid: str,
    body: ConsentRequest,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, _, db)
    row = ConsentLedger(
        id=f"c_{uuid.uuid4().hex[:10]}",
        project_id=pid,
        principal_id=body.principal_id,
        purpose=body.purpose,
        granted=False,
        revoked_at=None,
        granted_by=_.email if isinstance(_, User) else None,
    )
    db.add(row)
    db.commit()
    return {"project_id": pid, "principal_id": body.principal_id, "status": "revoked"}


@router.post("/rights")
def create_rights_request(
    body: RightsRequest,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(body.project_id, {"Owner", "Editor"}, _, db)
    row = DPDPRightsRequest(
        id=f"rr_{uuid.uuid4().hex[:10]}",
        project_id=body.project_id,
        principal_id=body.principal_id,
        request_type=body.request_type,
        status="queued",
        details=body.details,
    )
    db.add(row)
    db.commit()
    return {
        "id": row.id,
        "project_id": row.project_id,
        "principal_id": body.principal_id,
        "request_type": body.request_type,
        "status": "queued",
    }


@router.get("/rights")
def list_rights_requests(
    project_id: str,
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, _, db)
    rows = db.scalars(
        select(DPDPRightsRequest)
        .where(DPDPRightsRequest.project_id == project_id)
        .order_by(DPDPRightsRequest.created_at.desc())
    ).all()
    return {
        "project_id": project_id,
        "items": [
            {
                "id": r.id,
                "principal_id": r.principal_id,
                "request_type": r.request_type,
                "status": r.status,
                "details": r.details,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.get("/{pid}/incidents")
def list_incidents(
    pid: str,
    state: str | None = Query(default=None),
    from_ts: str | None = Query(default=None),
    to_ts: str | None = Query(default=None),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, _, db)
    def _parse_ts(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception as exc:
            logger.warning("%s: suppressed error: %s", '_parse_ts', exc)
            return None

    from_dt = _parse_ts(from_ts)
    to_dt = _parse_ts(to_ts)
    incidents_dir = workspace_path(pid) / "dpdp" / "breaches"
    items: list[dict] = []
    if incidents_dir.exists():
        for p in sorted(incidents_dir.glob("*.json"), reverse=True):
            try:
                import json

                payload = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    continue
                if state and str(payload.get("state")) != state:
                    continue
                created_raw = payload.get("created_at")
                created_at = _parse_ts(created_raw) if isinstance(created_raw, str) else None
                if from_dt and created_at and created_at < from_dt:
                    continue
                if to_dt and created_at and created_at > to_dt:
                    continue
                items.append(payload)
            except Exception:  # noqa: S112 — best-effort, non-fatal
                continue
    return {"project_id": pid, "items": items}


@router.post("/{pid}/incidents/{run_id}/state")
def update_incident_state(
    pid: str,
    run_id: str,
    body: IncidentUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    allowed = {"open", "triaged", "investigating", "resolved", "closed"}
    state_value = body.state.strip().lower()
    if state_value not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid state. Allowed: {sorted(allowed)}")
    updated = update_breach_incident_state(
        pid,
        run_id,
        actor=user.email,
        state=state_value,
        resolution_notes=body.resolution_notes,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return {"project_id": pid, "run_id": run_id, "incident": updated}
