"""Tests for Excel data auto-correction service (Cowork Tier 2)."""

import math
import pytest

from app.services.excel_corrections import DataCorrector


class TestDataCorrectorAssumptions:
    """Test assumption correction (type coercion, NaN/Inf replacement)."""

    def test_correct_assumptions_normal_dict(self):
        """Normal assumptions pass through unchanged."""
        assumptions = {
            "revenue": 1000000.0,
            "growth_rate": 0.10,
            "tax_rate": 0.21,
        }
        corrected, corrections = DataCorrector.correct_assumptions(assumptions)
        assert corrected == assumptions
        assert corrections == []

    def test_correct_assumptions_extracts_currency_string(self):
        """Extract numeric from currency string: "$1,000,000" -> 1000000.0."""
        assumptions = {"revenue": "$1,000,000"}
        corrected, corrections = DataCorrector.correct_assumptions(assumptions)
        assert corrected["revenue"] == 1000000.0
        assert len(corrections) == 1
        assert "extracted numeric" in corrections[0].lower()

    def test_correct_assumptions_extracts_percentage_string(self):
        """Extract numeric from percentage string: "10.0%" -> 10.0."""
        assumptions = {"growth_rate": "10.0%"}
        corrected, corrections = DataCorrector.correct_assumptions(assumptions)
        assert corrected["growth_rate"] == 10.0
        assert "extracted numeric" in corrections[0].lower()

    def test_correct_assumptions_replaces_nan_with_default(self):
        """Replace NaN with sensible default."""
        assumptions = {
            "tax_rate": float("nan"),
            "revenue": 1000000.0,
        }
        corrected, corrections = DataCorrector.correct_assumptions(assumptions)
        assert corrected["tax_rate"] == 0.21  # Default
        assert corrected["revenue"] == 1000000.0
        assert any("tax_rate" in c for c in corrections)

    def test_correct_assumptions_replaces_inf_with_default(self):
        """Replace Inf with sensible default."""
        assumptions = {"discount_rate": float("inf")}
        corrected, corrections = DataCorrector.correct_assumptions(assumptions)
        assert corrected["discount_rate"] == 0.10  # Default
        assert any("inf" in c.lower() for c in corrections)

    def test_correct_assumptions_removes_nan_if_no_default(self):
        """Remove NaN if no default available."""
        assumptions = {"custom_metric": float("nan")}
        corrected, corrections = DataCorrector.correct_assumptions(assumptions)
        assert "custom_metric" not in corrected
        assert any("custom_metric" in c for c in corrections)

    def test_correct_assumptions_skips_non_numeric_string(self):
        """Skip string that contains no numeric value."""
        assumptions = {"revenue": "abc"}
        corrected, corrections = DataCorrector.correct_assumptions(assumptions)
        # Should try default if available, skip otherwise
        assert "revenue" not in corrected or corrected["revenue"] in DataCorrector.ASSUMPTION_DEFAULTS.values()
        assert any("revenue" in c for c in corrections)

    def test_correct_assumptions_integer_conversion(self):
        """Convert integer to float."""
        assumptions = {"revenue": 1000000}  # int instead of float
        corrected, corrections = DataCorrector.correct_assumptions(assumptions)
        assert corrected["revenue"] == 1000000
        # Value is preserved; type is same as input for non-NaN/Inf valid numbers

    def test_correct_assumptions_multiple_fixes(self):
        """Apply multiple corrections to different fields."""
        assumptions = {
            "revenue": "$1,000,000",
            "tax_rate": float("nan"),
            "discount_rate": 0.10,
        }
        corrected, corrections = DataCorrector.correct_assumptions(assumptions)
        assert corrected["revenue"] == 1000000.0
        assert corrected["tax_rate"] == 0.21
        assert corrected["discount_rate"] == 0.10
        assert len(corrections) == 2


