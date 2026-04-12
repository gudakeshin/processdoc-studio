"""Test suite for budget vs actual tracking."""

import pytest
from app.services.budget_vs_actual import (
    create_budget_setup,
    record_actual_results,
    calculate_period_variance,
    calculate_ytd_variance,
    forecast_full_year,
    identify_budget_drivers,
    build_variance_waterfall,
    generate_budget_vs_actual_report,
)


class TestCreateBudgetSetup:
    """Test budget setup creation."""

    def test_create_budget_basic(self):
        """Test basic budget setup."""
        budget_data = {
            "Salaries": 6000,
            "Marketing": 2000,
            "Operations": 1000,
        }

        budget = create_budget_setup(
            model_id="model_a",
            budget_data=budget_data,
            fiscal_year=2024,
            periods=12,
        )

        assert budget["model_id"] == "model_a"
        assert budget["fiscal_year"] == 2024
        assert budget["total_budget"] == 9000
        assert budget["periods"] == 12

    def test_budget_period_allocation(self):
        """Test period budget allocation."""
        budget_data = {"Salaries": 12000, "Marketing": 1200}

        budget = create_budget_setup(
            model_id="model_a",
            budget_data=budget_data,
            fiscal_year=2024,
            periods=12,
        )

        # Monthly budget = annual / 12
        assert budget["period_budgets"]["Salaries"] == pytest.approx(1000.0)
        assert budget["period_budgets"]["Marketing"] == pytest.approx(100.0)


class TestRecordActualResults:
    """Test recording actual results."""

    def test_record_actual_basic(self):
        """Test recording actual results."""
        budget = create_budget_setup(
            model_id="model_a",
            budget_data={"Salaries": 12000},
            fiscal_year=2024,
        )

        actual = record_actual_results(
            budget,
            period=1,
            actual_data={"Salaries": 1050},
        )

        assert actual["period"] == 1
        assert actual["total_ytd_actual"] == 1050.0

    def test_record_multiple_cost_centers(self):
        """Test recording multiple cost centers."""
        budget = create_budget_setup(
            model_id="model_a",
            budget_data={"Salaries": 12000, "Marketing": 1200},
            fiscal_year=2024,
        )

        actual = record_actual_results(
            budget,
            period=1,
            actual_data={"Salaries": 1050, "Marketing": 120},
        )

        assert actual["total_ytd_actual"] == pytest.approx(1170.0)


class TestCalculatePeriodVariance:
    """Test period variance calculation."""

    def test_period_variance_favorable(self):
        """Test favorable variance (spending less)."""
        budget = create_budget_setup(
            model_id="model_a",
            budget_data={"Salaries": 12000},
            fiscal_year=2024,
        )

        variance = calculate_period_variance(
            budget,
            period=1,
            actual_data={"Salaries": 950},
        )

        assert variance["period"] == 1
        # Budget 1000, Actual 950, Variance -50 (favorable for costs)
        assert variance["period_variances"]["Salaries"]["variance"] == pytest.approx(-50.0)
        assert variance["period_variances"]["Salaries"]["favorable"] is True

    def test_period_variance_unfavorable(self):
        """Test unfavorable variance (spending more)."""
        budget = create_budget_setup(
            model_id="model_a",
            budget_data={"Marketing": 1200},
            fiscal_year=2024,
        )

        variance = calculate_period_variance(
            budget,
            period=1,
            actual_data={"Marketing": 150},
        )

        # Budget 100, Actual 150, Variance +50 (unfavorable for costs)
        assert variance["period_variances"]["Marketing"]["variance"] == pytest.approx(50.0)
        assert variance["period_variances"]["Marketing"]["favorable"] is False

    def test_period_variance_severity(self):
        """Test variance severity classification."""
        budget = create_budget_setup(
            model_id="model_a",
            budget_data={"Expense": 1200},  # Monthly budget 100
            fiscal_year=2024,
        )

        # 20% over = critical (120 vs 100)
        variance_critical = calculate_period_variance(
            budget, period=1, actual_data={"Expense": 120}
        )
        assert variance_critical["period_variances"]["Expense"]["severity"] == "critical"

        # 7% over = high (107 vs 100)
        variance_high = calculate_period_variance(
            budget, period=1, actual_data={"Expense": 107}
        )
        assert variance_high["period_variances"]["Expense"]["severity"] == "high"

    def test_period_variance_multiple_cost_centers(self):
        """Test variance with multiple cost centers."""
        budget = create_budget_setup(
            model_id="model_a",
            budget_data={"Salaries": 12000, "Marketing": 1200, "OpEx": 2400},
            fiscal_year=2024,
        )

        variance = calculate_period_variance(
            budget,
            period=1,
            actual_data={"Salaries": 1000, "Marketing": 150, "OpEx": 200},
        )

        # Monthly budgets: Salaries 1000, Marketing 100, OpEx 200 = 1300 total
        assert variance["total_budget"] == pytest.approx(1300.0)
        assert variance["total_actual"] == pytest.approx(1350.0)


