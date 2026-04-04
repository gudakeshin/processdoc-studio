import json
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from openpyxl import Workbook
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.core.upload_validation import validate_excel_upload
from app.db.models import User
from app.db.session import get_db
from app.services.storage import ensure_workspace, workspace_path
from app.services.conflict_resolution import (
    create_conflict,
    get_conflict,
    list_conflicts,
    reopen_conflict,
    resolve_conflict,
    unresolved_high_risk_count,
)
from app.services.graph_sync import (
    ensure_cell_ref_map,
    load_checkpoint,
    load_dead_letter,
    queue_local_change,
    replay_dead_letter_item,
    run_graph_sync_tick,
    save_checkpoint,
    simulate_sync_tick,
)
from app.services.model_realtime import append_model_event, broadcast_model_event, replay_model_events
from app.services.observability import increment, observe_latency, snapshot as observability_snapshot
from app.services.xlsx_parser import parse_workbook, quality_gate_failed

router = APIRouter()
OBSERVABILITY_COUNTERS = {
    "models_created": 0,
    "scenarios_created": 0,
    "excel_imports": 0,
    "excel_exports": 0,
    "excel_syncs": 0,
}


def _models_dir(project_id: str) -> Path:
    ensure_workspace(project_id)
    models_dir = workspace_path(project_id) / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir


def _model_dir(project_id: str, model_id: str) -> Path:
    root = _models_dir(project_id) / model_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "scenarios").mkdir(parents=True, exist_ok=True)
    (root / "versions").mkdir(parents=True, exist_ok=True)
    return root


def _meta_path(project_id: str, model_id: str) -> Path:
    return _model_dir(project_id, model_id) / "model.json"


def _excel_dir(project_id: str, model_id: str) -> Path:
    path = _model_dir(project_id, model_id) / "excel"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _emit_model_event(pid: str, mid: str, event_type: str, payload: dict[str, Any]) -> None:
    event = append_model_event(_excel_dir(pid, mid), project_id=pid, model_id=mid, event_type=event_type, payload=payload)
    try:
        import asyncio

        loop = asyncio.get_running_loop()
        loop.create_task(broadcast_model_event(pid, mid, event))
    except RuntimeError:
        # No running loop (e.g. sync test context); event is still persisted for replay.
        pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ModelCreateRequest(BaseModel):
    name: str
    description: str = ""
    assumptions: dict[str, float | int | str | bool] = Field(default_factory=dict)


class ModelUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    assumptions: dict[str, float | int | str | bool] | None = None


class ScenarioCreateRequest(BaseModel):
    name: str
    assumption_overrides: dict[str, float | int | str | bool] = Field(default_factory=dict)


class ConflictDetectRequest(BaseModel):
    sheet: str = "Sheet1"
    cell_ref: str
    base_value: Any = None
    local_value: Any = None
    remote_value: Any = None


class ConflictResolveRequest(BaseModel):
    chosen_side: str = Field(pattern="^(local|remote|policy)$")
    rationale: str | None = None


class ConflictReopenRequest(BaseModel):
    reason: str | None = None


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _snapshot_version(project_id: str, model_id: str, reason: str) -> dict[str, Any]:
    mdir = _model_dir(project_id, model_id)
    meta = _read_json(_meta_path(project_id, model_id), {})
    version_id = f"{model_id}_v_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    payload = {
        "version_id": version_id,
        "created_at": _now_iso(),
        "reason": reason,
        "model": meta,
        "scenarios": _read_json(mdir / "scenarios" / "index.json", []),
    }
    _write_json(mdir / "versions" / f"{version_id}.json", payload)
    return payload