class TestDataCorrectorPeriods:
    """Test periods clamping."""

    def test_correct_periods_normal(self):
        """Normal periods pass through unchanged."""
        periods, correction = DataCorrector.correct_periods(5)
        assert periods == 5
        assert correction is None

    def test_correct_periods_clamps_zero(self):
        """Clamp periods=0 to 1."""
        periods, correction = DataCorrector.correct_periods(0)
        assert periods == 1
        assert correction is not None
        assert "0" in correction

    def test_correct_periods_clamps_negative(self):
        """Clamp negative periods to 1."""
        periods, correction = DataCorrector.correct_periods(-5)
        assert periods == 1
        assert correction is not None

    def test_correct_periods_clamps_100_plus(self):
        """Clamp periods > 100 to 100."""
        periods, correction = DataCorrector.correct_periods(1000)
        assert periods == 100
        assert correction is not None
        assert "100" in correction

    def test_correct_periods_invalid_type_uses_default(self):
        """Invalid type defaults to 5."""
        periods, correction = DataCorrector.correct_periods("abc")
        assert periods == 5
        assert correction is not None
        assert "invalid" in correction.lower() or "default" in correction.lower()


class TestDataCorrectorScenarios:
    """Test scenario filtering."""

    def test_correct_scenarios_none(self):
        """None scenarios returns empty list."""
        scenarios, corrections = DataCorrector.correct_scenarios(None)
        assert scenarios == []
        assert corrections == []

    def test_correct_scenarios_empty_list(self):
        """Empty list returns empty list."""
        scenarios, corrections = DataCorrector.correct_scenarios([])
        assert scenarios == []
        assert corrections == []

    def test_correct_scenarios_valid(self):
        """Valid scenarios with 'name' pass through."""
        input_scenarios = [
            {"name": "Scenario 1", "revenue_growth": 0.15},
            {"name": "Scenario 2", "revenue_growth": 0.05},
        ]
        scenarios, corrections = DataCorrector.correct_scenarios(input_scenarios)
        assert len(scenarios) == 2
        assert corrections == []

    def test_correct_scenarios_filters_missing_name(self):
        """Filter out scenarios missing 'name' key."""
        input_scenarios = [
            {"name": "Valid", "data": 1},
            {"data": 2},  # Missing name
        ]
        scenarios, corrections = DataCorrector.correct_scenarios(input_scenarios)
        assert len(scenarios) == 1
        assert scenarios[0]["name"] == "Valid"
        assert len(corrections) == 1

    def test_correct_scenarios_filters_non_dict(self):
        """Filter out non-dict scenarios."""
        input_scenarios = [
            {"name": "Valid"},
            None,
            "string",
            123,
        ]
        scenarios, corrections = DataCorrector.correct_scenarios(input_scenarios)
        assert len(scenarios) == 1
        assert len(corrections) == 3


class TestDataCorrectorHistoricalData:
    """Test historical data cleaning."""

    def test_correct_historical_data_none(self):
        """None data returns None."""
        data, corrections = DataCorrector.correct_historical_data(None)
        assert data is None
        assert corrections == []

    def test_correct_historical_data_empty(self):
        """Empty list returns empty list."""
        data, corrections = DataCorrector.correct_historical_data([])
        assert data == []
        assert corrections == []

    def test_correct_historical_data_valid(self):
        """Valid data passes through."""
        input_data = [1.0, 2.0, 3.0]
        data, corrections = DataCorrector.correct_historical_data(input_data)
        assert data == [1.0, 2.0, 3.0]
        assert corrections == []

    def test_correct_historical_data_removes_nan(self):
        """Remove NaN values."""
        input_data = [1.0, float("nan"), 3.0]
        data, corrections = DataCorrector.correct_historical_data(input_data)
        assert data == [1.0, 3.0]
        assert len(corrections) == 1
        assert "NaN" in corrections[0] or "nan" in corrections[0].lower()

    def test_correct_historical_data_removes_inf(self):
        """Remove Inf values."""
        input_data = [1.0, float("inf"), 3.0]
        data, corrections = DataCorrector.correct_historical_data(input_data)
        assert data == [1.0, 3.0]
        assert "Inf" in corrections[0] or "inf" in corrections[0].lower()

    def test_correct_historical_data_removes_invalid_type(self):
        """Remove non-numeric values."""
        input_data = [1.0, "abc", None, 3.0]
        data, corrections = DataCorrector.correct_historical_data(input_data)
        assert data == [1.0, 3.0]
        assert len(corrections) == 2

    def test_correct_historical_data_all_invalid_returns_none(self):
        """All invalid data returns None."""
        input_data = [float("nan"), "abc", None]
        data, corrections = DataCorrector.correct_historical_data(input_data)
        assert data is None
        assert any("All" in c for c in corrections)

    def test_correct_historical_data_converts_int(self):
        """Convert int to float."""
        input_data = [1, 2, 3]
        data, corrections = DataCorrector.correct_historical_data(input_data)
        assert data == [1.0, 2.0, 3.0]
        assert all(isinstance(x, float) for x in data)


