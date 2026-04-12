"""Test suite for variance analysis."""

import pytest
from app.services.variance_analysis import (
    calculate_simple_variance,
    calculate_line_item_variances,
    analyze_price_volume_mix,
    analyze_trend_variance,
    identify_variance_drivers,
    generate_variance_report,
)


class TestSimpleVariance:
    """Test simple variance calculations."""

    def test_simple_variance_favorable(self):
        """Test favorable variance (actual > budget for revenue)."""
        result = calculate_simple_variance(actual=1100, budget=1000)

        assert result["actual"] == 1100
        assert result["budget"] == 1000
        assert result["variance"] == 100
        assert result["variance_pct"] == pytest.approx(10.0)
        assert result["favorable"] is True

    def test_simple_variance_unfavorable(self):
        """Test unfavorable variance (actual < budget for revenue)."""
        result = calculate_simple_variance(actual=900, budget=1000)

        assert result["variance"] == -100
        assert result["variance_pct"] == pytest.approx(-10.0)
        assert result["favorable"] is False

    def test_simple_variance_zero(self):
        """Test zero variance."""
        result = calculate_simple_variance(actual=1000, budget=1000)

        assert result["variance"] == 0
        assert result["variance_pct"] == 0.0
        assert result["severity"] == "low"

    def test_simple_variance_severity(self):
        """Test variance severity classification."""
        # Low variance
        result_low = calculate_simple_variance(actual=1010, budget=1000)
        assert result_low["severity"] == "low"

        # Medium variance
        result_medium = calculate_simple_variance(actual=1035, budget=1000)
        assert result_medium["severity"] == "medium"

        # High variance
        result_high = calculate_simple_variance(actual=1065, budget=1000)
        assert result_high["severity"] == "high"

        # Critical variance
        result_critical = calculate_simple_variance(actual=1150, budget=1000)
        assert result_critical["severity"] == "critical"


class TestLineItemVariance:
    """Test line item variance analysis."""

    def test_line_item_variance_basic(self):
        """Test basic line item variance calculation."""
        actual = {"Revenue": 1100, "COGS": 450}
        budget = {"Revenue": 1000, "COGS": 400}

        result = calculate_line_item_variances(actual, budget)

        assert result["total_budget"] == 1400
        assert result["total_actual"] == 1550
        assert result["total_variance"] == 150
        assert result["item_count"] == 2

    def test_line_item_variance_multiple_items(self):
        """Test with multiple line items."""
        actual = {
            "Revenue": 1100,
            "COGS": 450,
            "OpEx": 200,
            "Tax": 130,
        }
        budget = {
            "Revenue": 1000,
            "COGS": 400,
            "OpEx": 220,
            "Tax": 126,
        }

        result = calculate_line_item_variances(actual, budget)

        assert "Revenue" in result["line_items"]
        assert "COGS" in result["line_items"]
        assert "OpEx" in result["line_items"]
        assert "Tax" in result["line_items"]
        assert result["item_count"] == 4

    def test_line_item_high_variance_detection(self):
        """Test detection of high variance items."""
        actual = {
            "Revenue": 1100,
            "COGS": 450,
            "OpEx": 500,  # Large variance
        }
        budget = {
            "Revenue": 1000,
            "COGS": 400,
            "OpEx": 220,
        }

        result = calculate_line_item_variances(actual, budget)

        high_variance_items = result["high_variance_items"]
        assert "OpEx" in high_variance_items

    def test_line_item_variance_mixed_items(self):
        """Test when actual has items budget doesn't have."""
        actual = {"Revenue": 1000, "Other Income": 100}
        budget = {"Revenue": 1000}

        result = calculate_line_item_variances(actual, budget)

        assert "Revenue" in result["line_items"]
        assert "Other Income" in result["line_items"]


