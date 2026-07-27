"""Model CRUD, scenarios, versions, and dashboard routes."""

import logging
import uuid
from typing import Any

from fastapi import (
    Depends,
    HTTPException,
)
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.db.models import User
from app.db.session import get_db

log = logging.getLogger(__name__)



from app.api.models._router import router  # noqa: F401
from app.api.models._shared import (
    OBSERVABILITY_COUNTERS,
    ModelCreateRequest,
    ModelUpdateRequest,
    ScenarioCreateRequest,
    _emit_model_event,
    _meta_path,
    _model_dir,
    _models_dir,
    _now_iso,
    _read_json,
    _snapshot_version,
    _write_json,
)


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


