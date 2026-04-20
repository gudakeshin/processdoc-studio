"""Scenario analysis engine for running calculations across model scenarios."""

import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.financial_calculations import (
    calculate_financial_metrics,
    calculate_npv,
)


def _now_iso() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now(UTC).isoformat()


def _read_json(path: Path, fallback: Any) -> Any:
    """Read JSON file with fallback."""
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _write_json(path: Path, payload: Any) -> None:
    """Write JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_scenario_calculation(
    scenario: dict[str, Any],
    base_assumptions: dict[str, Any],
) -> dict[str, Any]:
    """
    Calculate metrics for a single scenario.

    Args:
        scenario: Scenario dict with id, name, assumption_overrides
        base_assumptions: Base model assumptions

    Returns:
        Dictionary with:
            - scenario_id: Scenario identifier
            - scenario_name: Scenario name
            - assumptions: Merged assumptions (base + overrides)
            - metrics: Calculated financial metrics
            - npv: NPV if applicable
            - calculated_at: Timestamp
    """
    if not isinstance(scenario, dict):
        raise ValueError("Scenario must be a dict")

    # Merge base assumptions with scenario overrides
    merged_assumptions = {**base_assumptions}
    overrides = scenario.get("assumption_overrides", {})
    if isinstance(overrides, dict):
        merged_assumptions.update(overrides)

    # Calculate metrics
    metrics = {}
    npv_result = None

    # Try to calculate financial metrics
    revenue = merged_assumptions.get("revenue")
    if revenue is not None:
        with contextlib.suppress(TypeError, ValueError):
            metrics = calculate_financial_metrics(
                revenue=float(revenue),
                cogs=float(merged_assumptions.get("cogs", 0)),
                opex=float(merged_assumptions.get("opex", 0)),
                tax_rate=float(merged_assumptions.get("tax_rate", 0.21)),
                total_assets=merged_assumptions.get("total_assets"),
                shareholders_equity=merged_assumptions.get("shareholders_equity"),
                total_debt=merged_assumptions.get("total_debt"),
                cash=float(merged_assumptions.get("cash", 0)),
            )

    # Try to calculate NPV if cash flows are present
    cash_flows_str = merged_assumptions.get("cash_flows")
    discount_rate = merged_assumptions.get("discount_rate")

    if cash_flows_str is not None and discount_rate is not None:
        try:
            # Handle both list and comma-separated string formats
            if isinstance(cash_flows_str, str):
                cash_flows = [float(x.strip()) for x in cash_flows_str.split(",")]
            elif isinstance(cash_flows_str, (list, tuple)):
                cash_flows = [float(x) for x in cash_flows_str]
            else:
                cash_flows = []

            if cash_flows:
                npv_result = calculate_npv(cash_flows, float(discount_rate))
        except (TypeError, ValueError):
            pass

    return {
        "scenario_id": scenario.get("id"),
        "scenario_name": scenario.get("name", "Scenario"),
        "assumptions": merged_assumptions,
        "metrics": metrics,
        "npv": npv_result,
        "calculated_at": _now_iso(),
    }


def compare_scenarios(
    baseline_result: dict[str, Any],
    other_result: dict[str, Any],
) -> dict[str, Any]:
    """
    Compare two scenario results and calculate variances.

    Args:
        baseline_result: Baseline scenario calculation result
        other_result: Other scenario calculation result

    Returns:
        Dictionary with:
            - scenario_id: ID of compared scenario
            - scenario_name: Name of compared scenario
            - baseline_scenario: Name of baseline
            - metrics_variance: Variance in metrics
            - npv_variance: NPV variance if applicable
    """
    variance = {
        "scenario_id": other_result.get("scenario_id"),
        "scenario_name": other_result.get("scenario_name"),
        "baseline_scenario": baseline_result.get("scenario_name"),
        "metrics_variance": {},
        "npv_variance": None,
    }

    # Compare metrics
    baseline_metrics = baseline_result.get("metrics", {})
    other_metrics = other_result.get("metrics", {})

    for key in set(list(baseline_metrics.keys()) + list(other_metrics.keys())):
        baseline_value = baseline_metrics.get(key)
        other_value = other_metrics.get(key)

        if baseline_value is not None and other_value is not None:
            try:
                baseline_val = float(baseline_value)
                other_val = float(other_value)
                variance_amount = other_val - baseline_val
                variance_pct = (variance_amount / abs(baseline_val)) * 100 if baseline_val != 0 else 0

                variance["metrics_variance"][key] = {
                    "baseline": round(baseline_val, 2),
                    "scenario": round(other_val, 2),
                    "variance": round(variance_amount, 2),
                    "variance_pct": round(variance_pct, 1),
                }
            except (TypeError, ValueError):
                pass

    # Compare NPV
    baseline_npv = baseline_result.get("npv")
    other_npv = other_result.get("npv")

    if (
        baseline_npv is not None
        and other_npv is not None
        and isinstance(baseline_npv, dict)
        and isinstance(other_npv, dict)
    ):
        baseline_npv_value = baseline_npv.get("npv")
        other_npv_value = other_npv.get("npv")

        if baseline_npv_value is not None and other_npv_value is not None:
            try:
                baseline_val = float(baseline_npv_value)
                other_val = float(other_npv_value)
                variance_amount = other_val - baseline_val
                variance_pct = (variance_amount / abs(baseline_val)) * 100 if baseline_val != 0 else 0

                variance["npv_variance"] = {
                    "baseline": round(baseline_val, 2),
                    "scenario": round(other_val, 2),
                    "variance": round(variance_amount, 2),
                    "variance_pct": round(variance_pct, 1),
                }
            except (TypeError, ValueError):
                pass

    return variance


def save_scenario_results(excel_dir: Path, scenario_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """
    Save scenario calculation results to filesystem.

    Args:
        excel_dir: Model's excel directory
        scenario_id: Scenario ID
        result: Scenario calculation result

    Returns:
        Result with saved_at timestamp
    """
    results_dir = excel_dir / "scenario_results"
    results_dir.mkdir(parents=True, exist_ok=True)
    result_path = results_dir / f"{scenario_id}.json"
    result["saved_at"] = _now_iso()
    _write_json(result_path, result)
    return result


def load_scenario_results(excel_dir: Path, scenario_id: str) -> dict[str, Any] | None:
    """
    Load scenario calculation results from filesystem.

    Args:
        excel_dir: Model's excel directory
        scenario_id: Scenario ID

    Returns:
        Scenario results dict or None if not found
    """
    result_path = excel_dir / "scenario_results" / f"{scenario_id}.json"
    return _read_json(result_path, None)


def load_all_scenario_results(excel_dir: Path) -> list[dict[str, Any]]:
    """
    Load all scenario results from filesystem.

    Args:
        excel_dir: Model's excel directory

    Returns:
        List of all scenario results
    """
    results_dir = excel_dir / "scenario_results"
    results = []

    if results_dir.exists():
        for result_file in sorted(results_dir.glob("*.json")):
            result = _read_json(result_file, None)
            if isinstance(result, dict):
                results.append(result)

    return results


def refresh_all_scenario_results(
    excel_dir: Path,
    model_meta: dict[str, Any],
    scenarios: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Recalculate results for all scenarios.

    Args:
        excel_dir: Model's excel directory
        model_meta: Model metadata with base assumptions
        scenarios: List of scenarios

    Returns:
        List of updated scenario results
    """
    base_assumptions = model_meta.get("assumptions", {})
    updated_results = []

    for scenario in scenarios:
        if not isinstance(scenario, dict):
            continue

        # Calculate scenario
        result = run_scenario_calculation(scenario, base_assumptions)

        # Save to filesystem
        saved = save_scenario_results(excel_dir, scenario.get("id", ""), result)
        updated_results.append(saved)

    return updated_results


def get_scenario_rankings(
    all_results: list[dict[str, Any]],
    metric_key: str,
    ascending: bool = False,
) -> list[dict[str, Any]]:
    """
    Rank scenarios by a specific metric.

    Args:
        all_results: List of scenario results
        metric_key: Key of metric to rank by (e.g., "gross_margin_pct")
        ascending: Sort ascending (default: descending)

    Returns:
        List of scenarios ranked by metric value
    """
    rankings = []

    for result in all_results:
        metrics = result.get("metrics", {})
        if metric_key in metrics:
            value = metrics[metric_key]
            rankings.append({
                "scenario_id": result.get("scenario_id"),
                "scenario_name": result.get("scenario_name"),
                "metric_value": value,
            })

    # Sort by metric value
    rankings.sort(key=lambda x: x["metric_value"], reverse=not ascending)

    return rankings
