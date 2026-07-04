"""Model links, external data connectors, budget-vs-actual, and observability routes."""

import logging
from typing import Any

from fastapi import (
    Depends,
    HTTPException,
    Query,
)
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.db.models import User
from app.db.session import get_db
from app.services.budget_vs_actual import (
    calculate_period_variance,
    calculate_ytd_variance,
    create_budget_setup,
    forecast_full_year,
    generate_budget_vs_actual_report,
    record_actual_results,
)
from app.services.financial_data_connector import (
    build_data_lineage_graph,
    create_data_source_connector,
    detect_data_drift,
    get_data_lineage,
    list_data_sources,
    sync_data_source,
)
from app.services.model_links import (
    build_model_dependency_graph,
    create_model_link,
    get_link_impact,
    list_model_links,
    resolve_cell_reference,
    sync_linked_cells,
    validate_all_links,
)
from app.services.model_realtime import append_model_event
from app.services.observability import snapshot as observability_snapshot

log = logging.getLogger(__name__)



from app.api.models._router import router  # noqa: F401
from app.api.models._shared import (
    OBSERVABILITY_COUNTERS,
    CreateBudgetSetupRequest,
    CreateDataSourceConnectorRequest,
    CreateModelLinkRequest,
    GenerateBudgetReportRequest,
    RecordActualResultsRequest,
    ResolveCellReferenceRequest,
    SyncDataSourceRequest,
    _emit_model_event,
    _excel_dir,
    _meta_path,
    _read_json,
    _write_json,
)


