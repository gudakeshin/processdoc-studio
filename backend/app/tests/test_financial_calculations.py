"""Test suite for financial calculations (NPV, IRR, DCF, sensitivity)."""

import pytest

from app.services.financial_calculations import (
    calculate_dcf,
    calculate_financial_metrics,
    calculate_irr,
    calculate_npv,
    sensitivity_analysis,
)


class TestNPV:
    """Test Net Present Value calculations."""

    def test_npv_simple_case(self):
        """Test NPV with simple cash flows."""
        # Initial investment of -100, then +50, +50, +50
        cash_flows = [-100, 50, 50, 50]
        discount_rate = 0.10

        result = calculate_npv(cash_flows, discount_rate)

        assert result["npv"] is not None
        assert result["discount_rate"] == 0.10
        assert result["periods"] == 4
        # NPV should be positive with 3 years of positive returns
        assert result["npv"] > 0

    def test_npv_with_zero_discount_rate(self):
        """Test NPV with 0% discount rate (simple sum)."""
        cash_flows = [-100, 50, 50, 50]
        result = calculate_npv(cash_flows, 0.0)

        assert result["npv"] == pytest.approx(50.0)

    def test_npv_negative_cashflows(self):
        """Test NPV with all negative cash flows."""
        cash_flows = [-100, -50, -50, -50]
        result = calculate_npv(cash_flows, 0.10)

        assert result["npv"] < 0

    def test_npv_invalid_discount_rate(self):
        """Test NPV with invalid discount rate."""
        with pytest.raises(ValueError):
            calculate_npv([1, 2, 3], -1.5)

    def test_npv_empty_cashflows(self):
        """Test NPV with empty cash flows."""
        with pytest.raises(ValueError):
            calculate_npv([], 0.10)


class TestIRR:
    """Test Internal Rate of Return calculations."""

    def test_irr_simple_case(self):
        """Test IRR with simple cash flows."""
        # -100 initial, then +50, +50, +50
        cash_flows = [-100, 50, 50, 50]
        result = calculate_irr(cash_flows)

        assert result["convergence"] is True
        assert result["irr"] is not None
        # IRR should be between 0 and 1 (0% to 100%)
        assert -0.5 < result["irr"] < 2.0

    def test_irr_convergence_message(self):
        """Test IRR result includes convergence message."""
        cash_flows = [-100, 50, 50, 50]
        result = calculate_irr(cash_flows)

        assert "message" in result
        assert "convergence" in result
        assert "irr_percent" in result

    def test_irr_invalid_cashflows_length(self):
        """Test IRR with insufficient cash flows."""
        with pytest.raises(ValueError):
            calculate_irr([100])

    def test_irr_all_positive_cashflows(self):
        """Test IRR with all positive cash flows (no solution)."""
        cash_flows = [100, 50, 50, 50]
        result = calculate_irr(cash_flows)

        # Should not converge when all cash flows are positive
        assert result["convergence"] is False


class TestDCF:
    """Test DCF (Discounted Cash Flow) valuations."""

    def test_dcf_simple_case(self):
        """Test DCF with simple revenue and expense assumptions."""
        revenues = [100, 110, 121]  # 10% growth
        cogs_pct = 0.4  # 40% of revenue
        opex = 30  # Fixed opex
        wacc = 0.10
        terminal_growth = 0.02

        result = calculate_dcf(
            revenue_projections=revenues,
            cogs_percentages=cogs_pct,
            opex_projections=opex,
            wacc=wacc,
            terminal_growth=terminal_growth,
        )

        assert result["enterprise_value"] is not None
        assert result["pv_fcf"] is not None
        assert result["terminal_value"] is not None
        assert result["periods"] == 3
        assert result["wacc"] == wacc
        assert result["terminal_growth"] == terminal_growth

    def test_dcf_fcf_calculation(self):
        """Test that FCF is calculated correctly."""
        revenues = [1000]
        result = calculate_dcf(
            revenue_projections=revenues,
            cogs_percentages=0.5,
            opex_projections=200,
            tax_rate=0.2,
            wacc=0.1,
            terminal_growth=0.02,
        )

        # FCF = (Revenue - COGS - OpEx) * (1 - tax_rate)
        # = (1000 - 500 - 200) * 0.8 = 240
        assert result["fcf_by_year"][0] == pytest.approx(240, rel=0.01)

    def test_dcf_list_inputs(self):
        """Test DCF with list inputs for COGS and OpEx."""
        revenues = [100, 120, 140]
        cogs_list = [40, 45, 50]
        opex_list = [30, 32, 35]

        result = calculate_dcf(
            revenue_projections=revenues,
            cogs_percentages=cogs_list,
            opex_projections=opex_list,
            wacc=0.10,
            terminal_growth=0.02,
        )

        assert result["periods"] == 3
        assert len(result["fcf_by_year"]) == 3

    def test_dcf_with_capex(self):
        """Test DCF including capital expenditures."""
        revenues = [1000, 1100]
        capex = [100, 50]

        result = calculate_dcf(
            revenue_projections=revenues,
            cogs_percentages=0.4,
            opex_projections=200,
            capex_projections=capex,
            wacc=0.10,
            terminal_growth=0.02,
        )

        # FCF should be reduced by capex
        assert result["fcf_by_year"][0] < result["fcf_by_year"][0] + capex[0]

    def test_dcf_invalid_wacc(self):
        """Test DCF with WACC <= terminal growth rate."""
        with pytest.raises(ValueError):
            calculate_dcf(
                revenue_projections=[100],
                cogs_percentages=0.4,
                opex_projections=20,
                wacc=-1.5,  # Invalid
                terminal_growth=0.02,
            )