class TestPriceVolumeMix:
    """Test price, volume, and mix analysis."""

    def test_price_volume_mix_volume_variance(self):
        """Test volume variance isolation."""
        result = analyze_price_volume_mix(
            actual_units=120,
            actual_price=10.0,
            budget_units=100,
            budget_price=10.0,
        )

        assert result["drivers"]["volume"]["variance"] == pytest.approx(200)  # (120-100) * 10
        assert result["drivers"]["price"]["variance"] == pytest.approx(0)

    def test_price_volume_mix_price_variance(self):
        """Test price variance isolation."""
        result = analyze_price_volume_mix(
            actual_units=100,
            actual_price=11.0,
            budget_units=100,
            budget_price=10.0,
        )

        assert result["drivers"]["volume"]["variance"] == pytest.approx(0)
        assert result["drivers"]["price"]["variance"] == pytest.approx(100)  # 100 * (11 - 10)

    def test_price_volume_mix_combined(self):
        """Test combined price and volume variances."""
        result = analyze_price_volume_mix(
            actual_units=120,
            actual_price=11.0,
            budget_units=100,
            budget_price=10.0,
        )

        # Total = (120 * 11) - (100 * 10) = 1320 - 1000 = 320
        assert result["total_variance"] == pytest.approx(320)
        # Volume = (120 - 100) * 10 = 200
        assert result["drivers"]["volume"]["variance"] == pytest.approx(200)
        # Price = 120 * (11 - 10) = 120
        assert result["drivers"]["price"]["variance"] == pytest.approx(120)
        # Mix = (120 - 100) * (11 - 10) = 20
        assert result["drivers"]["mix"]["variance"] == pytest.approx(20)


class TestTrendVariance:
    """Test trend variance analysis."""

    def test_trend_variance_improving(self):
        """Test variance trend improving over time."""
        actual = [1000, 1050, 1100, 1150]
        budget = [1000, 1000, 1000, 1000]

        result = analyze_trend_variance(actual, budget)

        assert result["period_count"] == 4
        assert len(result["period_variances"]) == 4

    def test_trend_variance_worsening(self):
        """Test variance trend worsening."""
        actual = [1000, 900, 800, 700]
        budget = [1000, 1000, 1000, 1000]

        result = analyze_trend_variance(actual, budget)

        assert result["period_count"] == 4
        # Variance percents: 0%, -10%, -20%, -30% - getting more negative means worsening
        variance_pcts = [v["variance_pct"] for v in result["period_variances"]]
        # First is better than last
        assert variance_pcts[0] > variance_pcts[-1]

    def test_trend_variance_cumulative(self):
        """Test cumulative variance over periods."""
        actual = [1100, 1050, 1075, 1120]
        budget = [1000, 1000, 1000, 1000]

        result = analyze_trend_variance(actual, budget)

        # Each period is +100, +50, +75, +120 = +345 total
        assert result["cumulative_variance"] == pytest.approx(345)

    def test_trend_variance_mismatched_lengths(self):
        """Test error handling for mismatched period lengths."""
        with pytest.raises(ValueError):
            analyze_trend_variance([100, 200], [100, 200, 300])


class TestVarianceDrivers:
    """Test variance driver identification."""

    def test_identify_drivers_pareto(self):
        """Test Pareto (80/20) analysis."""
        variance = {
            "line_items": {
                "A": {"variance": 100, "variance_pct": 5.0, "severity": "high"},
                "B": {"variance": 60, "variance_pct": 3.0, "severity": "medium"},
                "C": {"variance": 30, "variance_pct": 1.5, "severity": "low"},
                "D": {"variance": 10, "variance_pct": 0.5, "severity": "low"},
            },
            "total_variance": 200,
        }

        result = identify_variance_drivers(variance, threshold_pct=2.0)

        drivers = result["drivers"]
        assert len(drivers) == 4
        # First driver (A) should account for most variance
        assert drivers[0]["line_item"] == "A"

    def test_identify_drivers_80_20(self):
        """Test 80/20 key drivers identification."""
        variance = {
            "line_items": {
                "Major1": {"variance": 500, "variance_pct": 50.0, "severity": "critical"},
                "Major2": {"variance": 350, "variance_pct": 35.0, "severity": "high"},
                "Minor1": {"variance": 100, "variance_pct": 10.0, "severity": "medium"},
                "Minor2": {"variance": 50, "variance_pct": 5.0, "severity": "low"},
            },
            "total_variance": 1000,
        }

        result = identify_variance_drivers(variance)

        key_drivers = result["key_drivers_80_20"]
        # Should only need Major1 and Major2 to cover 80%+
        assert "Major1" in key_drivers
        assert "Major2" in key_drivers

    def test_identify_drivers_significance(self):
        """Test significant variance item flagging."""
        variance = {
            "line_items": {
                "Large": {"variance": 200, "variance_pct": 10.0, "severity": "high"},
                "Small": {"variance": 20, "variance_pct": 1.0, "severity": "low"},
            },
            "total_variance": 220,
        }

        result = identify_variance_drivers(variance, threshold_pct=5.0)

        drivers = result["drivers"]
        assert drivers[0]["is_significant"] is True  # 10% > 5%
        assert drivers[1]["is_significant"] is False  # 1% < 5%


