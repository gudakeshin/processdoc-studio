"""Test suite for financial statement generation."""

import pytest

from app.services.financial_statements import (
    calculate_financial_ratios,
    generate_balance_sheet,
    generate_cash_flow_statement,
    generate_income_statement,
)


class TestIncomeStatement:
    """Test Income Statement generation."""

    def test_generate_income_statement_basic(self):
        """Test basic income statement generation."""
        revenues = [1000, 1100, 1210]
        cogs = 0.4  # 40% of revenue
        opex = [200, 220, 240]
        tax_rate = 0.21

        result = generate_income_statement(
            revenue_projections=revenues,
            cogs_projections=cogs,
            opex_projections=opex,
            tax_rate=tax_rate,
        )

        assert result["statement_type"] == "Income Statement (P&L)"
        assert result["period_count"] == 3
        assert "Revenue" in result["data"]
        assert "Gross Profit" in result["data"]
        assert "Net Income" in result["data"]

    def test_income_statement_calculations(self):
        """Test that income statement calculations are correct."""
        revenues = [1000]
        cogs = [400]  # 40% of revenue
        opex = [200]

        result = generate_income_statement(
            revenue_projections=revenues,
            cogs_projections=cogs,
            opex_projections=opex,
            tax_rate=0.21,
        )

        data = result["data"]
        # Verify key calculations
        assert data["Gross Profit"][0] == pytest.approx(600, rel=0.01)  # 1000 - 400
        assert data["EBITDA"][0] == pytest.approx(400, rel=0.01)  # 600 - 200
        assert data["EBIT"][0] == pytest.approx(400, rel=0.01)  # EBITDA + other income (0)

    def test_income_statement_with_list_inputs(self):
        """Test income statement with list inputs for COGS and OpEx."""
        revenues = [1000, 1100, 1200]
        cogs = [400, 420, 440]
        opex = [200, 220, 240]

        result = generate_income_statement(
            revenue_projections=revenues,
            cogs_projections=cogs,
            opex_projections=opex,
        )

        assert result["period_count"] == 3
        data = result["data"]
        assert len(data["Revenue"]) == 3
        assert data["Revenue"][0] == 1000

    def test_income_statement_margins(self):
        """Test that margins are calculated correctly."""
        revenues = [1000]
        cogs = [400]
        opex = [200]

        result = generate_income_statement(
            revenue_projections=revenues,
            cogs_projections=cogs,
            opex_projections=opex,
        )

        data = result["data"]
        # Gross margin = (1000 - 400) / 1000 = 60%
        assert data["Gross Margin %"][0] == pytest.approx(60.0)
        # Net margin = Net Income / Revenue
        # Net Income = 400 - 84 (taxes) = 316
        # Net Margin = 316 / 1000 = 31.6%
        assert data["Net Margin %"][0] == pytest.approx(31.6, rel=0.01)


class TestBalanceSheet:
    """Test Balance Sheet generation."""

    def test_generate_balance_sheet_basic(self):
        """Test basic balance sheet generation."""
        current_assets = [500, 550, 600]
        fixed_assets = [1000, 1050, 1100]
        current_liabilities = [200, 220, 240]
        long_term_debt = [500, 500, 500]
        equity = [800, 880, 960]

        result = generate_balance_sheet(
            current_assets=current_assets,
            fixed_assets=fixed_assets,
            current_liabilities=current_liabilities,
            long_term_debt=long_term_debt,
            shareholders_equity=equity,
        )

        assert result["statement_type"] == "Balance Sheet"
        assert result["period_count"] == 3
        data = result["data"]
        assert "Total Assets" in data
        assert "Total Liabilities" in data
        assert "Total Liabilities & Equity" in data

    def test_balance_sheet_balances(self):
        """Test that balance sheet balances (Assets = Liabilities + Equity)."""
        current_assets = [500]
        fixed_assets = [1000]
        current_liabilities = [300]
        long_term_debt = [500]
        equity = [700]

        result = generate_balance_sheet(
            current_assets=current_assets,
            fixed_assets=fixed_assets,
            current_liabilities=current_liabilities,
            long_term_debt=long_term_debt,
            shareholders_equity=equity,
        )

        data = result["data"]
        # Total Assets = 500 + 1000 = 1500
        assert data["Total Assets"][0] == pytest.approx(1500)
        # Total Liabilities & Equity = 300 + 500 + 700 = 1500
        assert data["Total Liabilities & Equity"][0] == pytest.approx(1500)
        # Balance check should be ✓
        assert data["Balance Check"][0] == "✓"

    def test_balance_sheet_scalar_inputs(self):
        """Test balance sheet with scalar inputs."""
        result = generate_balance_sheet(
            current_assets=500,
            fixed_assets=1000,
            current_liabilities=300,
            long_term_debt=500,
            shareholders_equity=700,
            periods=3,
        )

        assert result["period_count"] == 3
        data = result["data"]
        # All periods should have same values
        assert data["Current Assets"][0] == 500
        assert data["Current Assets"][2] == 500