class TestDataCorrectorBudgetData:
    """Test budget data validation."""

    def test_correct_budget_data_none(self):
        """None budget returns None."""
        data, corrections = DataCorrector.correct_budget_data(None)
        assert data is None
        assert corrections == []

    def test_correct_budget_data_valid(self):
        """Valid budget passes through."""
        input_data = {"Marketing": 10000.0, "Engineering": 50000.0}
        data, corrections = DataCorrector.correct_budget_data(input_data)
        assert data == input_data
        assert corrections == []

    def test_correct_budget_data_extracts_currency(self):
        """Extract numeric from currency string in budget."""
        input_data = {"Marketing": "$10,000"}
        data, corrections = DataCorrector.correct_budget_data(input_data)
        assert data["Marketing"] == 10000.0
        assert "extracted" in corrections[0].lower()

    def test_correct_budget_data_removes_nan(self):
        """Remove NaN from budget values."""
        input_data = {
            "Marketing": float("nan"),
            "Engineering": 50000.0,
        }
        data, corrections = DataCorrector.correct_budget_data(input_data)
        assert "Marketing" not in data
        assert data["Engineering"] == 50000.0
        assert len(corrections) == 1

    def test_correct_budget_data_skips_non_numeric(self):
        """Skip non-numeric budget values."""
        input_data = {
            "Marketing": "abc",
            "Engineering": 50000.0,
        }
        data, corrections = DataCorrector.correct_budget_data(input_data)
        assert "Marketing" not in data
        assert data["Engineering"] == 50000.0


class TestDataCorrectorActuals:
    """Test actuals_by_period validation."""

    def test_correct_actuals_none(self):
        """None actuals returns empty dict."""
        data, corrections = DataCorrector.correct_actuals_by_period(None)
        assert data == {}
        assert corrections == []

    def test_correct_actuals_valid(self):
        """Valid actuals pass through with integer keys."""
        input_data = {
            "1": {"revenue": 100000},
            "2": {"revenue": 120000},
        }
        data, corrections = DataCorrector.correct_actuals_by_period(input_data)
        assert 1 in data  # String key converted to int
        assert 2 in data
        assert corrections == []

    def test_correct_actuals_skips_non_dict_values(self):
        """Skip non-dict values."""
        input_data = {
            "1": {"revenue": 100000},
            "2": "not a dict",
        }
        data, corrections = DataCorrector.correct_actuals_by_period(input_data)
        assert 1 in data
        assert 2 not in data
        assert len(corrections) == 1

    def test_correct_actuals_skips_invalid_period_keys(self):
        """Skip invalid period keys."""
        input_data = {
            "1": {"revenue": 100000},
            "abc": {"revenue": 100000},
        }
        data, corrections = DataCorrector.correct_actuals_by_period(input_data)
        assert 1 in data
        assert "abc" not in data
        assert len(corrections) == 1
