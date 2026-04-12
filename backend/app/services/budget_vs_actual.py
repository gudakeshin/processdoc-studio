"""Budget vs actual tracking and variance analysis for ongoing periods."""

from datetime import datetime, timezone
from typing import Any
from collections import defaultdict
import json


def _now_iso() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def create_budget_setup(
    model_id: str,
    budget_data: dict[str, float],
    fiscal_year: int,
    periods: int = 12,
) -> dict[str, Any]:
    """
    Create a budget baseline for tracking.

    Args:
        model_id: Model ID
        budget_data: Dict of cost_center -> budgeted_amount
        fiscal_year: Fiscal year for budget
        periods: Number of periods (months/quarters)

    Returns:
        Budget setup object
    """
    budget_setup = {
        "id": f"budget_{datetime.now(timezone.utc).timestamp()}",
        "model_id": model_id,
        "fiscal_year": fiscal_year,
        "periods": periods,
        "budget_data": budget_data,
        "total_budget": sum(budget_data.values()),
        "created_at": _now_iso(),
        "period_budgets": {
            cost_center: amount / periods
            for cost_center, amount in budget_data.items()
        },
    }

    return budget_setup


def record_actual_results(
    budget_setup: dict[str, Any],
    period: int,
    actual_data: dict[str, float],
) -> dict[str, Any]:
    """
    Record actual results for a period.

    Args:
        budget_setup: Budget setup object
        period: Period number (1-12 for months)
        actual_data: Dict of cost_center -> actual_amount

    Returns:
        Recording object with metadata
    """
    period_budgets = budget_setup.get("period_budgets", {})

    # Calculate cumulative budget to date
    ytd_budget = {}
    for cost_center, period_budget in period_budgets.items():
        ytd_budget[cost_center] = period_budget * period

    # Calculate cumulative actual to date
    ytd_actual = {}
    total_ytd_budget = 0
    total_ytd_actual = 0

    for cost_center, actual_amount in actual_data.items():
        ytd_actual[cost_center] = actual_amount
        period_budget = period_budgets.get(cost_center, 0)
        ytd_budget[cost_center] = period_budget * period

        total_ytd_budget += ytd_budget[cost_center]
        total_ytd_actual += actual_amount

    recording = {
        "id": f"actual_{datetime.now(timezone.utc).timestamp()}",
        "budget_id": budget_setup["id"],
        "period": period,
        "recorded_at": _now_iso(),
        "period_actual": actual_data,
        "ytd_budget": ytd_budget,
        "ytd_actual": ytd_actual,
        "total_ytd_budget": total_ytd_budget,
        "total_ytd_actual": total_ytd_actual,
    }

    return recording


def calculate_period_variance(
    budget_setup: dict[str, Any],
    period: int,
    actual_data: dict[str, float],
) -> dict[str, Any]:
    """
    Calculate variance for a specific period.

    Args:
        budget_setup: Budget setup object
        period: Period number
        actual_data: Dict of cost_center -> actual_amount

    Returns:
        Period variance analysis
    """
    period_budgets = budget_setup.get("period_budgets", {})

    variances = {}
    total_budget = 0
    total_actual = 0
    total_variance = 0

    all_cost_centers = set(list(period_budgets.keys()) + list(actual_data.keys()))

    for cost_center in sorted(all_cost_centers):
        budget = period_budgets.get(cost_center, 0)
        actual = actual_data.get(cost_center, 0)
        variance = actual - budget

        # For costs, unfavorable = actual > budget
        favorable = variance <= 0  # Negative variance is good for expenses

        pct_variance = (variance / abs(budget) * 100) if budget != 0 else 0

        variances[cost_center] = {
            "budget": float(round(budget, 2)),
            "actual": float(round(actual, 2)),
            "variance": float(round(variance, 2)),
            "variance_pct": float(round(pct_variance, 1)),
            "favorable": favorable,
            "severity": "critical" if abs(pct_variance) > 10 else "high" if abs(pct_variance) > 5 else "medium" if abs(pct_variance) > 2 else "low",
        }

        total_budget += budget
        total_actual += actual
        total_variance += variance

    total_pct_variance = (total_variance / abs(total_budget) * 100) if total_budget != 0 else 0

    return {
        "period": period,
        "period_variances": variances,
        "total_budget": float(round(total_budget, 2)),
        "total_actual": float(round(total_actual, 2)),
        "total_variance": float(round(total_variance, 2)),
        "total_variance_pct": float(round(total_pct_variance, 1)),
        "total_favorable": total_variance <= 0,
        "high_variance_items": [
            cost_center for cost_center, v in variances.items()
            if v["severity"] in ["critical", "high"]
        ],
    }


