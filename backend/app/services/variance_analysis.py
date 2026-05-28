"""Variance analysis service for budget vs actual analysis and drill-down."""

from datetime import datetime
from app.core.tz import IST
from enum import Enum
from typing import Any


def _now_iso() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now(IST).isoformat()


class VarianceSeverity(Enum):
    """Variance severity levels."""
    LOW = "low"  # < 2%
    MEDIUM = "medium"  # 2-5%
    HIGH = "high"  # 5-10%
    CRITICAL = "critical"  # > 10%


def calculate_simple_variance(
    actual: float,
    budget: float,
) -> dict[str, Any]:
    """
    Calculate variance between actual and budget values.

    Args:
        actual: Actual value
        budget: Budget/forecast value

    Returns:
        Dictionary with variance metrics
    """
    variance_amount = actual - budget
    variance_pct = (variance_amount / abs(budget)) * 100 if budget != 0 else 0

    # Determine severity
    abs_pct = abs(variance_pct)
    if abs_pct < 2:
        severity = VarianceSeverity.LOW.value
    elif abs_pct < 5:
        severity = VarianceSeverity.MEDIUM.value
    elif abs_pct < 10:
        severity = VarianceSeverity.HIGH.value
    else:
        severity = VarianceSeverity.CRITICAL.value

    return {
        "actual": float(round(actual, 2)),
        "budget": float(round(budget, 2)),
        "variance": float(round(variance_amount, 2)),
        "variance_pct": float(round(variance_pct, 1)),
        "favorable": variance_amount >= 0,  # For revenue
        "severity": severity,
    }


def calculate_line_item_variances(
    actual_data: dict[str, float],
    budget_data: dict[str, float],
) -> dict[str, Any]:
    """
    Calculate variances for multiple line items.

    Args:
        actual_data: Dict of actual values by line item
        budget_data: Dict of budget values by line item

    Returns:
        Dictionary with variance analysis by line item
    """
    variances = {}
    total_actual = 0
    total_budget = 0
    total_variance = 0

    all_items = set(list(actual_data.keys()) + list(budget_data.keys()))

    for item in sorted(all_items):
        actual = actual_data.get(item, 0)
        budget = budget_data.get(item, 0)

        variance = calculate_simple_variance(actual, budget)
        variances[item] = variance

        total_actual += actual
        total_budget += budget
        total_variance += variance["variance"]

    # Calculate total variance
    total_variance_pct = (total_variance / abs(total_budget)) * 100 if total_budget != 0 else 0

    return {
        "line_items": variances,
        "total_actual": float(round(total_actual, 2)),
        "total_budget": float(round(total_budget, 2)),
        "total_variance": float(round(total_variance, 2)),
        "total_variance_pct": float(round(total_variance_pct, 1)),
        "item_count": len(all_items),
        "high_variance_items": [
            item for item, v in variances.items()
            if v["severity"] in [VarianceSeverity.HIGH.value, VarianceSeverity.CRITICAL.value]
        ],
    }


def analyze_price_volume_mix(
    actual_units: float,
    actual_price: float,
    budget_units: float,
    budget_price: float,
) -> dict[str, Any]:
    """
    Analyze variance drivers: price, volume, and mix effects.

    Args:
        actual_units: Actual units sold/produced
        actual_price: Actual price per unit
        budget_units: Budgeted units
        budget_price: Budgeted price per unit

    Returns:
        Dictionary with variance decomposition
    """
    actual_revenue = actual_units * actual_price
    budget_revenue = budget_units * budget_price
    total_variance = actual_revenue - budget_revenue

    # Calculate components
    volume_variance = (actual_units - budget_units) * budget_price
    price_variance = actual_units * (actual_price - budget_price)
    # Volume-price interaction (small effect)
    mix_variance = (actual_units - budget_units) * (actual_price - budget_price)

    return {
        "actual_revenue": float(round(actual_revenue, 2)),
        "budget_revenue": float(round(budget_revenue, 2)),
        "total_variance": float(round(total_variance, 2)),
        "total_variance_pct": float(round((total_variance / budget_revenue * 100) if budget_revenue != 0 else 0, 1)),
        "drivers": {
            "volume": {
                "variance": float(round(volume_variance, 2)),
                "variance_pct": float(round((volume_variance / budget_revenue * 100) if budget_revenue != 0 else 0, 1)),
                "description": f"Volume variance: {actual_units:.0f} vs {budget_units:.0f} units",
            },
            "price": {
                "variance": float(round(price_variance, 2)),
                "variance_pct": float(round((price_variance / budget_revenue * 100) if budget_revenue != 0 else 0, 1)),
                "description": f"Price variance: ${actual_price:.2f} vs ${budget_price:.2f} per unit",
            },
            "mix": {
                "variance": float(round(mix_variance, 2)),
                "variance_pct": float(round((mix_variance / budget_revenue * 100) if budget_revenue != 0 else 0, 1)),
                "description": "Volume-price interaction",
            },
        },
        "actual_metrics": {
            "units": actual_units,
            "price_per_unit": float(round(actual_price, 2)),
        },
        "budget_metrics": {
            "units": budget_units,
            "price_per_unit": float(round(budget_price, 2)),
        },
    }


