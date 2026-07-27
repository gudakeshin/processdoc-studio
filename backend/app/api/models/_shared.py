"""Shared helpers, schemas, and counters for the models package."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import settings
from app.core.tz import IST
from app.db.models import User
from app.db.session import SessionLocal
from app.services.model_realtime import append_model_event, broadcast_model_event
from app.services.storage import ensure_workspace, workspace_path

log = logging.getLogger(__name__)



def _model_calc_rate_limit() -> str:
    return (settings.model_calc_rate_limit or "30/minute").strip() or "30/minute"


def _model_dcf_rate_limit() -> str:
    return (settings.model_dcf_rate_limit or "10/minute").strip() or "10/minute"


def _model_forecast_rate_limit() -> str:
    return (settings.model_forecast_rate_limit or "20/minute").strip() or "20/minute"


# presence_store: {(pid, mid): {user_id: {"email": str, "connectedAt": str, "cursor": str | None}}}
_presence_store: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}


def _presence_room(pid: str, mid: str) -> dict[str, dict[str, Any]]:
    k = (pid, mid)
    if k not in _presence_store:
        _presence_store[k] = {}
    return _presence_store[k]


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


def _websocket_user_from_token(token: str) -> User | None:
    db = SessionLocal()
    try:
        try:
            payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
            if payload.get("typ") != "access":
                return None
            email = payload.get("sub")
            if not isinstance(email, str):
                return None
        except JWTError:
            return None
        return db.scalar(select(User).where(User.email == email))
    finally:
        db.close()


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


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


class ReportGenerateRequest(BaseModel):
    reportType: str = "comprehensive"
    format: str = "xlsx"
    title: str = "Financial Report"
    includeCharts: bool = True
    includeTables: bool = True
    recipients: str = ""


class StyleProfileRequest(BaseModel):
    formality: str = "Formal"
    tone: str = "Authoritative"
    persona: str = "Senior Director"
    verbosity: str = "Balanced"
    audience: str = "C-suite"


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
    version_id = f"{model_id}_v_{datetime.now(IST).strftime('%Y%m%d_%H%M%S')}"
    payload = {
        "version_id": version_id,
        "created_at": _now_iso(),
        "reason": reason,
        "model": meta,
        "scenarios": _read_json(mdir / "scenarios" / "index.json", []),
    }
    _write_json(mdir / "versions" / f"{version_id}.json", payload)
    return payload


