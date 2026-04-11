"""
Excel Model Data Auto-Correction Service

Automatic correction for common data quality issues in financial models.
Implements Cowork Tier 2 alignment pattern for auto-recovery.

Corrections include:
- Assumption type coercion (string -> float)
- NaN/Inf detection and replacement with sensible defaults
- Out-of-bounds value clamping
- Malformed optional data filtering
"""

from __future__ import annotations

import math
import re
import logging
from typing import Any

log = logging.getLogger(__name__)


class DataCorrector:
    """Auto-correction for common data quality issues in financial models."""

    ASSUMPTION_DEFAULTS = {
        "tax_rate": 0.21,
        "discount_rate": 0.10,
        "terminal_growth_rate": 0.02,
        "growth_rate": 0.10,
        "cogs_percent": 0.40,
        "operating_expense_growth": 0.10,
        "capex_percent_revenue": 0.05,
    }

    @staticmethod
    def correct_assumptions(assumptions: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """
        Auto-correct common assumption issues.

        Returns (corrected_dict, corrections_made) tuple.
        Corrections include:
        - Extracting numeric values from currency strings
        - Replacing NaN/Inf with reasonable defaults
        - Removing non-numeric values
        """
        corrected = {}
        corrections = []

        for key, val in assumptions.items():
            try:
                # Attempt numeric extraction from strings
                if isinstance(val, str):
                    # Remove currency symbols, commas, etc: "$1,000,000" -> 1000000
                    numeric_str = re.sub(r'[^\d.\-+e]', '', val)
                    if numeric_str:
                        try:
                            val = float(numeric_str)
                            corrections.append(f"'{key}': extracted numeric {val} from string")
                        except ValueError:
                            raise ValueError(f"No valid numeric value in '{val}'")
                    else:
                        raise ValueError(f"No numeric value found in '{val}'")

                # Ensure float conversion
                if not isinstance(val, (int, float)):
                    val = float(val)

                # Check for NaN/Inf
                if math.isnan(val) or math.isinf(val):
                    if key in DataCorrector.ASSUMPTION_DEFAULTS:
                        default = DataCorrector.ASSUMPTION_DEFAULTS[key]
                        corrections.append(f"'{key}': {val} replaced with default {default}")
                        corrected[key] = default
                    else:
                        corrections.append(f"'{key}': {val} removed (no default)")
                        # Skip this value entirely
                        continue
                else:
                    corrected[key] = val

            except (ValueError, TypeError) as e:
                # Conversion failed; use default if available
                if key in DataCorrector.ASSUMPTION_DEFAULTS:
                    default = DataCorrector.ASSUMPTION_DEFAULTS[key]
                    corrections.append(f"'{key}': conversion failed, using default {default}")
                    corrected[key] = default
                else:
                    corrections.append(f"'{key}': conversion failed, skipped")
                    # Skip invalid value

        return corrected, corrections

    @staticmethod
    def correct_periods(periods: Any) -> tuple[int, str | None]:
        """
        Clamp periods to valid range [1, 100].

        Returns (corrected_periods, correction_message) tuple.
        If no correction needed, message is None.
        """
        try:
            p = int(periods)
            if p < 1:
                correction = f"periods {p} < 1, clamped to 1"
                return 1, correction
            if p > 100:
                correction = f"periods {p} > 100, clamped to 100"
                return 100, correction
            return p, None
        except (ValueError, TypeError):
            return 5, "periods invalid type, using default 5"

    @staticmethod
    def correct_scenarios(scenarios: list[dict] | None) -> tuple[list[dict], list[str]]:
        """
        Filter out malformed scenarios.

        Validates that each scenario is a dict with "name" key.
        Returns (filtered_scenarios, corrections_made) tuple.
        """
        if not scenarios:
            return [], []

        corrected = []
        corrections = []
        for idx, scn in enumerate(scenarios):
            if isinstance(scn, dict) and "name" in scn:
                corrected.append(scn)
            else:
                corrections.append(f"Scenario {idx}: skipped (malformed or missing name)")

        return corrected, corrections

    @staticmethod
    def correct_historical_data(
        historical: list[float] | None,
    ) -> tuple[list[float] | None, list[str]]:
        """
        Remove NaN/Inf from historical data.

        Returns (cleaned_historical, corrections_made) tuple.
        If all values are invalid, returns (None, corrections).
        """
        if not historical:
            return historical, []

        corrected = []
        corrections = []
        for idx, val in enumerate(historical):
            if isinstance(val, (int, float)):
                if not (math.isnan(val) or math.isinf(val)):
                    corrected.append(float(val))
                else:
                    corrections.append(f"Historical[{idx}]: {val} removed (NaN/Inf)")
            else:
                corrections.append(f"Historical[{idx}]: {val} removed (invalid type {type(val).__name__})")

        if not corrected:
            corrections.append("All historical data invalid; forecast will be skipped")
            return None, corrections

        return corrected, corrections

    @staticmethod
    def correct_budget_data(budget_data: dict[str, Any] | None) -> tuple[dict[str, float] | None, list[str]]:
        """
        Validate and correct budget data.

        Ensures all values are numeric. Non-numeric values are skipped with warning.
        Returns (corrected_budget, corrections_made) tuple.
        """
        if not budget_data:
            return budget_data, []

        corrected = {}
        corrections = []
        for key, val in budget_data.items():
            try:
                # Attempt numeric conversion
                if isinstance(val, str):
                    numeric_str = re.sub(r'[^\d.\-+e]', '', val)
                    if numeric_str:
                        val = float(numeric_str)
                        corrections.append(f"Budget '{key}': extracted {val} from string")
                    else:
                        raise ValueError(f"No numeric in budget '{key}'")
                else:
                    val = float(val)

                if math.isnan(val) or math.isinf(val):
                    corrections.append(f"Budget '{key}': {val} removed (NaN/Inf)")
                    continue

                corrected[key] = val
            except (ValueError, TypeError):
                corrections.append(f"Budget '{key}': {val} skipped (non-numeric)")

        return corrected if corrected else None, corrections

    @staticmethod
    def correct_actuals_by_period(
        actuals_by_period: dict[int, dict] | None,
    ) -> tuple[dict[int, dict], list[str]]:
        """
        Validate actuals_by_period structure.

        Ensures period keys are integers and values are dicts.
        Returns (validated_actuals, corrections_made) tuple.
        """
        if not actuals_by_period:
            return {}, []

        corrected = {}
        corrections = []
        for period, data in actuals_by_period.items():
            try:
                period_int = int(period)
                if isinstance(data, dict):
                    corrected[period_int] = data
                else:
                    corrections.append(f"Actuals period {period}: value is not dict, skipped")
            except (ValueError, TypeError):
                corrections.append(f"Actuals period {period}: invalid period key, skipped")

        return corrected, corrections
