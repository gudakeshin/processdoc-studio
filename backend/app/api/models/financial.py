"""Financial calculations, scenario results, statements, forecasting, and variance routes."""

import logging
from typing import Any

from fastapi import (
    Depends,
    HTTPException,
    Query,
    Request,
)
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_project_role
from app.core.rate_limit import limiter
from app.db.models import User
from app.db.session import get_db
from app.services.financial_calculations import (
    calculate_dcf,
    calculate_financial_metrics,
    calculate_irr,
    calculate_npv,
    sensitivity_analysis,
)
from app.services.financial_metrics import compute_consolidated_metrics
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
from app.services.scenario_runner import (
    compare_scenarios,
    get_scenario_rankings,
    load_all_scenario_results,
    load_scenario_results,
    refresh_all_scenario_results,
    run_scenario_calculation,
    save_scenario_results,
)
from app.services.variance_analysis import (
    analyze_price_volume_mix,
    analyze_trend_variance,
    calculate_line_item_variances,
    calculate_simple_variance,
    generate_variance_report,
)

log = logging.getLogger(__name__)



from app.api.models._router import router  # noqa: F401
from app.api.models._shared import (
    CalculateDCFRequest,
    CalculateFinancialMetricsRequest,
    CalculateIRRRequest,
    CalculateNPVRequest,
    ExponentialSmoothingRequest,
    ForecastRequest,
    ForecastWithConfidenceRequest,
    GenerateBalanceSheetRequest,
    GenerateCashFlowStatementRequest,
    GenerateIncomeStatementRequest,
    LineItemVarianceRequest,
    MovingAverageRequest,
    PriceVolumeMixRequest,
    SensitivityAnalysisRequest,
    SimpleVarianceRequest,
    TrendVarianceRequest,
    VarianceReportRequest,
    _emit_model_event,
    _excel_dir,
    _meta_path,
    _model_calc_rate_limit,
    _model_dcf_rate_limit,
    _model_dir,
    _model_forecast_rate_limit,
    _read_json,
)

# ---------------------------------------------------------------------------
# Phase 3 — Consolidated financial dashboard
# ---------------------------------------------------------------------------

@router.get("/projects/{pid}/models/{mid}/financial/consolidated")
def financial_consolidated(
    pid: str,
    mid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    return compute_consolidated_metrics(_model_dir(pid, mid))



@router.post("/projects/{pid}/models/{mid}/calculate/npv")
@limiter.limit(_model_calc_rate_limit)
def calculate_model_npv(
    request: Request,
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
@limiter.limit(_model_calc_rate_limit)
def calculate_model_irr(
    request: Request,
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
@limiter.limit(_model_dcf_rate_limit)
def calculate_model_dcf(
    request: Request,
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
@limiter.limit(_model_dcf_rate_limit)
def calculate_model_sensitivity(
    request: Request,
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
@limiter.limit(_model_calc_rate_limit)
def calculate_model_metrics(
    request: Request,
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
@limiter.limit(_model_forecast_rate_limit)
def forecast_linear_regression(
    request: Request,
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
@limiter.limit(_model_forecast_rate_limit)
def forecast_exponential_smoothing(
    request: Request,
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
@limiter.limit(_model_forecast_rate_limit)
def forecast_moving_average(
    request: Request,
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
@limiter.limit(_model_forecast_rate_limit)
def forecast_arima(
    request: Request,
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
@limiter.limit(_model_forecast_rate_limit)
def forecast_compare_methods(
    request: Request,
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
@limiter.limit(_model_forecast_rate_limit)
def forecast_ensemble_with_confidence(
    request: Request,
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