def calculate_ytd_variance(
    budget_setup: dict[str, Any],
    actual_by_period: dict[int, dict[str, float]],
    through_period: int,
) -> dict[str, Any]:
    """
    Calculate YTD (year-to-date) variance through a period.

    Args:
        budget_setup: Budget setup object
        actual_by_period: Dict of period -> cost_center -> amount
        through_period: Calculate through this period number

    Returns:
        YTD variance analysis
    """
    period_budgets = budget_setup.get("period_budgets", {})

    ytd_variances = {}
    ytd_totals = {
        "budget": 0,
        "actual": 0,
        "variance": 0,
        "periods_recorded": 0,
    }

    all_cost_centers = set(period_budgets.keys())
    for period_actuals in actual_by_period.values():
        all_cost_centers.update(period_actuals.keys())

    for cost_center in sorted(all_cost_centers):
        ytd_budget = period_budgets.get(cost_center, 0) * through_period
        ytd_actual = 0

        for period in range(1, through_period + 1):
            if period in actual_by_period:
                ytd_actual += actual_by_period[period].get(cost_center, 0)

        variance = ytd_actual - ytd_budget
        favorable = variance <= 0

        pct_variance = (variance / abs(ytd_budget) * 100) if ytd_budget != 0 else 0

        ytd_variances[cost_center] = {
            "ytd_budget": float(round(ytd_budget, 2)),
            "ytd_actual": float(round(ytd_actual, 2)),
            "ytd_variance": float(round(variance, 2)),
            "ytd_variance_pct": float(round(pct_variance, 1)),
            "favorable": favorable,
        }

        ytd_totals["budget"] += ytd_budget
        ytd_totals["actual"] += ytd_actual
        ytd_totals["variance"] += variance

    ytd_totals["periods_recorded"] = len([p for p in actual_by_period.keys() if p <= through_period])

    ytd_pct_variance = (ytd_totals["variance"] / abs(ytd_totals["budget"]) * 100) if ytd_totals["budget"] != 0 else 0

    return {
        "through_period": through_period,
        "ytd_variances": ytd_variances,
        "ytd_budget": float(round(ytd_totals["budget"], 2)),
        "ytd_actual": float(round(ytd_totals["actual"], 2)),
        "ytd_variance": float(round(ytd_totals["variance"], 2)),
        "ytd_variance_pct": float(round(ytd_pct_variance, 1)),
        "ytd_favorable": ytd_totals["variance"] <= 0,
        "periods_recorded": ytd_totals["periods_recorded"],
        "periods_remaining": budget_setup["periods"] - ytd_totals["periods_recorded"],
    }


def forecast_full_year(
    budget_setup: dict[str, Any],
    actual_by_period: dict[int, dict[str, float]],
    through_period: int,
) -> dict[str, Any]:
    """
    Forecast full-year results based on YTD performance.

    Args:
        budget_setup: Budget setup object
        actual_by_period: Dict of period -> cost_center -> amount
        through_period: Current period

    Returns:
        Full-year forecast
    """
    period_budgets = budget_setup.get("period_budgets", {})
    total_periods = budget_setup.get("periods", 12)

    forecasted_full_year = {}
    ytd_actuals = {}

    all_cost_centers = set(period_budgets.keys())

    # Calculate YTD actuals
    for cost_center in all_cost_centers:
        ytd_actual = 0
        for period in range(1, through_period + 1):
            if period in actual_by_period:
                ytd_actual += actual_by_period[period].get(cost_center, 0)

        ytd_actuals[cost_center] = ytd_actual

    # Project remaining periods
    for cost_center in all_cost_centers:
        ytd_actual = ytd_actuals[cost_center]
        period_budget = period_budgets.get(cost_center, 0)

        # Simple average projection: assume same rate for remaining periods
        avg_per_period = ytd_actual / through_period if through_period > 0 else 0
        remaining_periods = total_periods - through_period
        projected_remaining = avg_per_period * remaining_periods

        full_year_forecast = ytd_actual + projected_remaining
        full_year_budget = period_budget * total_periods

        variance = full_year_forecast - full_year_budget

        forecasted_full_year[cost_center] = {
            "full_year_budget": float(round(full_year_budget, 2)),
            "ytd_actual": float(round(ytd_actual, 2)),
            "avg_per_period": float(round(avg_per_period, 2)),
            "remaining_periods": remaining_periods,
            "projected_remaining": float(round(projected_remaining, 2)),
            "full_year_forecast": float(round(full_year_forecast, 2)),
            "variance_at_completion": float(round(variance, 2)),
            "variance_pct": float(round((variance / abs(full_year_budget) * 100) if full_year_budget != 0 else 0, 1)),
        }

    total_budget = sum(period_budgets.values()) * total_periods
    total_forecast = sum(f["full_year_forecast"] for f in forecasted_full_year.values())
    total_variance = total_forecast - total_budget

    return {
        "fiscal_year": budget_setup["fiscal_year"],
        "through_period": through_period,
        "forecasts": forecasted_full_year,
        "total_budget": float(round(total_budget, 2)),
        "total_ytd_actual": float(round(sum(ytd_actuals.values()), 2)),
        "total_forecast": float(round(total_forecast, 2)),
        "total_variance_at_completion": float(round(total_variance, 2)),
        "total_variance_pct": float(round((total_variance / abs(total_budget) * 100) if total_budget != 0 else 0, 1)),
    }


