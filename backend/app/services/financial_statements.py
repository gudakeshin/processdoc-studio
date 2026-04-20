"""Financial statement generation service (P&L, Balance Sheet, Cash Flow)."""

from datetime import UTC, datetime
from typing import Any


def _now_iso() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now(UTC).isoformat()


def generate_income_statement(
    revenue_projections: list[float],
    cogs_projections: list[float] | float,
    opex_projections: list[float] | float,
    other_income: list[float] | float = 0,
    tax_rate: float = 0.21,
    periods: int = 5,
) -> dict[str, Any]:
    """
    Generate an Income Statement (P&L) projection.

    Args:
        revenue_projections: List of projected revenues
        cogs_projections: Cost of goods sold (scalar or list)
        opex_projections: Operating expenses (scalar or list)
        other_income: Other income items (scalar or list)
        tax_rate: Tax rate for income tax calculation
        periods: Number of periods to project

    Returns:
        Dictionary with:
            - line_items: Row labels
            - periods: Column period numbers (1-N)
            - data: 2D array of values
            - calculations: Formulas used for each row
    """
    # Normalize inputs to lists
    if isinstance(cogs_projections, (int, float)):
        cogs_projections = [cogs_projections] * periods
    if isinstance(opex_projections, (int, float)):
        opex_projections = [opex_projections] * periods
    if isinstance(other_income, (int, float)):
        other_income = [other_income] * periods

    periods = len(revenue_projections)
    data = {}

    # Revenue
    data["Revenue"] = [round(r, 2) for r in revenue_projections]

    # Cost of Goods Sold
    data["Cost of Goods Sold"] = [round(cogs_projections[i], 2) for i in range(periods)]

    # Gross Profit
    data["Gross Profit"] = [
        round(data["Revenue"][i] - data["Cost of Goods Sold"][i], 2)
        for i in range(periods)
    ]

    # Gross Margin %
    data["Gross Margin %"] = [
        round((data["Gross Profit"][i] / data["Revenue"][i] * 100) if data["Revenue"][i] != 0 else 0, 1)
        for i in range(periods)
    ]

    # Operating Expenses
    data["Operating Expenses"] = [round(opex_projections[i], 2) for i in range(periods)]

    # EBITDA (assuming no depreciation/amortization)
    data["EBITDA"] = [
        round(data["Gross Profit"][i] - data["Operating Expenses"][i], 2)
        for i in range(periods)
    ]

    # Other Income
    data["Other Income"] = [round(other_income[i], 2) for i in range(periods)]

    # EBIT (Operating Income)
    data["EBIT"] = [
        round(data["EBITDA"][i] + data["Other Income"][i], 2)
        for i in range(periods)
    ]

    # Income Tax
    data["Income Tax"] = [
        round(max(0, data["EBIT"][i]) * tax_rate, 2)
        for i in range(periods)
    ]

    # Net Income
    data["Net Income"] = [
        round(data["EBIT"][i] - data["Income Tax"][i], 2)
        for i in range(periods)
    ]

    # Net Margin %
    data["Net Margin %"] = [
        round((data["Net Income"][i] / data["Revenue"][i] * 100) if data["Revenue"][i] != 0 else 0, 1)
        for i in range(periods)
    ]

    return {
        "statement_type": "Income Statement (P&L)",
        "line_items": list(data.keys()),
        "period_count": periods,
        "data": data,
        "tax_rate": tax_rate,
        "generated_at": _now_iso(),
    }


def generate_balance_sheet(
    current_assets: list[float] | float,
    fixed_assets: list[float] | float,
    current_liabilities: list[float] | float,
    long_term_debt: list[float] | float,
    shareholders_equity: list[float] | float,
    periods: int = 5,
) -> dict[str, Any]:
    """
    Generate a Balance Sheet projection.

    Args:
        current_assets: Current assets (cash, AR, inventory)
        fixed_assets: Fixed assets (PP&E, net)
        current_liabilities: Current liabilities (AP, short-term debt)
        long_term_debt: Long-term debt
        shareholders_equity: Shareholder equity
        periods: Number of periods

    Returns:
        Dictionary with balance sheet structure and calculations
    """
    # Normalize inputs
    if isinstance(current_assets, (int, float)):
        current_assets = [current_assets] * periods
    if isinstance(fixed_assets, (int, float)):
        fixed_assets = [fixed_assets] * periods
    if isinstance(current_liabilities, (int, float)):
        current_liabilities = [current_liabilities] * periods
    if isinstance(long_term_debt, (int, float)):
        long_term_debt = [long_term_debt] * periods
    if isinstance(shareholders_equity, (int, float)):
        shareholders_equity = [shareholders_equity] * periods

    periods = len(current_assets)
    data = {}

    # ASSETS
    data["Current Assets"] = [round(current_assets[i], 2) for i in range(periods)]
    data["Fixed Assets"] = [round(fixed_assets[i], 2) for i in range(periods)]
    data["Total Assets"] = [
        round(data["Current Assets"][i] + data["Fixed Assets"][i], 2)
        for i in range(periods)
    ]

    # LIABILITIES
    data["Current Liabilities"] = [round(current_liabilities[i], 2) for i in range(periods)]
    data["Long-term Debt"] = [round(long_term_debt[i], 2) for i in range(periods)]
    data["Total Liabilities"] = [
        round(data["Current Liabilities"][i] + data["Long-term Debt"][i], 2)
        for i in range(periods)
    ]

    # EQUITY
    data["Shareholders' Equity"] = [round(shareholders_equity[i], 2) for i in range(periods)]
    data["Total Liabilities & Equity"] = [
        round(data["Total Liabilities"][i] + data["Shareholders' Equity"][i], 2)
        for i in range(periods)
    ]

    # Validation
    data["Balance Check"] = [
        "✓" if abs(data["Total Assets"][i] - data["Total Liabilities & Equity"][i]) < 0.01 else "✗"
        for i in range(periods)
    ]

    return {
        "statement_type": "Balance Sheet",
        "line_items": list(data.keys()),
        "period_count": periods,
        "data": data,
        "generated_at": _now_iso(),
    }


