"""Financial calculation engine for NPV, IRR, DCF, and sensitivity analysis."""

from datetime import datetime
from app.core.tz import IST
from typing import Any

from scipy import optimize


def _now_iso() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now(IST).isoformat()


def calculate_npv(cash_flows: list[float], discount_rate: float) -> dict[str, Any]:
    """
    Calculate Net Present Value from a series of cash flows.

    Args:
        cash_flows: List of cash flows (first element is initial investment, typically negative)
        discount_rate: Annual discount rate (e.g., 0.10 for 10%)

    Returns:
        Dictionary with:
            - npv: Calculated NPV value
            - discount_rate: Input discount rate
            - periods: Number of periods
            - calculated_at: Timestamp
    """
    if not cash_flows or len(cash_flows) < 1:
        raise ValueError("At least one cash flow is required")

    if discount_rate < -0.99:
        raise ValueError("Discount rate must be greater than -99%")

    npv_value = 0.0
    for t, cf in enumerate(cash_flows):
        npv_value += cf / ((1 + discount_rate) ** t)

    return {
        "npv": round(npv_value, 2),
        "discount_rate": discount_rate,
        "periods": len(cash_flows),
        "calculated_at": _now_iso(),
    }


def calculate_irr(cash_flows: list[float], guess: float = 0.1) -> dict[str, Any]:
    """
    Calculate Internal Rate of Return using Newton-Raphson method.

    Args:
        cash_flows: List of cash flows (first element is typically negative investment)
        guess: Initial guess for IRR (default 10%)

    Returns:
        Dictionary with:
            - irr: Calculated IRR as decimal (e.g., 0.15 for 15%)
            - irr_percent: IRR as percentage
            - convergence: Boolean indicating convergence success
            - message: Description of result
            - calculated_at: Timestamp
    """
    if not cash_flows or len(cash_flows) < 2:
        raise ValueError("At least two cash flows are required for IRR")

    def npv_func(rate: float) -> float:
        """NPV function for root-finding."""
        return sum(cf / ((1 + rate) ** t) for t, cf in enumerate(cash_flows))

    def npv_derivative(rate: float) -> float:
        """First derivative of NPV for Newton-Raphson."""
        return sum(-t * cf / ((1 + rate) ** (t + 1)) for t, cf in enumerate(cash_flows))

    try:
        # Try Newton-Raphson method with initial guess
        irr_value = optimize.newton(
            npv_func,
            guess,
            fprime=npv_derivative,
            maxiter=1000,
            tol=1e-6,
        )

        # Validate the result
        residual = abs(npv_func(irr_value))
        converged = bool(residual < 1e-4)

        return {
            "irr": float(round(irr_value, 4)),
            "irr_percent": float(round(irr_value * 100, 2)),
            "convergence": converged,
            "message": "IRR calculated successfully" if converged else "IRR calculated with residual",
            "residual": float(round(residual, 6)) if not converged else None,
            "calculated_at": _now_iso(),
        }
    except (ValueError, RuntimeError) as e:
        # Fall back to scipy's brentq if Newton-Raphson fails
        try:
            # Check if there's a sign change (required for brentq)
            if npv_func(0.0) * npv_func(1.0) < 0:
                irr_value = optimize.brentq(npv_func, -0.99, 10.0, maxiter=1000, xtol=1e-6)
                return {
                    "irr": round(irr_value, 4),
                    "irr_percent": round(irr_value * 100, 2),
                    "convergence": True,
                    "message": "IRR calculated with alternative method",
                    "calculated_at": _now_iso(),
                }
        except ValueError:
            pass

        return {
            "irr": None,
            "irr_percent": None,
            "convergence": False,
            "message": f"IRR calculation failed: {str(e)}",
            "calculated_at": _now_iso(),
        }