class TestCashFlowStatement:
    """Test Cash Flow Statement generation."""

    def test_generate_cash_flow_statement_basic(self):
        """Test basic cash flow statement generation."""
        net_income = [300, 330, 363]
        capex = [100, 120, 140]

        result = generate_cash_flow_statement(
            net_income=net_income,
            capex_projections=capex,
        )

        assert result["statement_type"] == "Cash Flow Statement"
        assert result["period_count"] == 3
        data = result["data"]
        assert "Cash from Operations" in data
        assert "Cash from Investing" in data
        assert "Cash from Financing" in data
        assert "Net Change in Cash" in data

    def test_cash_flow_operations(self):
        """Test operating cash flow calculation."""
        net_income = [1000]
        capex = [200]
        wc_change = [100]

        result = generate_cash_flow_statement(
            net_income=net_income,
            capex_projections=capex,
            working_capital_change=wc_change,
        )

        data = result["data"]
        # Operating CF = NI + Adjustments + Change in WC = 1000 + 0 + (-100) = 900
        assert data["Cash from Operations"][0] == pytest.approx(900)
        # Investing CF = -CapEx = -200
        assert data["Cash from Investing"][0] == pytest.approx(-200)

    def test_cash_flow_cumulative(self):
        """Test cumulative cash calculation."""
        net_income = [500, 500, 500]
        capex = [100, 100, 100]

        result = generate_cash_flow_statement(
            net_income=net_income,
            capex_projections=capex,
        )

        data = result["data"]
        # Check cumulative increases each period
        cum_cash = data["Cumulative Cash"]
        assert cum_cash[0] < cum_cash[1] < cum_cash[2]

    def test_cash_flow_with_financing(self):
        """Test cash flow with debt and equity issuance."""
        net_income = [500]
        capex = [200]
        debt_issuance = [100]
        equity_issuance = [50]

        result = generate_cash_flow_statement(
            net_income=net_income,
            capex_projections=capex,
            debt_issuance=debt_issuance,
            equity_issuance=equity_issuance,
        )

        data = result["data"]
        # Financing CF = Debt + Equity = 100 + 50 = 150
        assert data["Cash from Financing"][0] == pytest.approx(150)


class TestFinancialRatios:
    """Test financial ratio calculation."""

    def test_calculate_ratios_from_statements(self):
        """Test calculating ratios from complete statements."""
        # Create income statement
        income_statement = generate_income_statement(
            revenue_projections=[1000],
            cogs_projections=0.4,
            opex_projections=200,
            tax_rate=0.21,
        )

        # Create balance sheet
        balance_sheet = generate_balance_sheet(
            current_assets=500,
            fixed_assets=1000,
            current_liabilities=300,
            long_term_debt=500,
            shareholders_equity=700,
            periods=1,
        )

        result = calculate_financial_ratios(income_statement, balance_sheet, periods=1)

        ratios = result["ratios"]
        assert "net_margin_pct" in ratios
        assert "gross_margin_pct" in ratios
        assert "roe_pct" in ratios
        assert "roa_pct" in ratios
        assert "current_ratio" in ratios
        assert "debt_to_equity" in ratios

    def test_ratio_calculations(self):
        """Test that individual ratios are calculated correctly."""
        income_statement = generate_income_statement(
            revenue_projections=[1000],
            cogs_projections=0.4,
            opex_projections=200,
        )

        balance_sheet = generate_balance_sheet(
            current_assets=500,
            fixed_assets=1000,
            current_liabilities=200,
            long_term_debt=500,
            shareholders_equity=800,
            periods=1,
        )

        result = calculate_financial_ratios(income_statement, balance_sheet, periods=1)
        ratios = result["ratios"]

        # Check current ratio: 500 / 200 = 2.5
        assert ratios["current_ratio"][0] == pytest.approx(2.5)

        # Check debt to equity: 500 / 800 = 0.625, rounded to 0.62
        assert ratios["debt_to_equity"][0] == pytest.approx(0.62, rel=0.05)


class TestIntegration:
    """Integration tests for financial statements."""

    def test_complete_financial_model(self):
        """Test generating a complete set of financial statements."""
        # Project revenues
        revenues = [1000, 1100, 1210, 1331, 1464]

        # Generate Income Statement
        pl = generate_income_statement(
            revenue_projections=revenues,
            cogs_projections=0.4,  # 40% of revenue
            opex_projections=[200, 220, 240, 260, 280],
            tax_rate=0.21,
        )

        # Extract net income
        net_income = pl["data"]["Net Income"]

        # Generate Balance Sheet
        bs = generate_balance_sheet(
            current_assets=[500, 550, 605, 666, 732],
            fixed_assets=[1000, 1050, 1100, 1150, 1200],
            current_liabilities=[200, 220, 242, 266, 293],
            long_term_debt=[500, 500, 500, 500, 500],
            shareholders_equity=[800, 880, 963, 1050, 1146],
        )

        # Generate Cash Flow Statement
        cf = generate_cash_flow_statement(
            net_income=net_income,
            capex_projections=[100, 110, 121, 133, 146],
        )

        # Calculate ratios
        ratios = calculate_financial_ratios(pl, bs)

        # Verify complete structure
        assert pl["period_count"] == 5
        assert bs["period_count"] == 5
        assert cf["period_count"] == 5
        assert ratios["period_count"] == 5

        # Verify key outputs
        assert len(pl["data"]["Net Income"]) == 5
        assert len(cf["data"]["Net Change in Cash"]) == 5
        assert "roe_pct" in ratios["ratios"]
