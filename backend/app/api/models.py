import json
import logging
import uuid
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from openpyxl import Workbook
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.core.upload_validation import validate_excel_upload
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
from app.services.conflict_resolution import (
    create_conflict,
    get_conflict,
    list_conflicts,
    reopen_conflict,
    resolve_conflict,
    unresolved_high_risk_count,
)
from app.services.financial_calculations import (
    calculate_dcf,
    calculate_financial_metrics,
    calculate_irr,
    calculate_npv,
    sensitivity_analysis,
)
from app.services.financial_data_connector import (
    build_data_lineage_graph,
    create_data_source_connector,
    detect_data_drift,
    get_data_lineage,
    list_data_sources,
    sync_data_source,
)
from app.services.financial_statements import (
    generate_balance_sheet,
    generate_cash_flow_statement,
    generate_income_statement,
)
from app.services.forecasting import (
    calculate_arima_simple,
    calculate_exponential_smoothing,
    calculate_linear_regression,
    calculate_moving_average,
    compare_forecast_methods,
    forecast_with_confidence,
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
from app.services.model_links import (
    build_model_dependency_graph,
    create_model_link,
    get_link_impact,
    list_model_links,
    resolve_cell_reference,
    sync_linked_cells,
    validate_all_links,
)
from app.services.model_realtime import append_model_event, broadcast_model_event, replay_model_events
from app.services.observability import increment, observe_latency
from app.services.observability import snapshot as observability_snapshot
from app.services.scenario_runner import (
    compare_scenarios,
    get_scenario_rankings,
    load_all_scenario_results,
    load_scenario_results,
    refresh_all_scenario_results,
    run_scenario_calculation,
    save_scenario_results,
)
from app.services.storage import ensure_workspace, workspace_path
from app.services.variance_analysis import (
    analyze_price_volume_mix,
    analyze_trend_variance,
    calculate_line_item_variances,
    calculate_simple_variance,
    generate_variance_report,
)
from app.services.xlsx_parser import parse_workbook, quality_gate_failed

log = logging.getLogger(__name__)

router = APIRouter()
OBSERVABILITY_COUNTERS = {
    "models_created": 0,
    "scenarios_created": 0,
    "excel_imports": 0,
    "excel_exports": 0,
    "excel_export_errors": 0,  # Phase 1 Hardening: Track export errors
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
    return datetime.now(UTC).isoformat()


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


class CalculateNPVRequest(BaseModel):
    cash_flows: list[float]
    discount_rate: float


class CalculateIRRRequest(BaseModel):
    cash_flows: list[float]
    guess: float = Field(default=0.1)


class CalculateDCFRequest(BaseModel):
    revenue_projections: list[float]
    cogs_percentages: list[float] | float = 0.4
    opex_projections: list[float] | float = 0.2
    tax_rate: float = Field(default=0.21)
    wacc: float = Field(default=0.10)
    terminal_growth: float = Field(default=0.02)
    capex_projections: list[float] | float | None = None
    nwc_change: list[float] | float | None = None


class SensitivityAnalysisRequest(BaseModel):
    assumptions: dict[str, float]
    assumptions_to_vary: list[str]
    variance_range: list[float] = Field(default=[-0.10, 0.10])


class CalculateFinancialMetricsRequest(BaseModel):
    revenue: float
    cogs: float = 0
    gross_profit: float | None = None
    opex: float = 0
    ebit: float | None = None
    tax_rate: float = Field(default=0.21)
    net_income: float | None = None
    total_assets: float | None = None
    shareholders_equity: float | None = None
    total_debt: float | None = None
    cash: float = 0


class GenerateIncomeStatementRequest(BaseModel):
    revenue_projections: list[float]
    cogs_projections: list[float] | float = 0.4
    opex_projections: list[float] | float = 0.2
    other_income: list[float] | float = Field(default=0)
    tax_rate: float = Field(default=0.21)


class GenerateBalanceSheetRequest(BaseModel):
    current_assets: list[float] | float
    fixed_assets: list[float] | float
    current_liabilities: list[float] | float
    long_term_debt: list[float] | float
    shareholders_equity: list[float] | float


class GenerateCashFlowStatementRequest(BaseModel):
    net_income: list[float]
    capex_projections: list[float] | float
    working_capital_change: list[float] | float = Field(default=0)
    debt_issuance: list[float] | float = Field(default=0)
    equity_issuance: list[float] | float = Field(default=0)


class ForecastRequest(BaseModel):
    historical_data: list[float]
    forecast_periods: int = Field(default=5, ge=1, le=50)


class ExponentialSmoothingRequest(BaseModel):
    historical_data: list[float]
    forecast_periods: int = Field(default=5, ge=1, le=50)
    alpha: float = Field(default=0.3, ge=0.0, le=1.0)
    beta: float = Field(default=0.1, ge=0.0, le=1.0)


class MovingAverageRequest(BaseModel):
    historical_data: list[float]
    window_size: int = Field(default=3, ge=2, le=20)
    forecast_periods: int = Field(default=5, ge=1, le=50)


class ForecastWithConfidenceRequest(BaseModel):
    historical_data: list[float]
    forecast_periods: int = Field(default=5, ge=1, le=50)
    confidence_level: float = Field(default=0.95, ge=0.80, le=0.99)


class SimpleVarianceRequest(BaseModel):
    actual: float
    budget: float


class LineItemVarianceRequest(BaseModel):
    actual_data: dict[str, float]
    budget_data: dict[str, float]


class PriceVolumeMixRequest(BaseModel):
    actual_units: float
    actual_price: float
    budget_units: float
    budget_price: float


class TrendVarianceRequest(BaseModel):
    actual_periods: list[float]
    budget_periods: list[float]


class VarianceReportRequest(BaseModel):
    actual_data: dict[str, float]
    budget_data: dict[str, float]
    title: str = Field(default="Variance Analysis Report")


class CreateModelLinkRequest(BaseModel):
    source_model_id: str
    source_cell_ref: str
    target_cell_ref: str


class ResolveCellReferenceRequest(BaseModel):
    cell_ref: str
    cell_value: float | str | None = None


class CreateDataSourceConnectorRequest(BaseModel):
    source_name: str
    file_path: str
    file_type: str = Field(default="csv")
    column_mapping: dict[str, str]
    refresh_schedule: str = Field(default="manual")


class SyncDataSourceRequest(BaseModel):
    connector_id: str


class CreateBudgetSetupRequest(BaseModel):
    budget_data: dict[str, float]
    fiscal_year: int
    periods: int = Field(default=12, ge=1, le=52)


class RecordActualResultsRequest(BaseModel):
    period: int = Field(ge=1, le=52)
    actual_data: dict[str, float]


class GenerateBudgetReportRequest(BaseModel):
    through_period: int = Field(ge=1, le=52)
    title: str = Field(default="Budget vs Actual Report")


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
    version_id = f"{model_id}_v_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
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
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Export a financial model to a multi-sheet Excel workbook.

    Composes all financial services into a professional Excel model with
    10 sheets: Assumptions, Income Statement, Balance Sheet, Cash Flow,
    Financial Ratios, Valuation, Scenarios, Forecast, Budget vs Actual, Dashboard.

    Returns:
        dict with status, filename, and list of sheets created
    """
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    started = perf_counter()

    try:
        log.info(f"Excel export initiated for project {pid}, model {mid}, user {user.id}")

        # Load all available model data
        model = _read_json(_meta_path(pid, mid), {})
        assumptions = model.get("assumptions", {}) if isinstance(model, dict) else {}
        scenarios = _read_json(_model_dir(pid, mid) / "scenarios" / "index.json", [])
        excel_dir = _excel_dir(pid, mid)
        budget_data = _read_json(excel_dir / "budget.json", None)
        actuals = _read_json(excel_dir / "actuals_by_period.json", None)
        historical = assumptions.pop("historical_data", None) if isinstance(assumptions, dict) else None

        log.debug(f"Loaded model data: {len(assumptions)} assumptions, {len(scenarios) if scenarios else 0} scenarios")

        # Phase 1 Hardening: Size validation before processing
        assumptions_json_str = json.dumps(assumptions)
        if len(assumptions_json_str) > 10_000_000:  # 10 MB limit
            raise ValueError(f"Assumptions exceed 10 MB limit ({len(assumptions_json_str)} bytes)")

        if historical and len(historical) > 10_000:  # 10K points limit
            raise ValueError(f"Historical data exceeds 10,000 points ({len(historical)} points)")

        if scenarios and len(scenarios) > 1_000:  # 1K scenarios limit
            raise ValueError(f"Scenarios exceed 1,000 limit ({len(scenarios)} scenarios)")

        # ===== Cowork Alignment: Tier 2 - Auto-Correction =====
        # Apply automatic corrections to data quality issues before composition
        from app.services.excel_corrections import DataCorrector

        log.info("Applying auto-corrections to model data (Tier 2)")

        # Correct assumptions (extract from strings, replace NaN/Inf, etc)
        assumptions_orig = assumptions.copy() if isinstance(assumptions, dict) else {}
        assumptions, assumption_corrections = DataCorrector.correct_assumptions(assumptions_orig)
        for corr in assumption_corrections:
            log.info(f"Auto-correction: {corr}")
            increment("excel_export_auto_correction", tags=["type=assumption"])

        # Correct periods (clamp to [1, 100])
        periods_val = model.get("periods", 5)
        periods_val, period_correction = DataCorrector.correct_periods(periods_val)
        if period_correction:
            log.info(f"Auto-correction: {period_correction}")
            increment("excel_export_auto_correction", tags=["type=periods"])

        # Correct scenarios (filter malformed)
        if scenarios:
            scenarios.copy()
            scenarios, scenario_corrections = DataCorrector.correct_scenarios(scenarios)
            for corr in scenario_corrections:
                log.info(f"Auto-correction: {corr}")
            if scenario_corrections:
                increment("excel_export_auto_correction", tags=["type=scenarios"], delta=len(scenario_corrections))

        # Correct historical data (remove NaN/Inf)
        if historical:
            historical.copy()
            historical, historical_corrections = DataCorrector.correct_historical_data(historical)
            for corr in historical_corrections:
                log.info(f"Auto-correction: {corr}")
            if historical_corrections:
                increment("excel_export_auto_correction", tags=["type=historical"], delta=len(historical_corrections))

        # Correct budget data (ensure numeric)
        if budget_data:
            budget_data.copy()
            budget_data, budget_corrections = DataCorrector.correct_budget_data(budget_data)
            for corr in budget_corrections:
                log.info(f"Auto-correction: {corr}")
            if budget_corrections:
                increment("excel_export_auto_correction", tags=["type=budget"], delta=len(budget_corrections))

        # Correct actuals_by_period (validate structure)
        if actuals:
            actuals.copy()
            actuals, actuals_corrections = DataCorrector.correct_actuals_by_period(actuals)
            for corr in actuals_corrections:
                log.info(f"Auto-correction: {corr}")
            if actuals_corrections:
                increment("excel_export_auto_correction", tags=["type=actuals"], delta=len(actuals_corrections))

        # ===== Cowork Alignment: Tier 1 - Automatic Retry Loop =====
        # Compose with retry on transient failures
        from app.core.deliverable_xlsx import apply_cells_to_workbook
        from app.services.excel_model_composer import compose_financial_model_with_retry

        log.info("Composing financial model with retry (Tier 1)")

        try:
            xlsx_cells, compose_error = compose_financial_model_with_retry(
                assumptions=assumptions if isinstance(assumptions, dict) else {},
                scenarios=scenarios if isinstance(scenarios, list) else [],
                budget_data=budget_data,
                actuals_by_period=actuals,
                historical_data=historical if isinstance(historical, list) else None,
                periods=periods_val,
                max_retries=3,
            )

            if compose_error:
                # Compose failed after retries; determine if transient or validation
                if any(x in compose_error for x in ["NaN", "infinite", "bounds", "exceeds"]):
                    # Non-transient validation error
                    log.error(f"Model composition validation failed: {compose_error}")
                    raise HTTPException(status_code=400, detail=f"Invalid model data: {compose_error}")
                else:
                    # Transient error after max retries
                    log.error(f"Model composition failed after retries: {compose_error}")
                    raise HTTPException(status_code=503, detail=f"Temporary error, please retry: {compose_error}")

        except ValueError as e:
            log.error(f"Model composition validation failed: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid model data: {str(e)}") from e
        except HTTPException:
            raise  # Re-raise HTTP exceptions as-is
        except Exception as e:
            log.error(f"Model composition failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Model export generation failed") from e

        log.debug(f"Composed financial model: {len(xlsx_cells)} cells")

        # Write workbook using shared utility
        try:
            wb = Workbook()
            apply_cells_to_workbook(wb, xlsx_cells)
        except Exception as e:
            log.error(f"Workbook creation failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to create Excel workbook") from e

        # Save with timestamp
        export_dir = _model_dir(pid, mid) / "excel"
        export_dir.mkdir(parents=True, exist_ok=True)
        fname = f"export_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.xlsx"
        out_path = export_dir / fname

        try:
            buf = BytesIO()
            wb.save(buf)
            export_bytes = buf.getvalue()

            # Phase 1 Hardening: Export size limit
            if len(export_bytes) > 50_000_000:  # 50 MB limit
                raise ValueError(f"Export exceeds 50 MB limit ({len(export_bytes)} bytes)")

            out_path.write_bytes(export_bytes)

            # Phase 4 Hardening: Set file permissions (owner RW, group R, others none = 0640)
            try:
                out_path.chmod(0o640)
                export_dir.chmod(0o750)  # owner RWX, group RX, others none
            except OSError as e:
                log.warning(f"Failed to set file permissions on export: {e}")
                # Non-fatal; continue with looser permissions

        except ValueError as e:
            log.error(f"Export file size validation failed: {e}")
            raise HTTPException(status_code=413, detail=f"Export too large: {str(e)}") from e
        except OSError as e:
            log.error(f"Export file write failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to write export file to disk") from e
        except Exception as e:
            log.error(f"Export file save failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to save export file") from e

        # Phase 2 Hardening: Comprehensive metrics & observability
        elapsed = (perf_counter() - started) * 1000.0
        export_size = len(export_bytes)
        sheet_count = len(wb.sheetnames)
        cell_count = len(xlsx_cells)

        # Counter metrics
        OBSERVABILITY_COUNTERS["excel_exports"] += 1
        increment("excel_export_total")

        # Latency observation
        observe_latency("excel_export", elapsed)

        # Size metrics (histogram-equivalent using multiple observations)
        increment("excel_export_size_mb", max(1, export_size // (1024 * 1024)))  # Size in MB buckets
        increment("excel_export_cells", max(1, cell_count // 100))  # Cell count in 100-cell buckets
        increment("excel_export_sheets", sheet_count)

        # Slow export detection
        if elapsed > 30_000:  # >30 seconds
            log.warning(f"Slow export detected: {fname}, elapsed={elapsed:.1f}ms, "
                       f"size={export_size} bytes, sheets={sheet_count}, cells={cell_count}")
            increment("excel_export_slow")

        # Success logging with all metrics
        log.info(f"Excel export success: {fname}, size={export_size} bytes ({export_size // (1024 * 1024)} MB), "
                f"sheets={sheet_count}, cells={cell_count}, elapsed={elapsed:.1f}ms")

        # ===== Cowork Alignment: Tier 3 - Optional QA Evaluation =====
        # Evaluate export quality using QAAgentLoop if requested via query parameter
        qa_result = None
        enable_qa = request.query_params.get("enable_qa_loop", "false").lower() == "true"
        if enable_qa:
            from app.services.excel_qa_integration import ExcelQAEvaluator

            log.info("Running QA evaluation on export (Tier 3)")
            try:
                evaluator = ExcelQAEvaluator()
                qa_result = evaluator.evaluate_export_quality(
                    xlsx_cells=xlsx_cells,
                    model_summary={
                        "assumptions": len(assumptions),
                        "periods": periods_val,
                        "scenarios": len(scenarios) if scenarios else 0,
                    },
                    threshold=0.8,
                    project_id=pid,
                )
                if not qa_result.get("passed", True):
                    log.warning(f"QA evaluation failed: {qa_result.get('remediation_instructions')}")
                    increment("excel_export_qa_failed")
                else:
                    increment("excel_export_qa_passed")
            except Exception as e:
                log.error(f"QA evaluation error: {e}", exc_info=True)
                increment("excel_export_qa_error")
                # QA failure doesn't block export; log and continue

        # Build response payload
        response_payload = {
            "status": "exported",
            "file": fname,
            "sheets": wb.sheetnames,
        }

        # Include QA result if evaluation ran
        if qa_result:
            response_payload["qa_result"] = {
                "passed": qa_result.get("passed", False),
                "iterations": qa_result.get("iterations", 0),
            }

        return response_payload

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        log.error(f"Unexpected error in export endpoint: {e}", exc_info=True)
        OBSERVABILITY_COUNTERS["excel_export_errors"] = OBSERVABILITY_COUNTERS.get("excel_export_errors", 0) + 1
        increment("excel_export_error")
        raise HTTPException(status_code=500, detail="Unexpected export error") from e


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
    added = sorted(k for k in right if k not in left)
    removed = sorted(k for k in left if k not in right)
    changed: list[dict[str, Any]] = []
    for key in sorted(k for k in right if k in left):
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


@router.post("/projects/{pid}/models/{mid}/calculate/npv")
def calculate_model_npv(
    pid: str,
    mid: str,
    body: CalculateNPVRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Calculate Net Present Value from cash flows."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    try:
        result = calculate_npv(cash_flows=body.cash_flows, discount_rate=body.discount_rate)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/projects/{pid}/models/{mid}/calculate/irr")
def calculate_model_irr(
    pid: str,
    mid: str,
    body: CalculateIRRRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Calculate Internal Rate of Return from cash flows."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    try:
        result = calculate_irr(cash_flows=body.cash_flows, guess=body.guess)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/projects/{pid}/models/{mid}/calculate/dcf")
def calculate_model_dcf(
    pid: str,
    mid: str,
    body: CalculateDCFRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Calculate DCF (Discounted Cash Flow) valuation."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    try:
        result = calculate_dcf(
            revenue_projections=body.revenue_projections,
            cogs_percentages=body.cogs_percentages,
            opex_projections=body.opex_projections,
            tax_rate=body.tax_rate,
            wacc=body.wacc,
            terminal_growth=body.terminal_growth,
            capex_projections=body.capex_projections,
            nwc_change=body.nwc_change,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/projects/{pid}/models/{mid}/calculate/sensitivity")
def calculate_model_sensitivity(
    pid: str,
    mid: str,
    body: SensitivityAnalysisRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Calculate sensitivity analysis for assumptions."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    try:
        # Create a simple NPV calculation function for sensitivity
        def test_npv(assumptions: dict[str, float]) -> float:
            # Use discount_rate and cash_flows from assumptions
            discount_rate = assumptions.get("discount_rate", 0.1)
            cf = assumptions.get("cash_flows_0")
            if cf is None:
                return 0.0
            # Collect all cash_flows_N entries
            cash_flows = []
            i = 0
            while f"cash_flows_{i}" in assumptions:
                cash_flows.append(assumptions[f"cash_flows_{i}"])
                i += 1
            if not cash_flows:
                return 0.0
            result = calculate_npv(cash_flows=cash_flows, discount_rate=discount_rate)
            return result.get("npv", 0.0)

        result = sensitivity_analysis(
            base_case=body.assumptions,
            assumptions_to_vary=body.assumptions_to_vary,
            variance_range=(body.variance_range[0], body.variance_range[1]),
            calculation_func=test_npv,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/projects/{pid}/models/{mid}/scenarios/{sid}/results")
def get_scenario_results(
    pid: str,
    mid: str,
    sid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get calculated results for a specific scenario."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    excel_dir = _excel_dir(pid, mid)
    result = load_scenario_results(excel_dir, sid)
    if result is None:
        raise HTTPException(status_code=404, detail="Scenario results not found")
    return result


@router.post("/projects/{pid}/models/{mid}/scenarios/{sid}/recalculate")
def recalculate_scenario_results(
    pid: str,
    mid: str,
    sid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recalculate results for a specific scenario."""
    require_project_role(pid, {"Owner", "Editor"}, user, db)

    model_meta = _read_json(_meta_path(pid, mid), None)
    if not isinstance(model_meta, dict):
        raise HTTPException(status_code=404, detail="Model not found")

    scenarios = _read_json(_model_dir(pid, mid) / "scenarios" / "index.json", [])
    if not isinstance(scenarios, list):
        scenarios = []

    # Find the scenario
    scenario = next((s for s in scenarios if s.get("id") == sid), None)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")

    # Calculate results
    result = run_scenario_calculation(scenario, model_meta.get("assumptions", {}))
    saved = save_scenario_results(_excel_dir(pid, mid), sid, result)

    _emit_model_event(pid, mid, "scenario_recalculated", {"scenario_id": sid})
    return saved


@router.get("/projects/{pid}/models/{mid}/scenarios/results/all")
def get_all_scenario_results(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get calculated results for all scenarios."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    excel_dir = _excel_dir(pid, mid)
    results = load_all_scenario_results(excel_dir)
    return {"items": results}


@router.post("/projects/{pid}/models/{mid}/scenarios/recalculate-all")
def recalculate_all_scenarios(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recalculate results for all scenarios."""
    require_project_role(pid, {"Owner", "Editor"}, user, db)

    model_meta = _read_json(_meta_path(pid, mid), None)
    if not isinstance(model_meta, dict):
        raise HTTPException(status_code=404, detail="Model not found")

    scenarios = _read_json(_model_dir(pid, mid) / "scenarios" / "index.json", [])
    if not isinstance(scenarios, list):
        scenarios = []

    excel_dir = _excel_dir(pid, mid)
    results = refresh_all_scenario_results(excel_dir, model_meta, scenarios)

    _emit_model_event(pid, mid, "scenarios_recalculated", {"count": len(results)})
    return {"items": results, "count": len(results)}


@router.post("/projects/{pid}/models/{mid}/scenarios/{sid}/compare")
def compare_with_baseline(
    pid: str,
    mid: str,
    sid: str,
    baseline_sid: str = Query(default="baseline"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Compare a scenario against a baseline scenario."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    excel_dir = _excel_dir(pid, mid)

    baseline_result = load_scenario_results(excel_dir, baseline_sid)
    if baseline_result is None:
        raise HTTPException(status_code=404, detail="Baseline scenario results not found")

    scenario_result = load_scenario_results(excel_dir, sid)
    if scenario_result is None:
        raise HTTPException(status_code=404, detail="Scenario results not found")

    comparison = compare_scenarios(baseline_result, scenario_result)
    return comparison


@router.get("/projects/{pid}/models/{mid}/scenarios/ranking/{metric}")
def rank_scenarios_by_metric(
    pid: str,
    mid: str,
    metric: str,
    ascending: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Rank all scenarios by a specific metric."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    excel_dir = _excel_dir(pid, mid)

    all_results = load_all_scenario_results(excel_dir)
    rankings = get_scenario_rankings(all_results, metric, ascending=ascending)

    return {"metric": metric, "rankings": rankings}


@router.post("/projects/{pid}/models/{mid}/calculate/metrics")
def calculate_model_metrics(
    pid: str,
    mid: str,
    body: CalculateFinancialMetricsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Calculate key financial metrics (margins, ROE, ROIC, etc)."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    try:
        result = calculate_financial_metrics(
            revenue=body.revenue,
            cogs=body.cogs,
            gross_profit=body.gross_profit,
            opex=body.opex,
            ebit=body.ebit,
            tax_rate=body.tax_rate,
            net_income=body.net_income,
            total_assets=body.total_assets,
            shareholders_equity=body.shareholders_equity,
            total_debt=body.total_debt,
            cash=body.cash,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/projects/{pid}/models/{mid}/generate/income-statement")
def generate_income_statement_endpoint(
    pid: str,
    mid: str,
    body: GenerateIncomeStatementRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generate a projected Income Statement (P&L)."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    try:
        result = generate_income_statement(
            revenue_projections=body.revenue_projections,
            cogs_projections=body.cogs_projections,
            opex_projections=body.opex_projections,
            other_income=body.other_income,
            tax_rate=body.tax_rate,
            periods=len(body.revenue_projections),
        )
        return result
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/projects/{pid}/models/{mid}/generate/balance-sheet")
def generate_balance_sheet_endpoint(
    pid: str,
    mid: str,
    body: GenerateBalanceSheetRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generate a projected Balance Sheet."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    try:
        # Determine periods from the largest list
        if isinstance(body.current_assets, (list, tuple)):
            periods = len(body.current_assets)
        elif isinstance(body.fixed_assets, (list, tuple)):
            periods = len(body.fixed_assets)
        else:
            periods = 5

        result = generate_balance_sheet(
            current_assets=body.current_assets,
            fixed_assets=body.fixed_assets,
            current_liabilities=body.current_liabilities,
            long_term_debt=body.long_term_debt,
            shareholders_equity=body.shareholders_equity,
            periods=periods,
        )
        return result
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/projects/{pid}/models/{mid}/generate/cash-flow-statement")
def generate_cash_flow_statement_endpoint(
    pid: str,
    mid: str,
    body: GenerateCashFlowStatementRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generate a projected Cash Flow Statement."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    try:
        result = generate_cash_flow_statement(
            net_income=body.net_income,
            capex_projections=body.capex_projections,
            working_capital_change=body.working_capital_change,
            debt_issuance=body.debt_issuance,
            equity_issuance=body.equity_issuance,
            periods=len(body.net_income),
        )
        return result
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/projects/{pid}/models/{mid}/forecast/linear-regression")
def forecast_linear_regression(
    pid: str,
    mid: str,
    body: ForecastRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Forecast using linear regression with confidence intervals."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    try:
        result = calculate_linear_regression(body.historical_data, body.forecast_periods)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/projects/{pid}/models/{mid}/forecast/exponential-smoothing")
def forecast_exponential_smoothing(
    pid: str,
    mid: str,
    body: ExponentialSmoothingRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Forecast using exponential smoothing (Holt-Winters)."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    try:
        result = calculate_exponential_smoothing(
            body.historical_data,
            body.forecast_periods,
            alpha=body.alpha,
            beta=body.beta,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/projects/{pid}/models/{mid}/forecast/moving-average")
def forecast_moving_average(
    pid: str,
    mid: str,
    body: MovingAverageRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Forecast using moving average."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    try:
        result = calculate_moving_average(body.historical_data, body.window_size, body.forecast_periods)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/projects/{pid}/models/{mid}/forecast/arima")
def forecast_arima(
    pid: str,
    mid: str,
    body: ForecastRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Forecast using ARIMA(1,1,0) model."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    try:
        result = calculate_arima_simple(body.historical_data, body.forecast_periods)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/projects/{pid}/models/{mid}/forecast/compare-methods")
def forecast_compare_methods(
    pid: str,
    mid: str,
    body: ForecastRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Compare multiple forecasting methods and recommend best fit."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    try:
        result = compare_forecast_methods(body.historical_data, body.forecast_periods)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/projects/{pid}/models/{mid}/forecast/ensemble-with-confidence")
def forecast_ensemble_with_confidence(
    pid: str,
    mid: str,
    body: ForecastWithConfidenceRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Forecast using ensemble of methods with confidence intervals."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    try:
        result = forecast_with_confidence(
            body.historical_data,
            body.forecast_periods,
            body.confidence_level,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/projects/{pid}/models/{mid}/variance/simple")
def variance_simple(
    pid: str,
    mid: str,
    body: SimpleVarianceRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Calculate simple variance between actual and budget."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    result = calculate_simple_variance(body.actual, body.budget)
    return result


@router.post("/projects/{pid}/models/{mid}/variance/line-items")
def variance_line_items(
    pid: str,
    mid: str,
    body: LineItemVarianceRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Analyze variance for multiple line items."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    result = calculate_line_item_variances(body.actual_data, body.budget_data)
    return result


@router.post("/projects/{pid}/models/{mid}/variance/price-volume-mix")
def variance_price_volume_mix(
    pid: str,
    mid: str,
    body: PriceVolumeMixRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Analyze variance drivers: price, volume, and mix effects."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    result = analyze_price_volume_mix(
        body.actual_units,
        body.actual_price,
        body.budget_units,
        body.budget_price,
    )
    return result


@router.post("/projects/{pid}/models/{mid}/variance/trend")
def variance_trend(
    pid: str,
    mid: str,
    body: TrendVarianceRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Analyze variance trends over multiple periods."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    try:
        result = analyze_trend_variance(body.actual_periods, body.budget_periods)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/projects/{pid}/models/{mid}/variance/report")
def variance_report(
    pid: str,
    mid: str,
    body: VarianceReportRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Generate comprehensive variance analysis report."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    result = generate_variance_report(
        body.actual_data,
        body.budget_data,
        body.title,
    )
    return result


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