def calculate_dcf(
    revenue_projections: list[float],
    cogs_percentages: list[float] | float,
    opex_projections: list[float] | float,
    tax_rate: float = 0.21,
    wacc: float = 0.10,
    terminal_growth: float = 0.02,
    capex_projections: list[float] | float = None,
    nwc_change: list[float] | float = None,
) -> dict[str, Any]:
    """
    Calculate DCF (Discounted Cash Flow) valuation.

    Args:
        revenue_projections: List of annual revenues
        cogs_percentages: COGS as % of revenue (scalar or list)
        opex_projections: Operating expenses (scalar or list)
        tax_rate: Corporate tax rate (default 21%)
        wacc: Weighted Average Cost of Capital (discount rate)
        terminal_growth: Terminal growth rate
        capex_projections: Capital expenditure (optional)
        nwc_change: Net working capital changes (optional)

    Returns:
        Dictionary with:
            - enterprise_value: DCF enterprise value
            - terminal_value: Value at end of projection period
            - pv_fcf: Present value of free cash flows
            - fcf_by_year: Free cash flows by year
            - wacc: Input WACC
            - terminal_growth: Input terminal growth rate
            - periods: Number of projection periods
    """
    if not revenue_projections or len(revenue_projections) < 1:
        raise ValueError("At least one revenue projection is required")

    if wacc <= -1.0:
        raise ValueError("WACC must be greater than -100%")

    periods = len(revenue_projections)

    # Normalize inputs to lists
    if isinstance(cogs_percentages, (int, float)):
        cogs_percentages = [cogs_percentages] * periods
    if isinstance(opex_projections, (int, float)):
        opex_projections = [opex_projections] * periods
    if capex_projections is None:
        capex_projections = [0] * periods
    elif isinstance(capex_projections, (int, float)):
        capex_projections = [capex_projections] * periods
    if nwc_change is None:
        nwc_change = [0] * periods
    elif isinstance(nwc_change, (int, float)):
        nwc_change = [nwc_change] * periods

    # Calculate Free Cash Flows
    fcf_by_year = []
    for year in range(periods):
        revenue = revenue_projections[year]
        cogs = revenue * cogs_percentages[year]
        opex = opex_projections[year]

        ebit = revenue - cogs - opex
        nopat = ebit * (1 - tax_rate)  # Net Operating Profit After Tax
        fcf = nopat - capex_projections[year] - nwc_change[year]
        fcf_by_year.append(fcf)

    # Calculate PV of explicit forecast period
    pv_fcf = sum(fcf / ((1 + wacc) ** (t + 1)) for t, fcf in enumerate(fcf_by_year))

    # Calculate Terminal Value (Gordon Growth Model)
    terminal_fcf = fcf_by_year[-1] * (1 + terminal_growth)
    terminal_value = terminal_fcf / (wacc - terminal_growth) if wacc > terminal_growth else 0
    pv_terminal = terminal_value / ((1 + wacc) ** periods)

    enterprise_value = pv_fcf + pv_terminal

    return {
        "enterprise_value": round(enterprise_value, 2),
        "pv_fcf": round(pv_fcf, 2),
        "terminal_value": round(terminal_value, 2),
        "pv_terminal_value": round(pv_terminal, 2),
        "fcf_by_year": [round(fcf, 2) for fcf in fcf_by_year],
        "wacc": wacc,
        "terminal_growth": terminal_growth,
        "periods": periods,
        "tax_rate": tax_rate,
        "calculated_at": _now_iso(),
    }


