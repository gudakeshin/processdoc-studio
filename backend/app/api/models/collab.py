"""Style profile, report generation, collaborative locks, and realtime WebSocket routes."""

import json
import logging
from typing import Any

from fastapi import (
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy.orm import Session

import app.services.excel_lock_service as lock_svc
from app.core.auth import get_current_user, require_project_role
from app.db.models import User
from app.db.session import SessionLocal, get_db
from app.services.email_service import send_email
from app.services.report_generator import generate_report

log = logging.getLogger(__name__)



from app.api.models._router import router  # noqa: F401
from app.api.models._shared import (
    ReportGenerateRequest,
    StyleProfileRequest,
    _model_dir,
    _now_iso,
    _presence_room,
    _websocket_user_from_token,
)

# ---------------------------------------------------------------------------
# Style profile — save / load
# ---------------------------------------------------------------------------

_STYLE_PROFILE_DEFAULTS: dict[str, str] = {
    "formality": "Formal",
    "tone": "Authoritative",
    "persona": "Senior Director",
    "verbosity": "Balanced",
    "audience": "C-suite",
}


@router.get("/projects/{pid}/models/{mid}/style-profile")
def get_style_profile(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    path = _model_dir(pid, mid) / "style_profile.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("%s: suppressed error: %s", 'get_style_profile', exc)
    return dict(_STYLE_PROFILE_DEFAULTS)


@router.put("/projects/{pid}/models/{mid}/style-profile")
def put_style_profile(
    pid: str,
    mid: str,
    body: StyleProfileRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    path = _model_dir(pid, mid) / "style_profile.json"
    path.write_text(json.dumps(body.model_dump(), ensure_ascii=False), encoding="utf-8")
    return body.model_dump()


# ---------------------------------------------------------------------------
# Phase 4a — Report generation
# ---------------------------------------------------------------------------

@router.post("/projects/{pid}/models/{mid}/reports/generate")
def reports_generate(
    pid: str,
    mid: str,
    body: ReportGenerateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    result = generate_report(
        _model_dir(pid, mid),
        report_type=body.reportType,
        fmt=body.format,
        title=body.title,
        include_charts=body.includeCharts,
        include_tables=body.includeTables,
    )
    if result.get("status") == "not_yet_implemented":
        raise HTTPException(status_code=501, detail=result.get("detail", "Report format not implemented"))
    if result.get("status") == "ok" and "filename" in result:
        result["download_path"] = f"/api/projects/{pid}/models/{mid}/reports/download/{result['filename']}"
        if body.recipients.strip():
            report_path = _model_dir(pid, mid) / "reports" / result["filename"]
            outcome = send_email(
                body.recipients.replace(";", ",").split(","),
                subject=body.title,
                body=f"Your financial report '{body.title}' is attached.",
                attachments=[report_path],
            )
            result["emailed"] = bool(outcome.get("sent"))
            result["email_reason"] = outcome.get("reason")
        else:
            result["emailed"] = False
            result["email_reason"] = None
    return result


@router.get("/projects/{pid}/models/{mid}/reports/download/{filename}")
def reports_download(
    pid: str,
    mid: str,
    filename: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Any:
    from fastapi.responses import FileResponse
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    # Sanitize — no path traversal
    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = _model_dir(pid, mid) / "reports" / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(str(path), filename=filename)


# ---------------------------------------------------------------------------
# Phase 4b — Collaborative editing locks (REST + WebSocket)
# ---------------------------------------------------------------------------

@router.get("/projects/{pid}/models/{mid}/collaborative/locks")
def collab_locks_list(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    return {"locks": lock_svc.get_locks(pid, mid)}


@router.delete("/projects/{pid}/models/{mid}/collaborative/locks/{cell_ref}")
def collab_locks_force_release(
    pid: str,
    mid: str,
    cell_ref: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner"}, user, db)
    released = lock_svc.force_release_lock(pid, mid, cell_ref)
    if not released:
        raise HTTPException(status_code=404, detail="Lock not found")
    return {"ok": True}


@router.websocket("/ws/models/{pid}/{mid}/collab")
async def collab_websocket(
    pid: str,
    mid: str,
    ws: WebSocket,
) -> None:
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=1008)
        return
    db = SessionLocal()
    user: User | None = None
    try:
        user = _websocket_user_from_token(token)
        if not user:
            await ws.close(code=1008)
            return
        require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    except Exception:
        await ws.close(code=1008)
        return
    finally:
        db.close()

    await ws.accept()
    q = lock_svc.subscribe(pid, mid)
    user_id = user.email
    presence = _presence_room(pid, mid)
    presence[user_id] = {"email": user_id, "connectedAt": _now_iso(), "cursor": None}
    try:
        await ws.send_json({
            "type": "init",
            "locks": lock_svc.get_locks(pid, mid),
            "presence": list(presence.values()),
        })
        await lock_svc.broadcast(pid, mid, {"type": "presence_update", "presence": list(presence.values())})

        async def _pump() -> None:
            while True:
                msg = await q.get()
                await ws.send_json(msg)

        import asyncio
        pump_task = asyncio.create_task(_pump())
        try:
            while True:
                data = await ws.receive_json()
                action = data.get("action")
                cell_ref = data.get("cellRef", "")
                if action == "lock":
                    result = lock_svc.acquire_lock(pid, mid, cell_ref, user_id)
                    await lock_svc.broadcast(pid, mid, {"type": "lock_update", "locks": lock_svc.get_locks(pid, mid)})
                    await ws.send_json({"type": "lock_result", **result})
                elif action == "release":
                    lock_svc.release_lock(pid, mid, cell_ref, user_id)
                    await lock_svc.broadcast(pid, mid, {"type": "lock_update", "locks": lock_svc.get_locks(pid, mid)})
                elif action == "cursor":
                    presence[user_id]["cursor"] = cell_ref or None
                    await lock_svc.broadcast(pid, mid, {"type": "presence_update", "presence": list(presence.values())})
        finally:
            pump_task.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        presence.pop(user_id, None)
        await lock_svc.broadcast(pid, mid, {"type": "presence_update", "presence": list(presence.values())})
        lock_svc.release_all_locks_for_user(pid, mid, user_id)
        lock_svc.unsubscribe(pid, mid, q)


@router.post("/projects/{pid}/models/{mid}/collaborative/locks/{cell_ref}/acquire")
def collab_lock_acquire(
    pid: str,
    mid: str,
    cell_ref: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    return lock_svc.acquire_lock(pid, mid, cell_ref, user.email)


@router.post("/projects/{pid}/models/{mid}/collaborative/locks/{cell_ref}/release")
def collab_lock_release(
    pid: str,
    mid: str,
    cell_ref: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    released = lock_svc.release_lock(pid, mid, cell_ref, user.email)
    return {"ok": released}