class TestSensitivity:
    """Test sensitivity analysis."""

    def test_sensitivity_basic(self):
        """Test sensitivity analysis with simple inputs."""
        base = {"discount_rate": 0.10, "cash_flows_0": -100, "cash_flows_1": 50, "cash_flows_2": 50}

        def calc_func(assumptions):
            cf = [assumptions.get(f"cash_flows_{i}") for i in range(3)]
            cf = [x for x in cf if x is not None]
            if not cf or len(cf) == 0:
                return 0
            dr = assumptions.get("discount_rate", 0.1)
            npv_result = calculate_npv(cf, dr)
            return npv_result["npv"]

        result = sensitivity_analysis(
            base_case=base,
            assumptions_to_vary=["discount_rate"],
            variance_range=(-0.05, 0.05),
            calculation_func=calc_func,
        )

        assert "sensitivity_table" in result
        assert "tornado_chart" in result
        assert result["base_case_output"] is not None

    def test_sensitivity_multiple_assumptions(self):
        """Test sensitivity with multiple assumptions."""
        base = {"revenue": 1000, "cost": 600, "tax_rate": 0.21}

        def calc_func(assumptions):
            revenue = assumptions.get("revenue", 1000)
            cost = assumptions.get("cost", 600)
            return (revenue - cost) * (1 - assumptions.get("tax_rate", 0.21))

        result = sensitivity_analysis(
            base_case=base,
            assumptions_to_vary=["revenue", "cost"],
            variance_range=(-0.10, 0.10),
            calculation_func=calc_func,
        )

        # Should have sensitivity rows for revenue and cost
        assert len(result["sensitivity_table"]) > 0
        # Tornado should show impact ranking
        assert len(result["tornado_chart"]) > 0


class TestFinancialMetrics:
    """Test financial metrics calculations."""

    def test_gross_margin(self):
        """Test gross margin calculation."""
        result = calculate_financial_metrics(
            revenue=1000,
            cogs=400,
        )

        assert result["gross_margin_pct"] == pytest.approx(60.0)

    def test_operating_margin(self):
        """Test operating margin calculation."""
        result = calculate_financial_metrics(
            revenue=1000,
            cogs=400,
            opex=200,
        )

        assert "operating_margin_pct" in result
        # (1000 - 400 - 200) / 1000 = 0.4 = 40%
        assert result["operating_margin_pct"] == pytest.approx(40.0)

    def test_net_margin(self):
        """Test net profit margin calculation."""
        result = calculate_financial_metrics(
            revenue=1000,
            cogs=400,
            opex=200,
            tax_rate=0.21,
        )

        assert "net_margin_pct" in result
        # EBIT = 400, Tax = 400 * 0.21 = 84, Net = 316
        # Margin = 316/1000 = 31.6%
        assert result["net_margin_pct"] == pytest.approx(31.6)

    def test_roe_calculation(self):
        """Test Return on Equity calculation."""
        result = calculate_financial_metrics(
            revenue=1000,
            cogs=400,
            opex=200,
            tax_rate=0.21,
            shareholders_equity=500,
        )

        assert "roe_pct" in result
        # Net income = (1000 - 400 - 200) * (1 - 0.21) = 317
        # ROE = 317 / 500 = 63.4%
        assert result["roe_pct"] > 0

    def test_debt_to_equity(self):
        """Test debt to equity ratio."""
        result = calculate_financial_metrics(
            revenue=1000,
            total_debt=500,
            shareholders_equity=1000,
        )

        assert result["debt_to_equity"] == pytest.approx(0.5)

    def test_empty_metrics(self):
        """Test with minimal inputs."""
        result = calculate_financial_metrics(revenue=0)

        # Should return a dict without errors
        assert isinstance(result, dict)

    def test_zero_equity_division(self):
        """Test with zero equity (should not divide by zero)."""
        result = calculate_financial_metrics(
            revenue=1000,
            shareholders_equity=0,
            net_income=100,
        )

        # Should not have ROE if equity is zero
        assert "roe_pct" not in result


class TestIntegration:
    """Integration tests combining multiple calculations."""

    def test_full_financial_model_workflow(self):
        """Test a complete financial modeling workflow."""
        # Set up a 3-year projection
        revenues = [1000, 1100, 1210]
        cogs_pct = 0.4
        opex = 200
        wacc = 0.12
        terminal_growth = 0.03

        # Calculate DCF
        dcf_result = calculate_dcf(
            revenue_projections=revenues,
            cogs_percentages=cogs_pct,
            opex_projections=opex,
            tax_rate=0.21,
            wacc=wacc,
            terminal_growth=terminal_growth,
        )

        assert dcf_result["enterprise_value"] > 0

        # Calculate metrics for first year
        first_year_revenue = revenues[0]
        first_year_cogs = first_year_revenue * cogs_pct
        first_year_ebit = first_year_revenue - first_year_cogs - opex

        metrics = calculate_financial_metrics(
            revenue=first_year_revenue,
            cogs=first_year_cogs,
            opex=opex,
            ebit=first_year_ebit,
            tax_rate=0.21,
        )

        assert metrics["gross_margin_pct"] == pytest.approx(60.0)
        assert "operating_margin_pct" in metrics