def identify_budget_drivers(
    variances: dict[str, dict[str, Any]],
    threshold_pct: float = 5.0,
) -> dict[str, Any]:
    """
    Identify main drivers of budget variance (Pareto analysis).

    Args:
        variances: Dict of cost_center -> variance info
        threshold_pct: Threshold % for significance

    Returns:
        Driver analysis
    """
    # Sort by absolute variance
    sorted_items = sorted(
        variances.items(),
        key=lambda x: abs(x[1]["variance"]),
        reverse=True,
    )

    drivers = []
    cumulative_variance = 0
    total_variance = sum(abs(v["variance"]) for v in variances.values())

    for cost_center, variance_info in sorted_items:
        variance_amount = variance_info["variance"]
        cumulative_variance += abs(variance_amount)

        pct_of_total = (abs(variance_amount) / total_variance * 100) if total_variance > 0 else 0

        drivers.append({
            "cost_center": cost_center,
            "variance": float(round(variance_amount, 2)),
            "variance_pct": variance_info.get("variance_pct", 0),
            "pct_of_total_variance": float(round(pct_of_total, 1)),
            "cumulative_pct": float(round(cumulative_variance / total_variance * 100, 1)) if total_variance > 0 else 0,
            "severity": variance_info.get("severity", "low"),
            "is_significant": abs(variance_info.get("variance_pct", 0)) > threshold_pct,
        })

    # 80/20 analysis
    cumulative = 0
    key_drivers_80_pct = []
    for driver in drivers:
        cumulative += driver["pct_of_total_variance"]
        key_drivers_80_pct.append(driver["cost_center"])
        if cumulative >= 80:
            break

    return {
        "drivers": drivers,
        "key_drivers_80_20": key_drivers_80_pct,
        "driver_count": len(drivers),
        "significant_variance_items": [d for d in drivers if d["is_significant"]],
    }


def build_variance_waterfall(
    budget_amount: float,
    variance_by_cost_center: dict[str, float],
) -> dict[str, Any]:
    """
    Build waterfall data for variance visualization.

    Args:
        budget_amount: Starting budget
        variance_by_cost_center: Dict of cost_center -> variance amount

    Returns:
        Waterfall chart data
    """
    waterfall_items = [
        {
            "label": "Budget",
            "value": float(round(budget_amount, 2)),
            "type": "base",
            "cumulative": float(round(budget_amount, 2)),
        }
    ]

    cumulative = budget_amount

    for cost_center, variance in sorted(variance_by_cost_center.items()):
        cumulative += variance
        waterfall_items.append({
            "label": cost_center,
            "value": float(round(variance, 2)),
            "type": "increase" if variance > 0 else "decrease",
            "cumulative": float(round(cumulative, 2)),
        })

    waterfall_items.append({
        "label": "Actual",
        "value": float(round(cumulative, 2)),
        "type": "total",
        "cumulative": float(round(cumulative, 2)),
    })

    return {
        "waterfall_items": waterfall_items,
        "budget": float(round(budget_amount, 2)),
        "actual": float(round(cumulative, 2)),
        "total_variance": float(round(cumulative - budget_amount, 2)),
    }


def generate_budget_vs_actual_report(
    budget_setup: dict[str, Any],
    actual_by_period: dict[int, dict[str, float]],
    through_period: int,
    title: str = "Budget vs Actual Report",
) -> dict[str, Any]:
    """
    Generate comprehensive budget vs actual report.

    Args:
        budget_setup: Budget setup object
        actual_by_period: Dict of period -> cost_center -> amount
        through_period: Current period
        title: Report title

    Returns:
        Complete report with variances, forecasts, drivers
    """
    period_variance = calculate_period_variance(
        budget_setup, through_period, actual_by_period.get(through_period, {})
    )

    ytd_variance = calculate_ytd_variance(
        budget_setup, actual_by_period, through_period
    )

    full_year_forecast = forecast_full_year(
        budget_setup, actual_by_period, through_period
    )

    # Get drivers from period variance
    drivers = identify_budget_drivers(period_variance["period_variances"])

    # Build waterfall
    period_variances_dict = {
        cc: v["variance"]
        for cc, v in period_variance["period_variances"].items()
    }
    waterfall = build_variance_waterfall(
        period_variance["total_budget"],
        period_variances_dict,
    )

    return {
        "report_title": title,
        "fiscal_year": budget_setup["fiscal_year"],
        "period": through_period,
        "summary": {
            "budget": ytd_variance["ytd_budget"],
            "actual": ytd_variance["ytd_actual"],
            "variance": ytd_variance["ytd_variance"],
            "variance_pct": ytd_variance["ytd_variance_pct"],
            "favorable": ytd_variance["ytd_favorable"],
            "periods_recorded": ytd_variance["periods_recorded"],
        },
        "period_variance": period_variance,
        "ytd_variance": ytd_variance,
        "full_year_forecast": full_year_forecast,
        "drivers": drivers,
        "key_drivers": drivers["key_drivers_80_20"],
        "waterfall": waterfall,
        "generated_at": _now_iso(),
    }