@router.post("/projects/{pid}/models/{mid}/links")
def create_link(
    pid: str,
    mid: str,
    body: CreateModelLinkRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a link from a cell in another model to a cell in this model."""
    require_project_role(pid, {"Owner", "Editor"}, user, db)

    # Load existing links
    excel_dir = _excel_dir(pid, mid)
    links_path = excel_dir / "links.json"
    all_links = _read_json(links_path, [])

    try:
        # Create the link
        link = create_model_link(
            source_model_id=body.source_model_id,
            source_cell_ref=body.source_cell_ref,
            target_model_id=mid,
            target_cell_ref=body.target_cell_ref,
            all_links=all_links,
        )

        all_links.append(link)
        _write_json(links_path, all_links)

        _emit_model_event(pid, mid, "link_created", {
            "link_id": link.get("id"),
            "source_model": body.source_model_id,
        })

        return link
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/projects/{pid}/models/{mid}/links")
def list_links(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List all links for this model."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    links_path = excel_dir / "links.json"
    all_links = _read_json(links_path, [])

    model_links = list_model_links(all_links, filter_model_id=mid)

    return {"items": model_links, "count": len(model_links)}


@router.get("/projects/{pid}/models/{mid}/links/impact")
def link_impact(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get impact analysis of changes to this model on dependent models."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    links_path = excel_dir / "links.json"
    all_links = _read_json(links_path, [])

    impact = get_link_impact(mid, all_links)
    return impact


@router.get("/projects/{pid}/models/{mid}/links/graph")
def dependency_graph(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get the model dependency graph."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    links_path = excel_dir / "links.json"
    all_links = _read_json(links_path, [])

    graph = build_model_dependency_graph(all_links)
    return graph


@router.post("/projects/{pid}/models/{mid}/links/resolve-cell")
def resolve_cell(
    pid: str,
    mid: str,
    body: ResolveCellReferenceRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Resolve a cell reference - check if it's linked to another model."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    links_path = excel_dir / "links.json"
    all_links = _read_json(links_path, [])

    result = resolve_cell_reference(mid, body.cell_ref, body.cell_value, all_links)
    return result


@router.post("/projects/{pid}/models/{mid}/links/sync")
def sync_links(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Sync all linked cells from this model to dependent models."""
    require_project_role(pid, {"Owner", "Editor"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    links_path = excel_dir / "links.json"
    all_links = _read_json(links_path, [])

    # Get model assumptions
    model_meta = _read_json(_meta_path(pid, mid), {})
    assumptions = model_meta.get("assumptions", {})

    # Sync linked cells
    sync_result = sync_linked_cells(mid, assumptions, all_links)

    _emit_model_event(pid, mid, "links_synced", {"synced_count": sync_result["synced_cell_count"]})

    return sync_result


@router.post("/projects/{pid}/models/{mid}/links/validate")
def validate_links(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Validate all links for integrity issues (circular dependencies, etc)."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    links_path = excel_dir / "links.json"
    all_links = _read_json(links_path, [])

    validation = validate_all_links(all_links)
    return validation


@router.post("/projects/{pid}/models/{mid}/external-data/connect")
def create_external_data_connector(
    pid: str,
    mid: str,
    request: CreateDataSourceConnectorRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a data source connector for importing external data."""
    require_project_role(pid, {"Owner", "Editor"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    connectors_path = excel_dir / "connectors.json"
    all_connectors = _read_json(connectors_path, [])

    connector = create_data_source_connector(
        model_id=mid,
        source_name=request.source_name,
        file_path=request.file_path,
        file_type=request.file_type,
        column_mapping=request.column_mapping,
        refresh_schedule=request.refresh_schedule,
    )

    all_connectors.append(connector)
    _write_json(connectors_path, all_connectors)

    append_model_event(pid, mid, "external_data_connected", {
        "connector_id": connector["id"],
        "source_name": connector["source_name"],
    })

    return connector


@router.get("/projects/{pid}/models/{mid}/external-data/sources")
def list_external_data_sources(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all external data connectors for a model."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    connectors_path = excel_dir / "connectors.json"
    all_connectors = _read_json(connectors_path, [])

    return list_data_sources(all_connectors, filter_model_id=mid)


@router.post("/projects/{pid}/models/{mid}/external-data/sync")
def sync_external_data(
    pid: str,
    mid: str,
    request: SyncDataSourceRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Sync data from external source into model assumptions."""
    require_project_role(pid, {"Owner", "Editor"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    connectors_path = excel_dir / "connectors.json"
    meta_path = excel_dir / "metadata.json"

    all_connectors = _read_json(connectors_path, [])
    meta = _read_json(meta_path, {})

    # Find connector
    connector = None
    for c in all_connectors:
        if c["id"] == request.connector_id:
            connector = c
            break

    if not connector:
        raise HTTPException(status_code=404, detail=f"Connector {request.connector_id} not found")

    # Get current assumptions
    model_assumptions = meta.get("assumptions", {})

    # Sync data
    sync_result = sync_data_source(connector, model_assumptions)

    # Update connector sync metadata
    for c in all_connectors:
        if c["id"] == request.connector_id:
            c["last_synced_at"] = sync_result["synced_at"]
            c["sync_count"] = c.get("sync_count", 0) + 1
            break

    _write_json(connectors_path, all_connectors)

    # Update assumptions with synced values
    for assumption, value in sync_result["updated_assumptions"].items():
        model_assumptions[assumption] = value

    meta["assumptions"] = model_assumptions
    _write_json(meta_path, meta)

    # Track sync history
    sync_history_path = excel_dir / "sync_history.json"
    sync_history = _read_json(sync_history_path, [])
    sync_history.append(sync_result)
    _write_json(sync_history_path, sync_history)

    append_model_event(pid, mid, "external_data_synced", {
        "connector_id": connector["id"],
        "synced_assumptions": list(sync_result["updated_assumptions"].keys()),
        "error_count": sync_result["error_count"],
    })

    return sync_result


@router.get("/projects/{pid}/models/{mid}/external-data/lineage")
def get_external_data_lineage(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get data lineage - trace assumptions back to external sources."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    sync_history_path = excel_dir / "sync_history.json"
    sync_history = _read_json(sync_history_path, [])

    return get_data_lineage(mid, sync_history)


@router.post("/projects/{pid}/models/{mid}/external-data/drift-detection")
def detect_external_data_drift(
    pid: str,
    mid: str,
    threshold_pct: float = Query(default=5.0, ge=0.1, le=50.0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Detect drift in assumption values from external sources."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    sync_history_path = excel_dir / "sync_history.json"
    sync_history = _read_json(sync_history_path, [])

    if len(sync_history) < 2:
        return {
            "drift_count": 0,
            "drifts": [],
            "message": "Need at least 2 syncs to detect drift",
        }

    # Get current and previous sync results
    current_assumptions = sync_history[-1].get("updated_assumptions", {})
    previous_assumptions = sync_history[-2].get("updated_assumptions", {})

    drift = detect_data_drift(current_assumptions, previous_assumptions, threshold_pct)

    return {
        **drift,
        "comparison_syncs": {
            "current": sync_history[-1].get("synced_at"),
            "previous": sync_history[-2].get("synced_at"),
        },
    }


@router.get("/projects/{pid}/models/{mid}/external-data/lineage-graph")
def get_external_data_lineage_graph(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get data lineage graph visualization data."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    connectors_path = excel_dir / "connectors.json"
    sync_history_path = excel_dir / "sync_history.json"

    all_connectors = _read_json(connectors_path, [])
    sync_history = _read_json(sync_history_path, [])

    return build_data_lineage_graph(all_connectors, sync_history)


@router.post("/projects/{pid}/models/{mid}/budget/setup")
def setup_budget(
    pid: str,
    mid: str,
    request: CreateBudgetSetupRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a budget baseline for tracking."""
    require_project_role(pid, {"Owner", "Editor"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    budget_path = excel_dir / "budget.json"

    budget = create_budget_setup(
        model_id=mid,
        budget_data=request.budget_data,
        fiscal_year=request.fiscal_year,
        periods=request.periods,
    )

    _write_json(budget_path, budget)

    append_model_event(pid, mid, "budget_created", {
        "fiscal_year": budget["fiscal_year"],
        "total_budget": budget["total_budget"],
    })

    return budget


@router.post("/projects/{pid}/models/{mid}/budget/record-actuals")
def record_budget_actuals(
    pid: str,
    mid: str,
    request: RecordActualResultsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Record actual results for a period."""
    require_project_role(pid, {"Owner", "Editor"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    budget_path = excel_dir / "budget.json"
    actuals_path = excel_dir / "actuals_by_period.json"

    budget = _read_json(budget_path, None)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not setup")

    actuals_by_period = _read_json(actuals_path, {})

    # Record actual
    actual_recording = record_actual_results(
        budget,
        period=request.period,
        actual_data=request.actual_data,
    )

    # Store in actuals dict
    actuals_by_period[str(request.period)] = request.actual_data
    _write_json(actuals_path, actuals_by_period)

    append_model_event(pid, mid, "actuals_recorded", {
        "period": request.period,
        "total_actual": actual_recording["total_ytd_actual"],
    })

    return actual_recording


@router.post("/projects/{pid}/models/{mid}/budget/variance")
def get_budget_variance(
    pid: str,
    mid: str,
    request: RecordActualResultsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Calculate variance for a specific period."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    budget_path = excel_dir / "budget.json"

    budget = _read_json(budget_path, None)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not setup")

    variance = calculate_period_variance(
        budget,
        period=request.period,
        actual_data=request.actual_data,
    )

    return variance


@router.get("/projects/{pid}/models/{mid}/budget/ytd-variance")
def get_budget_ytd_variance(
    pid: str,
    mid: str,
    through_period: int = Query(ge=1, le=52),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get YTD variance through a period."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    budget_path = excel_dir / "budget.json"
    actuals_path = excel_dir / "actuals_by_period.json"

    budget = _read_json(budget_path, None)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not setup")

    actuals_by_period = _read_json(actuals_path, {})
    # Convert string keys to int
    actuals_by_period = {int(k): v for k, v in actuals_by_period.items()}

    ytd_variance = calculate_ytd_variance(budget, actuals_by_period, through_period)

    return ytd_variance


@router.get("/projects/{pid}/models/{mid}/budget/forecast")
def get_budget_forecast(
    pid: str,
    mid: str,
    through_period: int = Query(ge=1, le=52),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get full-year forecast based on YTD performance."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    budget_path = excel_dir / "budget.json"
    actuals_path = excel_dir / "actuals_by_period.json"

    budget = _read_json(budget_path, None)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not setup")

    actuals_by_period = _read_json(actuals_path, {})
    # Convert string keys to int
    actuals_by_period = {int(k): v for k, v in actuals_by_period.items()}

    forecast = forecast_full_year(budget, actuals_by_period, through_period)

    return forecast


@router.post("/projects/{pid}/models/{mid}/budget/report")
def generate_budget_report(
    pid: str,
    mid: str,
    request: GenerateBudgetReportRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generate comprehensive budget vs actual report."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)

    excel_dir = _excel_dir(pid, mid)
    budget_path = excel_dir / "budget.json"
    actuals_path = excel_dir / "actuals_by_period.json"

    budget = _read_json(budget_path, None)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not setup")

    actuals_by_period = _read_json(actuals_path, {})
    # Convert string keys to int
    actuals_by_period = {int(k): v for k, v in actuals_by_period.items()}

    report = generate_budget_vs_actual_report(
        budget,
        actuals_by_period,
        through_period=request.through_period,
        title=request.title,
    )

    return report


@router.get("/models/observability")
def models_observability(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    # Any authenticated user can inspect aggregate model/excel API counters.
    del db
    del user
    return {"counters": OBSERVABILITY_COUNTERS, "runtime": observability_snapshot()}