class TestVarianceReport:
    """Test complete variance report generation."""

    def test_generate_variance_report_basic(self):
        """Test basic variance report generation."""
        actual = {"Revenue": 1100, "COGS": 450}
        budget = {"Revenue": 1000, "COGS": 400}

        result = generate_variance_report(actual, budget)

        assert "report_title" in result
        assert "summary" in result
        assert "line_items" in result
        assert "drivers" in result
        assert "waterfall" in result

    def test_variance_report_summary(self):
        """Test report summary section."""
        actual = {"Revenue": 1100, "COGS": 450, "OpEx": 200}
        budget = {"Revenue": 1000, "COGS": 400, "OpEx": 220}

        result = generate_variance_report(actual, budget, title="Q4 Variance")

        assert result["report_title"] == "Q4 Variance"
        assert result["summary"]["budget"] == 1620
        assert result["summary"]["actual"] == 1750
        assert result["summary"]["variance"] == 130
        assert result["summary"]["favorable"] is True

    def test_variance_report_waterfall(self):
        """Test waterfall data generation in report."""
        actual = {"Revenue": 1100, "OpEx": 180}
        budget = {"Revenue": 1000, "OpEx": 200}

        result = generate_variance_report(actual, budget)

        waterfall = result["waterfall"]
        assert waterfall["budget"] == 1200
        assert waterfall["actual"] == 1280
        assert len(waterfall["waterfall_items"]) > 0


class TestIntegration:
    """Integration tests for variance analysis."""

    def test_complete_variance_analysis_workflow(self):
        """Test complete variance analysis workflow."""
        # Setup actual vs budget data
        actual_data = {
            "Revenue": 1200,
            "COGS": 480,
            "Gross Profit": 720,
            "OpEx": 250,
            "EBIT": 470,
        }
        budget_data = {
            "Revenue": 1000,
            "COGS": 400,
            "Gross Profit": 600,
            "OpEx": 200,
            "EBIT": 400,
        }

        # Generate full report
        report = generate_variance_report(actual_data, budget_data, title="Monthly Analysis")

        # Verify complete structure
        # Total variance = (1200+480+720+250+470) - (1000+400+600+200+400) = 3120 - 2600 = 520
        assert report["summary"]["variance"] == 520
        assert len(report["key_drivers"]) > 0
        # Waterfall budget = 2600, actual = 3120
        assert report["waterfall"]["actual"] == 3120
        assert report["waterfall"]["budget"] == 2600

    def test_variance_with_price_volume_analysis(self):
        """Test variance analysis with price/volume breakdown."""
        # Product analysis
        pvmix = analyze_price_volume_mix(
            actual_units=1200,  # 20% higher volume
            actual_price=15.0,  # $1.5 higher price
            budget_units=1000,
            budget_price=13.5,
        )

        # Revenue variance should be split between price and volume
        assert pvmix["total_variance"] > 0
        assert pvmix["drivers"]["volume"]["variance"] > 0
        assert pvmix["drivers"]["price"]["variance"] > 0

    def test_variance_trend_and_drivers(self):
        """Test combining trend and driver analysis."""
        # Multi-period actual vs budget
        actual_periods = [1000, 1050, 1100, 1150]
        budget_periods = [1000, 1000, 1000, 1000]

        trend = analyze_trend_variance(actual_periods, budget_periods)

        # All periods show positive variance
        assert trend["cumulative_variance"] > 0
        assert all(v["favorable"] for v in trend["period_variances"])

    def test_variance_custom_title(self):
        """Test report with custom title."""
        actual = {"Item1": 100}
        budget = {"Item1": 100}

        result = generate_variance_report(actual, budget, title="Custom Report Title")

        assert result["report_title"] == "Custom Report Title"