def generate_cash_flow_statement(
    net_income: list[float],
    capex_projections: list[float] | float,
    working_capital_change: list[float] | float = 0,
    debt_issuance: list[float] | float = 0,
    equity_issuance: list[float] | float = 0,
    periods: int = 5,
) -> dict[str, Any]:
    """
    Generate a Cash Flow Statement projection.

    Args:
        net_income: Net income from operations
        capex_projections: Capital expenditures
        working_capital_change: Change in working capital
        debt_issuance: New debt issued
        equity_issuance: New equity issued
        periods: Number of periods

    Returns:
        Dictionary with cash flow statement structure
    """
    # Normalize inputs
    if isinstance(capex_projections, (int, float)):
        capex_projections = [capex_projections] * periods
    if isinstance(working_capital_change, (int, float)):
        working_capital_change = [working_capital_change] * periods
    if isinstance(debt_issuance, (int, float)):
        debt_issuance = [debt_issuance] * periods
    if isinstance(equity_issuance, (int, float)):
        equity_issuance = [equity_issuance] * periods

    periods = len(net_income)
    data = {}

    # OPERATING ACTIVITIES
    data["Net Income"] = [round(ni, 2) for ni in net_income]
    # Assuming no depreciation, amortization, or other adjustments for simplicity
    data["Adjustments"] = [0.0] * periods
    data["Change in Working Capital"] = [round(-wc, 2) for wc in working_capital_change]
    data["Cash from Operations"] = [
        round(data["Net Income"][i] + data["Adjustments"][i] + data["Change in Working Capital"][i], 2)
        for i in range(periods)
    ]

    # INVESTING ACTIVITIES
    data["Capital Expenditures"] = [round(-capex, 2) for capex in capex_projections]
    data["Cash from Investing"] = [round(data["Capital Expenditures"][i], 2) for i in range(periods)]

    # FINANCING ACTIVITIES
    data["Debt Issuance"] = [round(debt, 2) for debt in debt_issuance]
    data["Equity Issuance"] = [round(equity, 2) for equity in equity_issuance]
    data["Cash from Financing"] = [
        round(data["Debt Issuance"][i] + data["Equity Issuance"][i], 2)
        for i in range(periods)
    ]

    # NET CHANGE IN CASH
    data["Net Change in Cash"] = [
        round(
            data["Cash from Operations"][i]
            + data["Cash from Investing"][i]
            + data["Cash from Financing"][i],
            2,
        )
        for i in range(periods)
    ]

    # Cumulative cash
    cumulative = 0.0
    data["Cumulative Cash"] = []
    for i in range(periods):
        cumulative += data["Net Change in Cash"][i]
        data["Cumulative Cash"].append(round(cumulative, 2))

    return {
        "statement_type": "Cash Flow Statement",
        "line_items": list(data.keys()),
        "period_count": periods,
        "data": data,
        "generated_at": _now_iso(),
    }


def calculate_financial_ratios(
    income_statement: dict[str, Any],
    balance_sheet: dict[str, Any],
    periods: int = None,
) -> dict[str, Any]:
    """
    Calculate key financial ratios from statements.

    Args:
        income_statement: Income statement dictionary
        balance_sheet: Balance sheet dictionary
        periods: Number of periods to calculate (default: all)

    Returns:
        Dictionary with calculated ratios
    """
    ratios = {}

    # Profitability Ratios
    if "Net Margin %" in income_statement.get("data", {}):
        ratios["net_margin_pct"] = income_statement["data"]["Net Margin %"]

    if "Gross Margin %" in income_statement.get("data", {}):
        ratios["gross_margin_pct"] = income_statement["data"]["Gross Margin %"]

    # ROE
    net_income = income_statement.get("data", {}).get("Net Income", [])
    equity = balance_sheet.get("data", {}).get("Shareholders' Equity", [])
    if net_income and equity:
        ratios["roe_pct"] = [
            round((net_income[i] / equity[i] * 100) if equity[i] != 0 else 0, 1)
            for i in range(len(net_income))
        ]

    # ROA
    assets = balance_sheet.get("data", {}).get("Total Assets", [])
    if net_income and assets:
        ratios["roa_pct"] = [
            round((net_income[i] / assets[i] * 100) if assets[i] != 0 else 0, 1)
            for i in range(len(net_income))
        ]

    # Liquidity Ratios
    current_assets = balance_sheet.get("data", {}).get("Current Assets", [])
    current_liabilities = balance_sheet.get("data", {}).get("Current Liabilities", [])
    if current_assets and current_liabilities:
        ratios["current_ratio"] = [
            round(current_assets[i] / current_liabilities[i] if current_liabilities[i] != 0 else 0, 2)
            for i in range(len(current_assets))
        ]

    # Leverage Ratios
    total_debt = balance_sheet.get("data", {}).get("Long-term Debt", [])
    if equity and total_debt:
        ratios["debt_to_equity"] = [
            round(total_debt[i] / equity[i] if equity[i] != 0 else 0, 2)
            for i in range(len(total_debt))
        ]

    return {
        "ratios": ratios,
        "period_count": periods or len(list(ratios.values())[0]) if ratios else 0,
        "calculated_at": _now_iso(),
    }