def calculate_waterfall_data(
    budget_value: float,
    variance_components: dict[str, float],
) -> dict[str, Any]:
    """
    Generate waterfall chart data (Budget → Variances → Actual).

    Args:
        budget_value: Starting budget value
        variance_components: Dict of variance components (name → amount)

    Returns:
        Dictionary with waterfall structure
    """
    waterfall_items = [
        {
            "label": "Budget",
            "value": float(round(budget_value, 2)),
            "type": "base",
            "cumulative": float(round(budget_value, 2)),
        }
    ]

    cumulative = budget_value

    for component_name, component_value in sorted(variance_components.items()):
        cumulative += component_value
        waterfall_items.append({
            "label": component_name,
            "value": float(round(component_value, 2)),
            "type": "increase" if component_value > 0 else "decrease",
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
        "budget": float(round(budget_value, 2)),
        "actual": float(round(cumulative, 2)),
        "total_variance": float(round(cumulative - budget_value, 2)),
    }


def analyze_trend_variance(
    actual_periods: list[float],
    budget_periods: list[float],
) -> dict[str, Any]:
    """
    Analyze variance trends over multiple periods.

    Args:
        actual_periods: List of actual values by period
        budget_periods: List of budget values by period

    Returns:
        Dictionary with trend analysis
    """
    if len(actual_periods) != len(budget_periods):
        raise ValueError("Actual and budget periods must have same length")

    variances = []
    variance_amounts = []

    for actual, budget in zip(actual_periods, budget_periods, strict=False):
        v = calculate_simple_variance(actual, budget)
        variances.append(v)
        variance_amounts.append(v["variance_pct"])

    # Calculate trend
    if len(variance_amounts) >= 2:
        trend_direction = "improving" if variance_amounts[-1] < variance_amounts[0] else "worsening"
    else:
        trend_direction = "stable"

    # Find worst period
    worst_variance = max(variances, key=lambda x: abs(x["variance_pct"]))
    worst_period = variance_amounts.index(worst_variance["variance_pct"])

    # Calculate average variance
    avg_variance = sum(v["variance_pct"] for v in variances) / len(variances) if variances else 0

    return {
        "period_variances": variances,
        "trend": trend_direction,
        "avg_variance_pct": float(round(avg_variance, 1)),
        "worst_variance_period": worst_period + 1,  # 1-indexed
        "worst_variance_pct": float(round(worst_variance["variance_pct"], 1)),
        "cumulative_variance": float(round(sum(v["variance"] for v in variances), 2)),
        "period_count": len(variances),
    }


def identify_variance_drivers(
    line_items_variance: dict[str, Any],
    threshold_pct: float = 5.0,
) -> dict[str, Any]:
    """
    Identify the main drivers of overall variance (Pareto analysis).

    Args:
        line_items_variance: Output from calculate_line_item_variances
        threshold_pct: Threshold % to classify as significant variance

    Returns:
        Dictionary with driver analysis
    """
    variances = line_items_variance.get("line_items", {})

    # Sort by absolute variance amount
    sorted_items = sorted(
        variances.items(),
        key=lambda x: abs(x[1]["variance"]),
        reverse=True,
    )

    drivers = []
    cumulative_variance = 0
    total_variance = abs(line_items_variance["total_variance"])

    for item_name, item_variance in sorted_items:
        variance_amount = item_variance["variance"]
        cumulative_variance += abs(variance_amount)
        pct_of_total = (abs(variance_amount) / total_variance * 100) if total_variance > 0 else 0

        drivers.append({
            "line_item": item_name,
            "variance": float(round(variance_amount, 2)),
            "variance_pct": float(round(item_variance["variance_pct"], 1)),
            "pct_of_total_variance": float(round(pct_of_total, 1)),
            "cumulative_pct_of_total": float(round(cumulative_variance / total_variance * 100, 1)) if total_variance > 0 else 0,
            "severity": item_variance["severity"],
            "is_significant": abs(item_variance["variance_pct"]) > threshold_pct,
        })

    # 80/20 analysis
    cumulative = 0
    key_drivers_80_pct = []
    for driver in drivers:
        cumulative += driver["pct_of_total_variance"]
        key_drivers_80_pct.append(driver["line_item"])
        if cumulative >= 80:
            break

    return {
        "drivers": drivers,
        "key_drivers_80_20": key_drivers_80_pct,
        "driver_count": len(drivers),
        "significant_variance_items": [d for d in drivers if d["is_significant"]],
    }


def generate_variance_report(
    actual_data: dict[str, float],
    budget_data: dict[str, float],
    title: str = "Variance Analysis Report",
) -> dict[str, Any]:
    """
    Generate a comprehensive variance analysis report.

    Args:
        actual_data: Dict of actual values
        budget_data: Dict of budget values
        title: Report title

    Returns:
        Dictionary with complete variance report
    """
    # Calculate line item variances
    line_item_variances = calculate_line_item_variances(actual_data, budget_data)

    # Identify drivers
    drivers = identify_variance_drivers(line_item_variances, threshold_pct=5.0)

    # Generate waterfall data
    variance_components = {
        item: v["variance"]
        for item, v in line_item_variances["line_items"].items()
    }
    waterfall = calculate_waterfall_data(
        line_item_variances["total_budget"],
        variance_components,
    )

    return {
        "report_title": title,
        "summary": {
            "budget": line_item_variances["total_budget"],
            "actual": line_item_variances["total_actual"],
            "variance": line_item_variances["total_variance"],
            "variance_pct": line_item_variances["total_variance_pct"],
            "favorable": line_item_variances["total_variance"] >= 0,
        },
        "line_items": line_item_variances["line_items"],
        "high_variance_items": line_item_variances["high_variance_items"],
        "drivers": drivers,
        "key_drivers": drivers["key_drivers_80_20"],
        "waterfall": waterfall,
        "generated_at": _now_iso(),
    }