def sensitivity_analysis(
    base_case: dict[str, float],
    assumptions_to_vary: list[str],
    variance_range: tuple[float, float] = (-0.10, 0.10),
    output_cell: str = "npv",
    calculation_func=None,
) -> dict[str, Any]:
    """
    Perform sensitivity analysis by varying assumptions and measuring output impact.

    Args:
        base_case: Dictionary of assumption values
        assumptions_to_vary: List of assumption names to vary
        variance_range: Tuple of (min_variance, max_variance) as decimals
        output_cell: Name of output cell to measure
        calculation_func: Function that takes assumptions dict and returns output value

    Returns:
        Dictionary with:
            - sensitivity_table: List of rows with assumption, variance %, original_value, new_value, output_value, impact
            - base_output: Output value in base case
            - tornado_chart: Assumptions sorted by impact (high to low)
    """
    if not calculation_func:
        raise ValueError("calculation_func is required")

    try:
        base_output = calculation_func(base_case)
    except Exception as e:
        raise ValueError(f"Failed to calculate base case: {str(e)}") from e

    if not base_output or not isinstance(base_output, (int, float)):
        raise ValueError("Calculation function must return a numeric value")

    sensitivity_table = []
    impacts = []

    for assumption in assumptions_to_vary:
        if assumption not in base_case:
            continue

        base_value = base_case[assumption]

        # Try variance percentages
        test_values = [
            base_value * (1 + variance_range[0]),  # Lower bound
            base_value,  # Base case
            base_value * (1 + variance_range[1]),  # Upper bound
        ]

        for test_value in test_values:
            if test_value == base_value:
                continue

            modified_assumptions = base_case.copy()
            modified_assumptions[assumption] = test_value

            try:
                output_value = calculation_func(modified_assumptions)
            except Exception:  # noqa: S112 — best-effort, non-fatal
                continue

            variance_pct = ((test_value - base_value) / abs(base_value)) if base_value != 0 else 0
            impact = output_value - base_output
            impact_pct = (impact / abs(base_output)) if base_output != 0 else 0

            sensitivity_table.append({
                "assumption": assumption,
                "original_value": round(base_value, 2),
                "test_value": round(test_value, 2),
                "variance_pct": round(variance_pct * 100, 1),
                "output_value": round(output_value, 2),
                "impact": round(impact, 2),
                "impact_pct": round(impact_pct * 100, 2),
            })

            impacts.append({
                "assumption": assumption,
                "impact": abs(impact),
                "impact_pct": abs(impact_pct),
            })

    # Sort by impact for tornado chart
    tornado = sorted(impacts, key=lambda x: x["impact"], reverse=True)

    return {
        "base_case_output": round(base_output, 2),
        "sensitivity_table": sensitivity_table,
        "tornado_chart": tornado,
        "calculated_at": _now_iso(),
    }


def calculate_financial_metrics(
    revenue: float,
    cogs: float = 0,
    gross_profit: float = None,
    opex: float = 0,
    ebit: float = None,
    tax_rate: float = 0.21,
    net_income: float = None,
    total_assets: float = None,
    shareholders_equity: float = None,
    total_debt: float = None,
    cash: float = 0,
) -> dict[str, float]:
    """
    Calculate key financial metrics from income statement and balance sheet items.

    Returns metrics like gross margin, operating margin, net margin, ROE, ROIC, etc.
    """
    metrics = {}

    # Income statement metrics
    if revenue > 0:
        if gross_profit is None and cogs >= 0:
            gross_profit = revenue - cogs
        if gross_profit is not None and gross_profit >= 0:
            metrics["gross_margin_pct"] = round((gross_profit / revenue) * 100, 1)

        if ebit is None and opex >= 0 and gross_profit is not None:
            ebit = gross_profit - opex
        if ebit is not None and ebit >= 0:
            metrics["operating_margin_pct"] = round((ebit / revenue) * 100, 1)
            metrics["ebit"] = round(ebit, 2)

        if net_income is None and ebit is not None:
            taxes = ebit * tax_rate
            net_income = ebit - taxes
        if net_income is not None:
            metrics["net_margin_pct"] = round((net_income / revenue) * 100, 1)
            metrics["net_income"] = round(net_income, 2)

    # Balance sheet metrics
    if total_assets is not None and total_assets > 0 and net_income is not None:
        metrics["roa_pct"] = round((net_income / total_assets) * 100, 1)

    if shareholders_equity is not None and shareholders_equity > 0 and net_income is not None:
        metrics["roe_pct"] = round((net_income / shareholders_equity) * 100, 1)

    if total_debt is not None:
        if shareholders_equity is not None and shareholders_equity > 0:
            metrics["debt_to_equity"] = round(total_debt / shareholders_equity, 2)
        if ebit is not None and total_debt > 0:
            metrics["interest_coverage"] = round(ebit / (total_debt * 0.05), 2)  # Assuming 5% interest

    # Liquidity
    if cash is not None and total_assets is not None and total_assets > 0:
        metrics["cash_ratio"] = round(cash / total_assets, 2)

    return metrics