@router.get("/projects/{pid}/models")
def list_models(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    items: list[dict[str, Any]] = []
    for child in sorted(_models_dir(pid).glob("*")):
        if child.is_dir():
            meta = _read_json(child / "model.json", None)
            if isinstance(meta, dict):
                version_count = len(list((child / "versions").glob("*.json")))
                items.append({**meta, "version_count": version_count})
    return {"project_id": pid, "items": items}


@router.post("/projects/{pid}/models")
def create_model(
    pid: str,
    body: ModelCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    model_id = f"model_{uuid.uuid4().hex[:8]}"
    meta = {
        "id": model_id,
        "name": body.name.strip() or "Untitled model",
        "description": body.description,
        "assumptions": body.assumptions,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "created_by": user.email,
        "status": "draft",
    }
    _write_json(_meta_path(pid, model_id), meta)
    _write_json(_model_dir(pid, model_id) / "scenarios" / "index.json", [])
    _snapshot_version(pid, model_id, "create")
    _emit_model_event(pid, model_id, "model_created", {"name": meta["name"]})
    OBSERVABILITY_COUNTERS["models_created"] += 1
    return meta


@router.get("/projects/{pid}/models/{mid}")
def get_model(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    meta = _read_json(_meta_path(pid, mid), None)
    if not isinstance(meta, dict):
        raise HTTPException(status_code=404, detail="Model not found")
    scenarios = _read_json(_model_dir(pid, mid) / "scenarios" / "index.json", [])
    return {"model": meta, "scenarios": scenarios}


@router.put("/projects/{pid}/models/{mid}")
def update_model(
    pid: str,
    mid: str,
    body: ModelUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    meta = _read_json(_meta_path(pid, mid), None)
    if not isinstance(meta, dict):
        raise HTTPException(status_code=404, detail="Model not found")
    if body.name is not None:
        meta["name"] = body.name
    if body.description is not None:
        meta["description"] = body.description
    if body.assumptions is not None:
        meta["assumptions"] = body.assumptions
    meta["updated_at"] = _now_iso()
    _write_json(_meta_path(pid, mid), meta)
    _snapshot_version(pid, mid, "update")
    _emit_model_event(pid, mid, "model_updated", {"name": meta.get("name"), "updated_at": meta.get("updated_at")})
    return meta


@router.get("/projects/{pid}/models/{mid}/scenarios")
def list_scenarios(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    return {"items": _read_json(_model_dir(pid, mid) / "scenarios" / "index.json", [])}


@router.post("/projects/{pid}/models/{mid}/scenarios")
def create_scenario(
    pid: str,
    mid: str,
    body: ScenarioCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    scenarios_path = _model_dir(pid, mid) / "scenarios" / "index.json"
    scenarios = _read_json(scenarios_path, [])
    if not isinstance(scenarios, list):
        scenarios = []
    scenario = {
        "id": f"scn_{uuid.uuid4().hex[:8]}",
        "name": body.name.strip() or "Scenario",
        "assumption_overrides": body.assumption_overrides,
        "created_at": _now_iso(),
        "created_by": user.email,
    }
    scenarios.append(scenario)
    _write_json(scenarios_path, scenarios)
    _snapshot_version(pid, mid, "scenario_create")
    _emit_model_event(pid, mid, "scenario_created", {"scenario_id": scenario["id"], "name": scenario["name"]})
    OBSERVABILITY_COUNTERS["scenarios_created"] += 1
    return scenario


@router.get("/projects/{pid}/models/{mid}/versions")
def list_versions(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    versions: list[dict[str, Any]] = []
    for item in sorted((_model_dir(pid, mid) / "versions").glob("*.json"), reverse=True):
        payload = _read_json(item, None)
        if isinstance(payload, dict):
            versions.append(
                {
                    "version_id": payload.get("version_id"),
                    "created_at": payload.get("created_at"),
                    "reason": payload.get("reason"),
                }
            )
    return {"items": versions}


@router.get("/projects/{pid}/models/{mid}/dashboard")
def get_dashboard(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    model = _read_json(_meta_path(pid, mid), None)
    if not isinstance(model, dict):
        raise HTTPException(status_code=404, detail="Model not found")
    assumptions = model.get("assumptions", {})
    scenarios = _read_json(_model_dir(pid, mid) / "scenarios" / "index.json", [])
    scenario_count = len(scenarios) if isinstance(scenarios, list) else 0
    assumption_count = len(assumptions) if isinstance(assumptions, dict) else 0
    return {
        "kpis": [
            {"id": "scenario_count", "label": "Scenarios", "value": scenario_count},
            {"id": "assumption_count", "label": "Assumptions", "value": assumption_count},
            {"id": "version_count", "label": "Versions", "value": len(list((_model_dir(pid, mid) / "versions").glob('*.json')))},
        ],
        "charts": [
            {
                "id": "scenario_values",
                "type": "bar",
                "title": "Scenario override counts",
                "labels": [s.get("name", "Scenario") for s in scenarios] if isinstance(scenarios, list) else [],
                "datasets": [
                    {
                        "label": "Overrides",
                        "data": [
                            len((s.get("assumption_overrides") or {}).keys())
                            if isinstance(s, dict)
                            else 0
                            for s in (scenarios if isinstance(scenarios, list) else [])
                        ],
                    }
                ],
            }
        ],
        "tables": [
            {
                "id": "assumptions",
                "title": "Assumption values",
                "columns": ["name", "value"],
                "rows": [[k, v] for k, v in assumptions.items()] if isinstance(assumptions, dict) else [],
            }
        ],
    }


@router.post("/projects/{pid}/models/{mid}/excel/import")
async def excel_import(
    pid: str,
    mid: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    started = perf_counter()
    excel_dir = _excel_dir(pid, mid)
    content = await file.read()
    filename = file.filename or f"upload_{uuid.uuid4().hex[:8]}.bin"
    validate_excel_upload(filename, content)
    target = excel_dir / filename
    target.write_bytes(content)

    snapshot = parse_workbook(content=content, filename=filename)
    snapshots_dir = excel_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    _write_json(snapshots_dir / f"{snapshot['snapshot_id']}.json", snapshot)

    quality = snapshot["quality"]
    diagnostics = snapshot["diagnostics"]
    _write_json(
        excel_dir / "last_import.json",
        {
            "filename": filename,
            "bytes": len(content),
            "snapshot_id": snapshot["snapshot_id"],
            "quality": quality,
            "diagnostics": diagnostics,
            "imported_at": _now_iso(),
        },
    )

    if snapshot.get("parser_kind") == "xlsx" and quality_gate_failed(quality):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Workbook parse quality below minimum threshold",
                "snapshot_id": snapshot["snapshot_id"],
                "quality": quality,
                "diagnostics": diagnostics,
            },
        )

    OBSERVABILITY_COUNTERS["excel_imports"] += 1
    increment("excel_import_total")
    observe_latency("excel_import", (perf_counter() - started) * 1000.0)
    _emit_model_event(
        pid,
        mid,
        "excel_imported",
        {"snapshot_id": snapshot["snapshot_id"], "parser_kind": snapshot.get("parser_kind"), "quality": quality},
    )
    return {
        "status": "imported",
        "filename": filename,
        "snapshot_id": snapshot["snapshot_id"],
        "parser_kind": snapshot.get("parser_kind"),
        "quality": quality,
        "diagnostics": diagnostics,
    }


@router.post("/projects/{pid}/models/{mid}/excel/export")
def excel_export(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    started = perf_counter()
    model = _read_json(_meta_path(pid, mid), {})
    assumptions = model.get("assumptions", {}) if isinstance(model, dict) else {}
    wb = Workbook()
    ws = wb.active
    ws.title = "Assumptions"
    ws["A1"] = "name"
    ws["B1"] = "value"
    row = 2
    if isinstance(assumptions, dict):
        for key, value in assumptions.items():
            ws[f"A{row}"] = str(key)
            ws[f"B{row}"] = value
            row += 1
    meta_ws = wb.create_sheet("Metadata")
    meta_ws["A1"] = "model_id"
    meta_ws["B1"] = mid
    meta_ws["A2"] = "generated_at"
    meta_ws["B2"] = _now_iso()
    export_dir = _model_dir(pid, mid) / "excel"
    export_dir.mkdir(parents=True, exist_ok=True)
    fname = f"export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.xlsx"
    out_path = export_dir / fname
    buf = BytesIO()
    wb.save(buf)
    out_path.write_bytes(buf.getvalue())
    OBSERVABILITY_COUNTERS["excel_exports"] += 1
    increment("excel_export_total")
    observe_latency("excel_export", (perf_counter() - started) * 1000.0)
    return {"status": "exported", "file": fname}


@router.post("/projects/{pid}/models/{mid}/excel/sync")
def excel_sync(
    pid: str,
    mid: str,
    mode: str = Form(default="manual"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    started = perf_counter()
    excel_dir = _excel_dir(pid, mid)
    ensure_cell_ref_map(excel_dir)
    request_id = f"req_{uuid.uuid4().hex[:10]}"
    if mode in {"graph-local", "graph-api", "force-fail"}:
        result = run_graph_sync_tick(
            excel_dir=excel_dir,
            mode=mode,
            actor=user.email,
            request_id=request_id,
        )
    else:
        result = simulate_sync_tick(excel_dir=excel_dir, mode=mode, actor=user.email)
    payload = {
        "status": result["status"],
        "mode": mode,
        "synced_at": _now_iso(),
        "request_id": result.get("request_id") or request_id,
        "sync_state": result["checkpoint"]["state"],
        "checkpoint": result["checkpoint"],
        "pull_applied": int(result.get("pull_applied") or 0),
        "pushed": int(result.get("pushed") or 0),
        "idempotent_replay": bool(result.get("idempotent_replay") or False),
        "graph_connected": bool(result.get("graph_connected") or False),
        "conflict_policy": {
            "assumption_cells": "last_write_wins",
            "computed_cells": "processdoc_wins",
        },
        "latency_seconds": 0,
    }
    if result.get("dead_letter_item_id"):
        payload["dead_letter_item_id"] = result["dead_letter_item_id"]
    high_risk_open = unresolved_high_risk_count(excel_dir)
    if high_risk_open > 0:
        payload["status"] = "conflicted"
        payload["sync_state"] = "conflicted"
        payload["high_risk_open_conflicts"] = high_risk_open
        payload["checkpoint"]["state"] = "conflicted"
        save_checkpoint(excel_dir, payload["checkpoint"])
    _write_json(excel_dir / "last_sync.json", payload)
    _emit_model_event(
        pid,
        mid,
        "sync_state_changed",
        {
            "status": payload["status"],
            "sync_state": payload["sync_state"],
            "request_id": payload["request_id"],
            "pull_applied": payload["pull_applied"],
            "pushed": payload["pushed"],
        },
    )
    OBSERVABILITY_COUNTERS["excel_syncs"] += 1
    increment("excel_sync_total")
    increment(f"excel_sync_status_{payload['status']}_total")
    observe_latency("excel_sync", (perf_counter() - started) * 1000.0)
    return payload


@router.post("/projects/{pid}/models/{mid}/excel/sync/queue-local-change")
def excel_sync_queue_local_change(
    pid: str,
    mid: str,
    cell_ref: str = Form(...),
    value: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    excel_dir = _excel_dir(pid, mid)
    item = queue_local_change(excel_dir=excel_dir, cell_ref=cell_ref, value=value, actor=user.email)
    return {"status": "queued", "item": item}


@router.post("/projects/{pid}/models/{mid}/excel/sync/start")
def excel_sync_start(
    pid: str,
    mid: str,
    mode: str = Form(default="polling"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    excel_dir = _excel_dir(pid, mid)
    checkpoint = load_checkpoint(excel_dir)
    checkpoint.update(
        {
            "state": "syncing",
            "mode": mode,
            "started_by": user.email,
            "started_at": _now_iso(),
            "last_error": None,
        }
    )
    save_checkpoint(excel_dir, checkpoint)
    ensure_cell_ref_map(excel_dir)
    return {"status": "started", "checkpoint": checkpoint}


@router.post("/projects/{pid}/models/{mid}/excel/sync/stop")
def excel_sync_stop(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    excel_dir = _excel_dir(pid, mid)
    checkpoint = load_checkpoint(excel_dir)
    checkpoint.update({"state": "idle", "stopped_by": user.email, "stopped_at": _now_iso()})
    save_checkpoint(excel_dir, checkpoint)
    return {"status": "stopped", "checkpoint": checkpoint}


@router.get("/projects/{pid}/models/{mid}/excel/sync/status")
def excel_sync_status(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    excel_dir = _excel_dir(pid, mid)
    checkpoint = load_checkpoint(excel_dir)
    dead_letter = load_dead_letter(excel_dir)
    state = checkpoint.get("state") or "idle"
    high_risk_open = unresolved_high_risk_count(excel_dir)
    if high_risk_open > 0:
        state = "conflicted"
    if state not in {"idle", "syncing", "degraded", "conflicted", "failed"}:
        state = "degraded"
    return {
        "state": state,
        "checkpoint": checkpoint,
        "high_risk_open_conflicts": high_risk_open,
        "dead_letter_count": len(dead_letter),
        "dead_letter_items": dead_letter[-20:],
    }


@router.post("/projects/{pid}/models/{mid}/excel/sync/replay-dead-letter/{item_id}")
def excel_sync_replay_dead_letter(
    pid: str,
    mid: str,
    item_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    excel_dir = _excel_dir(pid, mid)
    item = replay_dead_letter_item(excel_dir, item_id=item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Dead-letter item not found")
    checkpoint = load_checkpoint(excel_dir)
    checkpoint["state"] = "syncing"
    checkpoint["last_error"] = None
    checkpoint["last_replay_item_id"] = item_id
    save_checkpoint(excel_dir, checkpoint)
    return {"status": "replayed", "item": item, "checkpoint": checkpoint}


@router.get("/projects/{pid}/models/{mid}/excel/schema-diff")
def excel_schema_diff(
    pid: str,
    mid: str,
    from_snapshot: str = Query(..., alias="from"),
    to_snapshot: str = Query(..., alias="to"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    snapshots_dir = _excel_dir(pid, mid) / "snapshots"
    from_payload = _read_json(snapshots_dir / f"{from_snapshot}.json", None)
    to_payload = _read_json(snapshots_dir / f"{to_snapshot}.json", None)
    if not isinstance(from_payload, dict) or not isinstance(to_payload, dict):
        raise HTTPException(status_code=404, detail="Snapshot not found")

    def flatten(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
        mapping: dict[str, dict[str, Any]] = {}
        for sheet in snapshot.get("sheets", []):
            sheet_name = str(sheet.get("sheet"))
            for cell in sheet.get("cells", []):
                key = f"{sheet_name}:{cell.get('a1_ref')}"
                mapping[key] = {
                    "semantic_type": cell.get("inference", {}).get("semantic_type"),
                    "role": cell.get("inference", {}).get("role"),
                    "confidence": cell.get("inference", {}).get("confidence"),
                }
        return mapping

    left = flatten(from_payload)
    right = flatten(to_payload)
    added = sorted(k for k in right.keys() if k not in left)
    removed = sorted(k for k in left.keys() if k not in right)
    changed: list[dict[str, Any]] = []
    for key in sorted(k for k in right.keys() if k in left):
        if left[key] != right[key]:
            changed.append({"cell": key, "from": left[key], "to": right[key]})

    return {
        "from_snapshot": from_snapshot,
        "to_snapshot": to_snapshot,
        "summary": {
            "added_cells": len(added),
            "removed_cells": len(removed),
            "changed_cells": len(changed),
        },
        "added": added[:200],
        "removed": removed[:200],
        "changed": changed[:200],
    }


@router.get("/projects/{pid}/models/{mid}/excel/conflicts")
def excel_conflicts_list(
    pid: str,
    mid: str,
    sheet: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    status: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    items = list_conflicts(_excel_dir(pid, mid))
    if sheet:
        items = [x for x in items if str(x.get("sheet")) == sheet]
    if severity:
        items = [x for x in items if str(x.get("severity")) == severity]
    if status:
        items = [x for x in items if str(x.get("status")) == status]
    return {"items": items}


@router.get("/projects/{pid}/models/{mid}/excel/conflicts/{cid}")
def excel_conflicts_get(
    pid: str,
    mid: str,
    cid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    item = get_conflict(_excel_dir(pid, mid), cid)
    if item is None:
        raise HTTPException(status_code=404, detail="Conflict not found")
    return item


@router.post("/projects/{pid}/models/{mid}/excel/conflicts/detect")
def excel_conflicts_detect(
    pid: str,
    mid: str,
    body: ConflictDetectRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    item = create_conflict(
        _excel_dir(pid, mid),
        sheet=body.sheet,
        cell_ref=body.cell_ref,
        base_value=body.base_value,
        local_value=body.local_value,
        remote_value=body.remote_value,
        actor=user.email,
    )
    checkpoint = load_checkpoint(_excel_dir(pid, mid))
    checkpoint["state"] = "conflicted"
    save_checkpoint(_excel_dir(pid, mid), checkpoint)
    _emit_model_event(pid, mid, "conflict_detected", {"conflict_id": item["id"], "type": item["type"], "severity": item["severity"]})
    return item


@router.post("/projects/{pid}/models/{mid}/excel/conflicts/{cid}/resolve")
def excel_conflicts_resolve(
    pid: str,
    mid: str,
    cid: str,
    body: ConflictResolveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    item = resolve_conflict(
        _excel_dir(pid, mid),
        conflict_id=cid,
        actor=user.email,
        chosen_side=body.chosen_side,
        rationale=body.rationale,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Conflict not found")
    if unresolved_high_risk_count(_excel_dir(pid, mid)) == 0:
        checkpoint = load_checkpoint(_excel_dir(pid, mid))
        if checkpoint.get("state") == "conflicted":
            checkpoint["state"] = "idle"
            save_checkpoint(_excel_dir(pid, mid), checkpoint)
    _emit_model_event(pid, mid, "conflict_resolved", {"conflict_id": cid, "chosen_side": body.chosen_side})
    return item


@router.post("/projects/{pid}/models/{mid}/excel/conflicts/{cid}/reopen")
def excel_conflicts_reopen(
    pid: str,
    mid: str,
    cid: str,
    body: ConflictReopenRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    item = reopen_conflict(_excel_dir(pid, mid), conflict_id=cid, actor=user.email, reason=body.reason)
    if item is None:
        raise HTTPException(status_code=404, detail="Conflict not found")
    checkpoint = load_checkpoint(_excel_dir(pid, mid))
    checkpoint["state"] = "conflicted"
    save_checkpoint(_excel_dir(pid, mid), checkpoint)
    _emit_model_event(pid, mid, "conflict_reopened", {"conflict_id": cid})
    return item


@router.get("/projects/{pid}/models/{mid}/events")
def model_events(
    pid: str,
    mid: str,
    after_event_id: int = Query(default=0),
    limit: int = Query(default=200, ge=1, le=1000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    events = replay_model_events(_excel_dir(pid, mid), after_event_id=after_event_id, limit=limit)
    return {"items": events}


@router.get("/models/observability")
def models_observability(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    # Any authenticated user can inspect aggregate model/excel API counters.
    del db
    del user
    return {"counters": OBSERVABILITY_COUNTERS, "runtime": observability_snapshot()}