class TestCalculateYTDVariance:
    """Test YTD variance calculation."""

    def test_ytd_variance_single_period(self):
        """Test YTD variance for 1 period."""
        budget = create_budget_setup(
            model_id="model_a",
            budget_data={"Salaries": 12000},
            fiscal_year=2024,
        )

        actual_by_period = {1: {"Salaries": 1050}}

        ytd = calculate_ytd_variance(budget, actual_by_period, through_period=1)

        assert ytd["through_period"] == 1
        assert ytd["ytd_budget"] == pytest.approx(1000.0)
        assert ytd["ytd_actual"] == pytest.approx(1050.0)

    def test_ytd_variance_multiple_periods(self):
        """Test YTD variance for multiple periods."""
        budget = create_budget_setup(
            model_id="model_a",
            budget_data={"Salaries": 12000},
            fiscal_year=2024,
        )

        actual_by_period = {
            1: {"Salaries": 1000},
            2: {"Salaries": 1050},
            3: {"Salaries": 1100},
        }

        ytd = calculate_ytd_variance(budget, actual_by_period, through_period=3)

        # 3 months * 1000/month = 3000 budget
        assert ytd["ytd_budget"] == pytest.approx(3000.0)
        # 1000 + 1050 + 1100 = 3150 actual
        assert ytd["ytd_actual"] == pytest.approx(3150.0)
        assert ytd["ytd_variance"] == pytest.approx(150.0)

    def test_ytd_variance_periods_remaining(self):
        """Test periods remaining calculation."""
        budget = create_budget_setup(
            model_id="model_a",
            budget_data={"Expense": 1200},
            fiscal_year=2024,
            periods=12,
        )

        actual_by_period = {1: {"Expense": 100}}

        ytd = calculate_ytd_variance(budget, actual_by_period, through_period=1)

        assert ytd["periods_recorded"] == 1
        assert ytd["periods_remaining"] == 11


class TestForecastFullYear:
    """Test full-year forecast."""

    def test_forecast_steady_spending(self):
        """Test forecast for steady spending pattern."""
        budget = create_budget_setup(
            model_id="model_a",
            budget_data={"Salaries": 12000},
            fiscal_year=2024,
            periods=12,
        )

        # First 3 months all 1000
        actual_by_period = {
            1: {"Salaries": 1000},
            2: {"Salaries": 1000},
            3: {"Salaries": 1000},
        }

        forecast = forecast_full_year(budget, actual_by_period, through_period=3)

        # Average: 3000/3 = 1000/month
        # Forecast: 3000 YTD + (1000 * 9 remaining) = 12000
        assert forecast["forecasts"]["Salaries"]["full_year_forecast"] == pytest.approx(12000.0)

    def test_forecast_increasing_spending(self):
        """Test forecast for increasing spending."""
        budget = create_budget_setup(
            model_id="model_a",
            budget_data={"Marketing": 1200},
            fiscal_year=2024,
            periods=12,
        )

        # Months 1-3 with increasing spend
        actual_by_period = {
            1: {"Marketing": 80},
            2: {"Marketing": 100},
            3: {"Marketing": 120},
        }

        forecast = forecast_full_year(budget, actual_by_period, through_period=3)

        # Average: 300/3 = 100/month
        # Forecast: 300 YTD + (100 * 9) = 1200
        assert forecast["forecasts"]["Marketing"]["full_year_forecast"] == pytest.approx(1200.0)

    def test_forecast_variance_at_completion(self):
        """Test forecast variance at completion."""
        budget = create_budget_setup(
            model_id="model_a",
            budget_data={"OpEx": 2400},
            fiscal_year=2024,
            periods=12,
        )

        actual_by_period = {
            1: {"OpEx": 230},  # Over budget
            2: {"OpEx": 220},
            3: {"OpEx": 240},
        }

        forecast = forecast_full_year(budget, actual_by_period, through_period=3)

        # Average: 690/3 = 230/month
        # Forecast: 690 + (230 * 9) = 2760
        # Budget: 2400, so variance = 360 over
        forecast_item = forecast["forecasts"]["OpEx"]
        assert forecast_item["full_year_forecast"] == pytest.approx(2760.0)
        assert forecast_item["variance_at_completion"] == pytest.approx(360.0)


class TestIdentifyBudgetDrivers:
    """Test driver identification."""

    def test_identify_drivers_pareto(self):
        """Test Pareto 80/20 analysis."""
        variances = {
            "Salaries": {"variance": 500, "variance_pct": 5.0, "severity": "high"},
            "Marketing": {"variance": 200, "variance_pct": 20.0, "severity": "critical"},
            "Office": {"variance": 50, "variance_pct": 2.0, "severity": "low"},
            "Supplies": {"variance": 10, "variance_pct": 1.0, "severity": "low"},
        }

        result = identify_budget_drivers(variances, threshold_pct=2.0)

        # Sorted by variance, so Salaries (500) comes first
        assert result["drivers"][0]["cost_center"] == "Salaries"
        assert len(result["key_drivers_80_20"]) >= 1

    def test_identify_drivers_significance(self):
        """Test significant variance flagging."""
        variances = {
            "Large": {"variance": 200, "variance_pct": 10.0, "severity": "high"},
            "Small": {"variance": 20, "variance_pct": 1.0, "severity": "low"},
        }

        result = identify_budget_drivers(variances, threshold_pct=5.0)

        large_driver = [d for d in result["drivers"] if d["cost_center"] == "Large"][0]
        small_driver = [d for d in result["drivers"] if d["cost_center"] == "Small"][0]

        assert large_driver["is_significant"] is True
        assert small_driver["is_significant"] is False


class TestBuildVarianceWaterfall:
    """Test waterfall chart data."""

    def test_waterfall_basic(self):
        """Test basic waterfall construction."""
        budget = 1000
        variances = {"Salaries": 50, "Marketing": -20, "OpEx": 30}

        result = build_variance_waterfall(budget, variances)

        assert result["budget"] == 1000
        assert result["actual"] == pytest.approx(1060.0)
        assert len(result["waterfall_items"]) == 5  # Budget + 3 items + Actual

    def test_waterfall_cumulative(self):
        """Test cumulative values in waterfall."""
        budget = 100
        variances = {"A": 20, "B": -10}

        result = build_variance_waterfall(budget, variances)

        items = result["waterfall_items"]
        assert items[0]["cumulative"] == 100  # Budget
        assert items[1]["cumulative"] == 120  # After A
        assert items[2]["cumulative"] == 110  # After B
        assert items[3]["cumulative"] == 110  # Actual


class TestGenerateBudgetVsActualReport:
    """Test comprehensive report generation."""

    def test_generate_report_basic(self):
        """Test basic report generation."""
        budget = create_budget_setup(
            model_id="model_a",
            budget_data={"Salaries": 12000, "Marketing": 1200},
            fiscal_year=2024,
        )

        actual_by_period = {
            1: {"Salaries": 1050, "Marketing": 120},
        }

        report = generate_budget_vs_actual_report(
            budget,
            actual_by_period,
            through_period=1,
        )

        assert "report_title" in report
        assert "summary" in report
        assert "period_variance" in report
        assert "ytd_variance" in report
        assert "full_year_forecast" in report
        assert "drivers" in report

    def test_report_multiple_periods(self):
        """Test report with multiple periods."""
        budget = create_budget_setup(
            model_id="model_a",
            budget_data={"Expense": 1200},
            fiscal_year=2024,
        )

        actual_by_period = {
            1: {"Expense": 100},
            2: {"Expense": 110},
            3: {"Expense": 105},
        }

        report = generate_budget_vs_actual_report(
            budget,
            actual_by_period,
            through_period=3,
            title="Q1 Report",
        )

        assert report["report_title"] == "Q1 Report"
        assert report["period"] == 3
        assert report["summary"]["periods_recorded"] == 3


class TestIntegration:
    """Integration tests for budget vs actual."""

    def test_complete_budget_tracking_workflow(self):
        """Test complete budget tracking workflow."""
        # Setup annual budget
        budget = create_budget_setup(
            model_id="financial_model",
            budget_data={
                "Salaries": 120000,
                "Marketing": 12000,
                "Operations": 24000,
            },
            fiscal_year=2024,
            periods=12,
        )

        # Record actuals for Q1
        actual_by_period = {
            1: {"Salaries": 10200, "Marketing": 1100, "Operations": 2100},
            2: {"Salaries": 10000, "Marketing": 950, "Operations": 2000},
            3: {"Salaries": 10300, "Marketing": 1050, "Operations": 2050},
        }

        # Generate Q1 report
        report = generate_budget_vs_actual_report(
            budget,
            actual_by_period,
            through_period=3,
            title="Q1 2024 Budget Review",
        )

        # Verify report structure
        assert report["fiscal_year"] == 2024
        assert report["summary"]["periods_recorded"] == 3

        # Verify variance calculations
        # Monthly budgets: Salaries 10000, Marketing 1000, Operations 2000 = 13000/month
        # Budget for 3 months = 39000
        # Actual: (10200+10000+10300) + (1100+950+1050) + (2100+2000+2050) = 30500 + 3100 + 6150 = 39750
        assert report["summary"]["budget"] == pytest.approx(39000.0)
        assert report["summary"]["actual"] == pytest.approx(39750.0)

        # Verify forecast
        forecast = report["full_year_forecast"]
        assert forecast["fiscal_year"] == 2024
        assert len(forecast["forecasts"]) == 3

        # Verify drivers identified
        assert len(report["drivers"]["drivers"]) > 0
        assert len(report["drivers"]["key_drivers_80_20"]) > 0
