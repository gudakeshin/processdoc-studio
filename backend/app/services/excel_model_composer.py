"""Excel Financial Model Composer.

Orchestrates existing financial services into a professional, multi-sheet,
formula-driven Excel financial model.  Returns a list of ``xlsx_cells`` dicts
compatible with ``apply_cells_to_workbook()`` in ``deliverable_xlsx.py``.

No new financial logic lives here — this module is a pure *composer*.
"""

from __future__ import annotations

import contextlib
import logging
import math
import time
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Formatting constants (per xlsx_v1 SKILL.md)
# ---------------------------------------------------------------------------

BLUE_INPUT = "0000FF"       # Hardcoded inputs / assumptions
BLACK_CALC = "000000"       # Formulas & calculations
GREEN_LINK = "008000"       # Cross-sheet references
YELLOW_BG = "FFFF00"        # Key assumptions needing attention
HEADER_BG = "D9E1F2"        # Section headers (light blue)
SUBTOTAL_BG = "E2EFDA"      # Sub-total rows (light green)

FMT_CURRENCY = '$#,##0;($#,##0);"-"'
FMT_PERCENT = "0.0%"
FMT_RATIO = "0.00"
FMT_INTEGER = "#,##0"
FMT_MULTIPLE = '0.0"x"'

# Key assumptions that get yellow highlight
KEY_ASSUMPTIONS = {
    "revenue", "growth_rate", "revenue_growth_rate",
    "tax_rate", "discount_rate", "wacc",
}

# Canonical assumption ordering and display labels
ASSUMPTION_ORDER = [
    ("revenue", "Revenue", FMT_CURRENCY, True),
    ("growth_rate", "Revenue Growth Rate", FMT_PERCENT, True),
    ("revenue_growth_rate", "Revenue Growth Rate", FMT_PERCENT, True),
    ("cogs_pct", "COGS (% of Revenue)", FMT_PERCENT, False),
    ("cogs", "COGS (% of Revenue)", FMT_PERCENT, False),
    ("opex", "Operating Expenses", FMT_CURRENCY, False),
    ("tax_rate", "Tax Rate", FMT_PERCENT, True),
    ("discount_rate", "Discount Rate (WACC)", FMT_PERCENT, False),
    ("wacc", "Discount Rate (WACC)", FMT_PERCENT, False),
    ("terminal_growth", "Terminal Growth Rate", FMT_PERCENT, False),
    ("terminal_growth_rate", "Terminal Growth Rate", FMT_PERCENT, False),
    ("capex", "Capital Expenditure", FMT_CURRENCY, False),
    ("depreciation", "Depreciation & Amortization", FMT_CURRENCY, False),
    ("current_assets", "Current Assets", FMT_CURRENCY, False),
    ("fixed_assets", "Fixed Assets (PP&E)", FMT_CURRENCY, False),
    ("current_liabilities", "Current Liabilities", FMT_CURRENCY, False),
    ("long_term_debt", "Long-term Debt", FMT_CURRENCY, False),
    ("shareholders_equity", "Shareholders' Equity", FMT_CURRENCY, False),
    ("working_capital_change", "Working Capital Change", FMT_CURRENCY, False),
    ("cash", "Cash & Equivalents", FMT_CURRENCY, False),
    ("total_assets", "Total Assets", FMT_CURRENCY, False),
    ("total_debt", "Total Debt", FMT_CURRENCY, False),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _col_letter(col_num: int) -> str:
    """Convert 1-based column number to Excel letter(s).  1→A, 27→AA."""
    result = ""
    while col_num > 0:
        col_num, remainder = divmod(col_num - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _cell(
    sheet: str,
    row: int,
    col: int,
    *,
    value: Any = None,
    formula: str | None = None,
    bold: bool = False,
    font_color: str | None = None,
    fill_color: str | None = None,
    number_format: str | None = None,
) -> dict[str, Any]:
    """Build a single xlsx_cell dict."""
    c: dict[str, Any] = {"sheet": sheet, "row": row, "col": col}
    if formula is not None:
        c["formula"] = formula
    elif value is not None:
        c["value"] = value
    if bold:
        c["bold"] = True
    if font_color:
        c["font_color"] = font_color
    if fill_color:
        c["fill_color"] = fill_color
    if number_format:
        c["number_format"] = number_format
    return c


def _safe_div(numerator: str, denominator: str) -> str:
    """Return an Excel formula fragment that avoids #DIV/0!."""
    return f"IF({denominator}=0,0,{numerator}/{denominator})"


def _resolve_assumption(assumptions: dict, *keys: str, default: float | None = None) -> float | None:
    """Look up the first matching key in assumptions.

    Raises:
        ValueError: If the value is NaN or Infinity.
    """
    for k in keys:
        if k in assumptions:
            try:
                val = float(assumptions[k])
                if math.isnan(val):
                    raise ValueError(f"Assumption '{k}' is NaN (not a number)")
                if math.isinf(val):
                    raise ValueError(f"Assumption '{k}' is infinite")
                return val
            except (TypeError, ValueError) as e:
                if isinstance(e, ValueError) and ("NaN" in str(e) or "infinite" in str(e)):
                    raise
                log.warning(f"Assumption '{k}' is not numeric (value={assumptions[k]}, type={type(assumptions[k]).__name__}), treating as None")
                pass
    return default


# ---------------------------------------------------------------------------
# Sheet Composers
# ---------------------------------------------------------------------------

SH_ASSUMPTIONS = "Assumptions"
SH_INCOME = "Income Statement"
SH_BALANCE = "Balance Sheet"
SH_CASHFLOW = "Cash Flow"
SH_RATIOS = "Financial Ratios"
SH_VALUATION = "Valuation"
SH_SCENARIOS = "Scenarios"
SH_FORECAST = "Forecast"
SH_BUDGET = "Budget vs Actual"
SH_DASHBOARD = "Dashboard"


def _compose_assumptions_sheet(
    assumptions: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Build the Assumptions sheet and return (cells, ref_map).

    ``ref_map`` maps assumption keys to their Excel address
    (e.g. ``{"revenue": "Assumptions!B3"}``).
    """
    cells: list[dict[str, Any]] = []
    ref_map: dict[str, str] = {}

    # Title row
    cells.append(_cell(SH_ASSUMPTIONS, 1, 1, value="Financial Model Assumptions",
                        bold=True, fill_color=HEADER_BG))
    cells.append(_cell(SH_ASSUMPTIONS, 1, 2, value="", fill_color=HEADER_BG))

    # Column headers
    cells.append(_cell(SH_ASSUMPTIONS, 2, 1, value="Assumption", bold=True))
    cells.append(_cell(SH_ASSUMPTIONS, 2, 2, value="Value", bold=True))

    row = 3
    placed_keys: set[str] = set()

    # Place assumptions in canonical order first
    for key, label, fmt, is_key in ASSUMPTION_ORDER:
        if key not in assumptions or key in placed_keys:
            continue
        placed_keys.add(key)

        val = assumptions[key]
        with contextlib.suppress(TypeError, ValueError):
            val = float(val)

        fill = YELLOW_BG if (is_key or key in KEY_ASSUMPTIONS) else None
        cells.append(_cell(SH_ASSUMPTIONS, row, 1, value=label))
        cells.append(_cell(SH_ASSUMPTIONS, row, 2, value=val,
                            font_color=BLUE_INPUT, fill_color=fill,
                            number_format=fmt))
        ref_map[key] = f"{SH_ASSUMPTIONS}!B{row}"
        row += 1

    # Place remaining assumptions not in canonical order
    for key, val in assumptions.items():
        if key in placed_keys or key == "historical_data":
            continue
        placed_keys.add(key)

        with contextlib.suppress(TypeError, ValueError):
            val = float(val)

        display_name = key.replace("_", " ").title()
        cells.append(_cell(SH_ASSUMPTIONS, row, 1, value=display_name))
        cells.append(_cell(SH_ASSUMPTIONS, row, 2, value=val,
                            font_color=BLUE_INPUT))
        ref_map[key] = f"{SH_ASSUMPTIONS}!B{row}"
        row += 1

    return cells, ref_map


def _compose_income_statement(
    ref_map: dict[str, str],
    periods: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Build the Income Statement sheet with real Excel formulas.

    Returns (cells, row_map) where row_map maps line-item keys to their row numbers.
    """
    cells: list[dict[str, Any]] = []
    row_map: dict[str, int] = {}
    sheet = SH_INCOME

    # Resolve assumption refs
    rev_ref = ref_map.get("revenue", "0")
    growth_ref = ref_map.get("growth_rate") or ref_map.get("revenue_growth_rate", "0")
    cogs_ref = ref_map.get("cogs_pct") or ref_map.get("cogs", "0")
    opex_ref = ref_map.get("opex", "0")
    tax_ref = ref_map.get("tax_rate", "0")

    # Title row
    cells.append(_cell(sheet, 1, 1, value="Income Statement", bold=True, fill_color=HEADER_BG))
    for p in range(periods):
        cells.append(_cell(sheet, 1, p + 2, value=f"Year {p + 1}", bold=True, fill_color=HEADER_BG))

    # Line items start at row 3
    r = 3

    # --- Revenue ---
    row_map["revenue"] = r
    cells.append(_cell(sheet, r, 1, value="Revenue", bold=True))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        if p == 0:
            cells.append(_cell(sheet, r, col, formula=rev_ref,
                                font_color=GREEN_LINK, number_format=FMT_CURRENCY))
        else:
            prev_cl = _col_letter(col - 1)
            cells.append(_cell(sheet, r, col,
                                formula=f"{prev_cl}{r}*(1+{growth_ref})",
                                font_color=BLACK_CALC, number_format=FMT_CURRENCY))
    r += 1

    # --- COGS ---
    row_map["cogs"] = r
    cells.append(_cell(sheet, r, 1, value="Cost of Goods Sold"))
    rev_row = row_map["revenue"]
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        cells.append(_cell(sheet, r, col,
                            formula=f"{cl}{rev_row}*{cogs_ref}",
                            font_color=BLACK_CALC, number_format=FMT_CURRENCY))
    r += 1

    # --- Gross Profit ---
    row_map["gross_profit"] = r
    cells.append(_cell(sheet, r, 1, value="Gross Profit", bold=True, fill_color=SUBTOTAL_BG))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        cells.append(_cell(sheet, r, col,
                            formula=f"{cl}{row_map['revenue']}-{cl}{row_map['cogs']}",
                            bold=True, font_color=BLACK_CALC,
                            fill_color=SUBTOTAL_BG, number_format=FMT_CURRENCY))
    r += 1

    # --- Gross Margin % ---
    row_map["gross_margin"] = r
    cells.append(_cell(sheet, r, 1, value="Gross Margin %"))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        cells.append(_cell(sheet, r, col,
                            formula=_safe_div(f"{cl}{row_map['gross_profit']}",
                                              f"{cl}{row_map['revenue']}"),
                            font_color=BLACK_CALC, number_format=FMT_PERCENT))
    r += 1

    # --- Operating Expenses ---
    row_map["opex"] = r
    cells.append(_cell(sheet, r, 1, value="Operating Expenses"))
    for p in range(periods):
        col = p + 2
        if p == 0:
            cells.append(_cell(sheet, r, col, formula=opex_ref,
                                font_color=GREEN_LINK, number_format=FMT_CURRENCY))
        else:
            prev_cl = _col_letter(col - 1)
            cells.append(_cell(sheet, r, col,
                                formula=f"{prev_cl}{r}*(1+{growth_ref})",
                                font_color=BLACK_CALC, number_format=FMT_CURRENCY))
    r += 1

    # --- EBITDA ---
    row_map["ebitda"] = r
    cells.append(_cell(sheet, r, 1, value="EBITDA", bold=True, fill_color=SUBTOTAL_BG))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        cells.append(_cell(sheet, r, col,
                            formula=f"{cl}{row_map['gross_profit']}-{cl}{row_map['opex']}",
                            bold=True, font_color=BLACK_CALC,
                            fill_color=SUBTOTAL_BG, number_format=FMT_CURRENCY))
    r += 1

    # --- Depreciation (if available) ---
    dep_ref = ref_map.get("depreciation")
    if dep_ref:
        row_map["depreciation"] = r
        cells.append(_cell(sheet, r, 1, value="Depreciation & Amortization"))
        for p in range(periods):
            col = p + 2
            cells.append(_cell(sheet, r, col, formula=dep_ref,
                                font_color=GREEN_LINK, number_format=FMT_CURRENCY))
        r += 1

    # --- EBIT ---
    row_map["ebit"] = r
    cells.append(_cell(sheet, r, 1, value="EBIT (Operating Income)", bold=True))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        if "depreciation" in row_map:
            cells.append(_cell(sheet, r, col,
                                formula=f"{cl}{row_map['ebitda']}-{cl}{row_map['depreciation']}",
                                bold=True, font_color=BLACK_CALC, number_format=FMT_CURRENCY))
        else:
            cells.append(_cell(sheet, r, col,
                                formula=f"{cl}{row_map['ebitda']}",
                                bold=True, font_color=BLACK_CALC, number_format=FMT_CURRENCY))
    r += 1

    # --- Income Tax ---
    row_map["tax"] = r
    cells.append(_cell(sheet, r, 1, value="Income Tax"))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        cells.append(_cell(sheet, r, col,
                            formula=f"MAX(0,{cl}{row_map['ebit']})*{tax_ref}",
                            font_color=BLACK_CALC, number_format=FMT_CURRENCY))
    r += 1

    # --- Net Income ---
    row_map["net_income"] = r
    cells.append(_cell(sheet, r, 1, value="Net Income", bold=True, fill_color=SUBTOTAL_BG))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        cells.append(_cell(sheet, r, col,
                            formula=f"{cl}{row_map['ebit']}-{cl}{row_map['tax']}",
                            bold=True, font_color=BLACK_CALC,
                            fill_color=SUBTOTAL_BG, number_format=FMT_CURRENCY))
    r += 1

    # --- Net Margin % ---
    row_map["net_margin"] = r
    cells.append(_cell(sheet, r, 1, value="Net Margin %"))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        cells.append(_cell(sheet, r, col,
                            formula=_safe_div(f"{cl}{row_map['net_income']}",
                                              f"{cl}{row_map['revenue']}"),
                            font_color=BLACK_CALC, number_format=FMT_PERCENT))

    return cells, row_map


def _compose_balance_sheet(
    ref_map: dict[str, str],
    periods: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Build the Balance Sheet with formula-driven projections."""
    cells: list[dict[str, Any]] = []
    row_map: dict[str, int] = {}
    sheet = SH_BALANCE
    growth_ref = ref_map.get("growth_rate") or ref_map.get("revenue_growth_rate", "0")

    # Title
    cells.append(_cell(sheet, 1, 1, value="Balance Sheet", bold=True, fill_color=HEADER_BG))
    for p in range(periods):
        cells.append(_cell(sheet, 1, p + 2, value=f"Year {p + 1}", bold=True, fill_color=HEADER_BG))

    r = 3

    # Assets section
    cells.append(_cell(sheet, r, 1, value="ASSETS", bold=True, fill_color=HEADER_BG))
    for p in range(periods):
        cells.append(_cell(sheet, r, p + 2, value="", fill_color=HEADER_BG))
    r += 1

    def _projection_row(label: str, key: str, ref_key: str, bold_row: bool = False) -> int:
        nonlocal r
        row_map[key] = r
        cells.append(_cell(sheet, r, 1, value=label, bold=bold_row))
        ref = ref_map.get(ref_key)
        for p in range(periods):
            col = p + 2
            if p == 0 and ref:
                cells.append(_cell(sheet, r, col, formula=ref,
                                    font_color=GREEN_LINK, number_format=FMT_CURRENCY))
            elif p == 0:
                cells.append(_cell(sheet, r, col, value=0, number_format=FMT_CURRENCY))
            else:
                prev = _col_letter(col - 1)
                cells.append(_cell(sheet, r, col,
                                    formula=f"{prev}{r}*(1+{growth_ref})",
                                    font_color=BLACK_CALC, number_format=FMT_CURRENCY))
        r += 1
        return r - 1

    _projection_row("Current Assets", "current_assets", "current_assets")
    _projection_row("Fixed Assets (PP&E)", "fixed_assets", "fixed_assets")

    # Total Assets
    row_map["total_assets"] = r
    cells.append(_cell(sheet, r, 1, value="Total Assets", bold=True, fill_color=SUBTOTAL_BG))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        cells.append(_cell(sheet, r, col,
                            formula=f"{cl}{row_map['current_assets']}+{cl}{row_map['fixed_assets']}",
                            bold=True, font_color=BLACK_CALC,
                            fill_color=SUBTOTAL_BG, number_format=FMT_CURRENCY))
    r += 2  # blank row

    # Liabilities section
    cells.append(_cell(sheet, r, 1, value="LIABILITIES & EQUITY", bold=True, fill_color=HEADER_BG))
    for p in range(periods):
        cells.append(_cell(sheet, r, p + 2, value="", fill_color=HEADER_BG))
    r += 1

    _projection_row("Current Liabilities", "current_liabilities", "current_liabilities")
    _projection_row("Long-term Debt", "long_term_debt", "long_term_debt")

    # Total Liabilities
    row_map["total_liabilities"] = r
    cells.append(_cell(sheet, r, 1, value="Total Liabilities", bold=True))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        cells.append(_cell(sheet, r, col,
                            formula=f"{cl}{row_map['current_liabilities']}+{cl}{row_map['long_term_debt']}",
                            bold=True, font_color=BLACK_CALC, number_format=FMT_CURRENCY))
    r += 1

    _projection_row("Shareholders' Equity", "equity", "shareholders_equity")

    # Total L&E
    row_map["total_le"] = r
    cells.append(_cell(sheet, r, 1, value="Total Liabilities & Equity", bold=True, fill_color=SUBTOTAL_BG))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        cells.append(_cell(sheet, r, col,
                            formula=f"{cl}{row_map['total_liabilities']}+{cl}{row_map['equity']}",
                            bold=True, font_color=BLACK_CALC,
                            fill_color=SUBTOTAL_BG, number_format=FMT_CURRENCY))
    r += 1

    # Balance Check
    row_map["balance_check"] = r
    cells.append(_cell(sheet, r, 1, value="Balance Check (should be 0)", bold=True))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        cells.append(_cell(sheet, r, col,
                            formula=f"{cl}{row_map['total_assets']}-{cl}{row_map['total_le']}",
                            bold=True, font_color=BLACK_CALC, number_format=FMT_CURRENCY))

    return cells, row_map


def _compose_cash_flow(
    ref_map: dict[str, str],
    is_row_map: dict[str, int],
    periods: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Build the Cash Flow Statement with cross-sheet references."""
    cells: list[dict[str, Any]] = []
    row_map: dict[str, int] = {}
    sheet = SH_CASHFLOW

    capex_ref = ref_map.get("capex", "0")
    wc_ref = ref_map.get("working_capital_change", "0")

    # Title
    cells.append(_cell(sheet, 1, 1, value="Cash Flow Statement", bold=True, fill_color=HEADER_BG))
    for p in range(periods):
        cells.append(_cell(sheet, 1, p + 2, value=f"Year {p + 1}", bold=True, fill_color=HEADER_BG))

    r = 3

    # --- Operating Activities ---
    cells.append(_cell(sheet, r, 1, value="OPERATING ACTIVITIES", bold=True, fill_color=HEADER_BG))
    for p in range(periods):
        cells.append(_cell(sheet, r, p + 2, value="", fill_color=HEADER_BG))
    r += 1

    # Net Income (cross-sheet ref)
    ni_row = is_row_map.get("net_income", 0)

    # Phase 1 Hardening: Validate row reference before using in formula
    if ni_row <= 0:
        log.warning("Cash Flow sheet: net_income row not found in Income Statement, skipping sheet")
        return [], {}

    row_map["net_income"] = r
    cells.append(_cell(sheet, r, 1, value="Net Income"))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        cells.append(_cell(sheet, r, col,
                            formula=f"'{SH_INCOME}'!{cl}{ni_row}",
                            font_color=GREEN_LINK, number_format=FMT_CURRENCY))
    r += 1

    # D&A add-back
    dep_ref = ref_map.get("depreciation")
    if dep_ref:
        row_map["da_addback"] = r
        cells.append(_cell(sheet, r, 1, value="Add: Depreciation & Amortization"))
        for p in range(periods):
            cells.append(_cell(sheet, r, p + 2, formula=dep_ref,
                                font_color=GREEN_LINK, number_format=FMT_CURRENCY))
        r += 1

    # Working Capital Change
    row_map["wc_change"] = r
    cells.append(_cell(sheet, r, 1, value="Change in Working Capital"))
    for p in range(periods):
        col = p + 2
        if wc_ref != "0":
            cells.append(_cell(sheet, r, col, formula=f"-{wc_ref}",
                                font_color=GREEN_LINK, number_format=FMT_CURRENCY))
        else:
            cells.append(_cell(sheet, r, col, value=0, number_format=FMT_CURRENCY))
    r += 1

    # Cash from Operations
    row_map["cfo"] = r
    cells.append(_cell(sheet, r, 1, value="Cash from Operations", bold=True, fill_color=SUBTOTAL_BG))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        parts = [f"{cl}{row_map['net_income']}"]
        if "da_addback" in row_map:
            parts.append(f"{cl}{row_map['da_addback']}")
        parts.append(f"{cl}{row_map['wc_change']}")
        cells.append(_cell(sheet, r, col,
                            formula="+".join(parts),
                            bold=True, font_color=BLACK_CALC,
                            fill_color=SUBTOTAL_BG, number_format=FMT_CURRENCY))
    r += 2

    # --- Investing Activities ---
    cells.append(_cell(sheet, r, 1, value="INVESTING ACTIVITIES", bold=True, fill_color=HEADER_BG))
    for p in range(periods):
        cells.append(_cell(sheet, r, p + 2, value="", fill_color=HEADER_BG))
    r += 1

    row_map["capex"] = r
    cells.append(_cell(sheet, r, 1, value="Capital Expenditure"))
    for p in range(periods):
        col = p + 2
        if capex_ref != "0":
            cells.append(_cell(sheet, r, col, formula=f"-{capex_ref}",
                                font_color=GREEN_LINK, number_format=FMT_CURRENCY))
        else:
            cells.append(_cell(sheet, r, col, value=0, number_format=FMT_CURRENCY))
    r += 1

    # Cash from Investing
    row_map["cfi"] = r
    cells.append(_cell(sheet, r, 1, value="Cash from Investing", bold=True, fill_color=SUBTOTAL_BG))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        cells.append(_cell(sheet, r, col,
                            formula=f"{cl}{row_map['capex']}",
                            bold=True, font_color=BLACK_CALC,
                            fill_color=SUBTOTAL_BG, number_format=FMT_CURRENCY))
    r += 2

    # --- Net Change in Cash ---
    row_map["net_cash"] = r
    cells.append(_cell(sheet, r, 1, value="Net Change in Cash", bold=True, fill_color=SUBTOTAL_BG))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        cells.append(_cell(sheet, r, col,
                            formula=f"{cl}{row_map['cfo']}+{cl}{row_map['cfi']}",
                            bold=True, font_color=BLACK_CALC,
                            fill_color=SUBTOTAL_BG, number_format=FMT_CURRENCY))
    r += 1

    # Cumulative Cash
    row_map["cumulative_cash"] = r
    cells.append(_cell(sheet, r, 1, value="Cumulative Cash", bold=True))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        if p == 0:
            cells.append(_cell(sheet, r, col,
                                formula=f"{cl}{row_map['net_cash']}",
                                bold=True, font_color=BLACK_CALC, number_format=FMT_CURRENCY))
        else:
            prev = _col_letter(col - 1)
            cells.append(_cell(sheet, r, col,
                                formula=f"{prev}{r}+{cl}{row_map['net_cash']}",
                                bold=True, font_color=BLACK_CALC, number_format=FMT_CURRENCY))

    return cells, row_map


def _compose_ratios(
    is_row_map: dict[str, int],
    bs_row_map: dict[str, int],
    periods: int,
) -> list[dict[str, Any]]:
    """Build Financial Ratios sheet — ALL formulas, zero static values."""
    cells: list[dict[str, Any]] = []
    sheet = SH_RATIOS

    # Title
    cells.append(_cell(sheet, 1, 1, value="Financial Ratios", bold=True, fill_color=HEADER_BG))
    for p in range(periods):
        cells.append(_cell(sheet, 1, p + 2, value=f"Year {p + 1}", bold=True, fill_color=HEADER_BG))

    r = 3

    def _ratio_row(label: str, numerator_sheet: str, num_row: int,
                   denominator_sheet: str, den_row: int, fmt: str = FMT_PERCENT) -> None:
        nonlocal r
        # Phase 1 Hardening: Validate row references before using in formulas
        if num_row <= 0 or den_row <= 0:
            log.warning(f"Ratios sheet: invalid row references for {label} (num_row={num_row}, den_row={den_row}), skipping ratio")
            return
        cells.append(_cell(sheet, r, 1, value=label))
        for p in range(periods):
            col = p + 2
            cl = _col_letter(col)
            num = f"'{numerator_sheet}'!{cl}{num_row}"
            den = f"'{denominator_sheet}'!{cl}{den_row}"
            cells.append(_cell(sheet, r, col,
                                formula=_safe_div(num, den),
                                font_color=GREEN_LINK, number_format=fmt))
        r += 1

    # Profitability
    cells.append(_cell(sheet, r, 1, value="PROFITABILITY", bold=True, fill_color=HEADER_BG))
    for p in range(periods):
        cells.append(_cell(sheet, r, p + 2, value="", fill_color=HEADER_BG))
    r += 1

    if "gross_profit" in is_row_map and "revenue" in is_row_map:
        _ratio_row("Gross Margin", SH_INCOME, is_row_map["gross_profit"],
                    SH_INCOME, is_row_map["revenue"])

    if "ebitda" in is_row_map and "revenue" in is_row_map:
        _ratio_row("EBITDA Margin", SH_INCOME, is_row_map["ebitda"],
                    SH_INCOME, is_row_map["revenue"])

    if "net_income" in is_row_map and "revenue" in is_row_map:
        _ratio_row("Net Margin", SH_INCOME, is_row_map["net_income"],
                    SH_INCOME, is_row_map["revenue"])

    # Returns
    if "net_income" in is_row_map and "equity" in bs_row_map:
        _ratio_row("Return on Equity (ROE)", SH_INCOME, is_row_map["net_income"],
                    SH_BALANCE, bs_row_map["equity"])

    if "net_income" in is_row_map and "total_assets" in bs_row_map:
        _ratio_row("Return on Assets (ROA)", SH_INCOME, is_row_map["net_income"],
                    SH_BALANCE, bs_row_map["total_assets"])

    # Leverage
    r += 1
    cells.append(_cell(sheet, r, 1, value="LEVERAGE", bold=True, fill_color=HEADER_BG))
    for p in range(periods):
        cells.append(_cell(sheet, r, p + 2, value="", fill_color=HEADER_BG))
    r += 1

    if "long_term_debt" in bs_row_map and "equity" in bs_row_map:
        _ratio_row("Debt / Equity", SH_BALANCE, bs_row_map["long_term_debt"],
                    SH_BALANCE, bs_row_map["equity"], fmt=FMT_RATIO)

    # Liquidity
    if "current_assets" in bs_row_map and "current_liabilities" in bs_row_map:
        _ratio_row("Current Ratio", SH_BALANCE, bs_row_map["current_assets"],
                    SH_BALANCE, bs_row_map["current_liabilities"], fmt=FMT_RATIO)

    return cells


def _compose_valuation(
    ref_map: dict[str, str],
    is_row_map: dict[str, int],
    cf_row_map: dict[str, int],
    periods: int,
) -> list[dict[str, Any]]:
    """Build DCF Valuation sheet with formulas."""
    cells: list[dict[str, Any]] = []
    sheet = SH_VALUATION

    wacc_ref = ref_map.get("discount_rate") or ref_map.get("wacc", "0")
    tg_ref = ref_map.get("terminal_growth") or ref_map.get("terminal_growth_rate", "0")

    # Title
    cells.append(_cell(sheet, 1, 1, value="DCF Valuation", bold=True, fill_color=HEADER_BG))
    for p in range(periods):
        cells.append(_cell(sheet, 1, p + 2, value=f"Year {p + 1}", bold=True, fill_color=HEADER_BG))

    r = 3

    # FCF row — reference Cash from Operations - CapEx (which is already net in CFI)
    cfo_row = cf_row_map.get("cfo", 0)
    capex_row = cf_row_map.get("capex", 0)

    # Phase 1 Hardening: Validate row references before using in formulas
    if cfo_row <= 0 or capex_row <= 0:
        log.warning(f"Valuation sheet: missing cash flow rows (cfo_row={cfo_row}, capex_row={capex_row}), "
                   f"valuation sheet will be incomplete")
        return []  # Gracefully skip this sheet

    fcf_r = r
    cells.append(_cell(sheet, r, 1, value="Free Cash Flow", bold=True))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        cells.append(_cell(sheet, r, col,
                            formula=f"'{SH_CASHFLOW}'!{cl}{cfo_row}+'{SH_CASHFLOW}'!{cl}{capex_row}",
                            font_color=GREEN_LINK, number_format=FMT_CURRENCY))
    r += 1

    # Discount Factor
    df_r = r
    cells.append(_cell(sheet, r, 1, value="Discount Factor"))
    for p in range(periods):
        col = p + 2
        cells.append(_cell(sheet, r, col,
                            formula=f"1/(1+{wacc_ref})^{p + 1}",
                            font_color=BLACK_CALC, number_format="0.0000"))
    r += 1

    # PV of FCF
    pv_r = r
    cells.append(_cell(sheet, r, 1, value="PV of Free Cash Flow"))
    for p in range(periods):
        col = p + 2
        cl = _col_letter(col)
        cells.append(_cell(sheet, r, col,
                            formula=f"{cl}{fcf_r}*{cl}{df_r}",
                            font_color=BLACK_CALC, number_format=FMT_CURRENCY))
    r += 2

    # Summary section
    cells.append(_cell(sheet, r, 1, value="VALUATION SUMMARY", bold=True, fill_color=HEADER_BG))
    cells.append(_cell(sheet, r, 2, value="", fill_color=HEADER_BG))
    r += 1

    # Sum of PV of FCFs
    sum_pv_r = r
    first_col = _col_letter(2)
    last_col = _col_letter(periods + 1)
    cells.append(_cell(sheet, r, 1, value="Sum of PV (FCFs)"))
    cells.append(_cell(sheet, r, 2,
                        formula=f"SUM({first_col}{pv_r}:{last_col}{pv_r})",
                        font_color=BLACK_CALC, number_format=FMT_CURRENCY))
    r += 1

    # Terminal Value
    # Phase 3 Hardening: Protect against wacc=terminal_growth division by zero
    tv_r = r
    last_fcf_col = _col_letter(periods + 1)
    cells.append(_cell(sheet, r, 1, value="Terminal Value"))
    cells.append(_cell(sheet, r, 2,
                        formula=f"IF({wacc_ref}<={tg_ref},0,{_safe_div(f'{last_fcf_col}{fcf_r}*(1+{tg_ref})', f'({wacc_ref}-{tg_ref})')})",
                        font_color=BLACK_CALC, number_format=FMT_CURRENCY))
    r += 1

    # PV of Terminal Value
    pv_tv_r = r
    cells.append(_cell(sheet, r, 1, value="PV of Terminal Value"))
    cells.append(_cell(sheet, r, 2,
                        formula=f"B{tv_r}/(1+{wacc_ref})^{periods}",
                        font_color=BLACK_CALC, number_format=FMT_CURRENCY))
    r += 1

    # Enterprise Value
    cells.append(_cell(sheet, r, 1, value="Enterprise Value", bold=True, fill_color=SUBTOTAL_BG))
    cells.append(_cell(sheet, r, 2,
                        formula=f"B{sum_pv_r}+B{pv_tv_r}",
                        bold=True, font_color=BLACK_CALC,
                        fill_color=SUBTOTAL_BG, number_format=FMT_CURRENCY))
    r += 2

    # IRR using Excel built-in
    cells.append(_cell(sheet, r, 1, value="IRR (Internal Rate of Return)", bold=True))
    cells.append(_cell(sheet, r, 2,
                        formula=f"IRR({first_col}{fcf_r}:{last_col}{fcf_r})",
                        bold=True, font_color=BLACK_CALC, number_format=FMT_PERCENT))

    return cells


def _compose_dashboard(
    is_row_map: dict[str, int],
    bs_row_map: dict[str, int],
    periods: int,
) -> list[dict[str, Any]]:
    """Build summary Dashboard with cross-sheet KPI references."""
    cells: list[dict[str, Any]] = []
    sheet = SH_DASHBOARD

    cells.append(_cell(sheet, 1, 1, value="Executive Dashboard", bold=True, fill_color=HEADER_BG))
    cells.append(_cell(sheet, 1, 2, value="Year 1", bold=True, fill_color=HEADER_BG))
    if periods >= 5:
        cells.append(_cell(sheet, 1, 3, value="Year 5", bold=True, fill_color=HEADER_BG))

    r = 3
    cells.append(_cell(sheet, r, 1, value="KEY METRICS", bold=True, fill_color=HEADER_BG))
    cells.append(_cell(sheet, r, 2, value="", fill_color=HEADER_BG))
    if periods >= 5:
        cells.append(_cell(sheet, r, 3, value="", fill_color=HEADER_BG))
    r += 1

    def _kpi(label: str, src_sheet: str, src_row: int, fmt: str = FMT_CURRENCY) -> None:
        nonlocal r
        # Phase 1 Hardening: Validate row reference before using in formula
        if src_row <= 0:
            log.warning(f"Dashboard: invalid row reference for {label} (src_row={src_row}), skipping KPI")
            return
        cells.append(_cell(sheet, r, 1, value=label))
        cells.append(_cell(sheet, r, 2,
                            formula=f"'{src_sheet}'!B{src_row}",
                            font_color=GREEN_LINK, number_format=fmt))
        if periods >= 5:
            last_cl = _col_letter(periods + 1)
            cells.append(_cell(sheet, r, 3,
                                formula=f"'{src_sheet}'!{last_cl}{src_row}",
                                font_color=GREEN_LINK, number_format=fmt))
        r += 1

    if "revenue" in is_row_map:
        _kpi("Revenue", SH_INCOME, is_row_map["revenue"])
    if "gross_profit" in is_row_map:
        _kpi("Gross Profit", SH_INCOME, is_row_map["gross_profit"])
    if "ebitda" in is_row_map:
        _kpi("EBITDA", SH_INCOME, is_row_map["ebitda"])
    if "net_income" in is_row_map:
        _kpi("Net Income", SH_INCOME, is_row_map["net_income"])
    if "gross_margin" in is_row_map:
        _kpi("Gross Margin %", SH_INCOME, is_row_map["gross_margin"], FMT_PERCENT)
    if "net_margin" in is_row_map:
        _kpi("Net Margin %", SH_INCOME, is_row_map["net_margin"], FMT_PERCENT)
    if "total_assets" in bs_row_map:
        _kpi("Total Assets", SH_BALANCE, bs_row_map["total_assets"])

    # Revenue CAGR
    if "revenue" in is_row_map and periods >= 2:
        r += 1
        cells.append(_cell(sheet, r, 1, value="GROWTH", bold=True, fill_color=HEADER_BG))
        cells.append(_cell(sheet, r, 2, value="", fill_color=HEADER_BG))
        r += 1

        rev_row = is_row_map["revenue"]
        last_cl = _col_letter(periods + 1)
        cells.append(_cell(sheet, r, 1, value=f"{periods}-Year Revenue CAGR"))
        cells.append(_cell(sheet, r, 2,
                            formula=f"IF('{SH_INCOME}'!B{rev_row}=0,0,"
                                    f"('{SH_INCOME}'!{last_cl}{rev_row}/'{SH_INCOME}'!B{rev_row})"
                                    f"^(1/{periods - 1})-1)",
                            font_color=BLACK_CALC, number_format=FMT_PERCENT))

    return cells


# ---------------------------------------------------------------------------
# Optional Sheet Composers
# ---------------------------------------------------------------------------

def _compose_scenarios(
    scenarios: list[dict[str, Any]],
    assumptions: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build Scenarios comparison sheet with static calculated values."""
    if not scenarios:
        return []

    try:
        from app.services.scenario_runner import run_scenario_calculation
    except ImportError:
        return []

    cells: list[dict[str, Any]] = []
    sheet = SH_SCENARIOS

    # Title
    cells.append(_cell(sheet, 1, 1, value="Scenario Comparison", bold=True, fill_color=HEADER_BG))

    # Column headers
    cells.append(_cell(sheet, 2, 1, value="Metric", bold=True))

    # Base case
    base_scenario = {"id": "base", "name": "Base Case", "assumption_overrides": {}}
    all_scenarios = [base_scenario] + list(scenarios)

    for idx, scn in enumerate(all_scenarios):
        cells.append(_cell(sheet, 2, idx + 2, value=scn.get("name", f"Scenario {idx}"),
                            bold=True, fill_color=HEADER_BG))

    # Calculate each scenario
    # Phase 3 Hardening: Validate scenarios and gracefully degrade on errors
    results = []
    for idx, scn in enumerate(all_scenarios):
        # Validate scenario structure
        if not isinstance(scn, dict):
            log.warning(f"Scenarios: skipping malformed scenario at index {idx} (not a dict)")
            results.append({"metrics": {}, "npv": None})
            continue

        try:
            result = run_scenario_calculation(scn, assumptions)
            results.append(result)
        except Exception as e:
            scn_name = scn.get("name", f"Scenario {idx}")
            log.warning(f"Scenarios: calculation failed for {scn_name}: {e}")
            results.append({"metrics": {}, "npv": None})

    # Write metrics rows
    metric_keys = set()
    for res in results:
        metric_keys.update(res.get("metrics", {}).keys())

    r = 3
    for metric_key in sorted(metric_keys):
        display = metric_key.replace("_", " ").title()
        cells.append(_cell(sheet, r, 1, value=display))

        for idx, res in enumerate(results):
            val = res.get("metrics", {}).get(metric_key)
            if val is not None:
                fmt = FMT_PERCENT if "margin" in metric_key or "pct" in metric_key else FMT_CURRENCY
                cells.append(_cell(sheet, r, idx + 2, value=round(val, 2),
                                    number_format=fmt))
        r += 1

    # NPV row
    cells.append(_cell(sheet, r, 1, value="NPV", bold=True, fill_color=SUBTOTAL_BG))
    for idx, res in enumerate(results):
        npv_data = res.get("npv")
        npv_val = npv_data.get("npv") if isinstance(npv_data, dict) else None
        if npv_val is not None:
            cells.append(_cell(sheet, r, idx + 2, value=round(npv_val, 2),
                                bold=True, fill_color=SUBTOTAL_BG, number_format=FMT_CURRENCY))

    return cells


def _compose_forecast(
    historical_data: list[float],
    periods: int,
) -> list[dict[str, Any]]:
    """Build Forecast sheet from historical data using ensemble method."""
    if not historical_data or len(historical_data) < 3:
        return []

    # Phase 3 Hardening: Validate historical data for NaN/Inf
    for idx, val in enumerate(historical_data):
        if math.isnan(val) or math.isinf(val):
            log.warning(f"Forecast: historical_data[{idx}] is {val}, skipping forecast sheet")
            return []

    try:
        from app.services.forecasting import forecast_with_confidence
    except ImportError:
        return []

    cells: list[dict[str, Any]] = []
    sheet = SH_FORECAST

    try:
        result = forecast_with_confidence(historical_data, forecast_periods=periods)
    except Exception as e:
        log.warning(f"Forecast: calculation failed: {e}")
        return []

    forecasts = result.get("forecasts", [])
    ci = result.get("confidence_intervals", [])
    method = result.get("method", "Ensemble")

    # Title
    cells.append(_cell(sheet, 1, 1, value=f"Forecast ({method})", bold=True, fill_color=HEADER_BG))

    # Headers
    cells.append(_cell(sheet, 2, 1, value="Period", bold=True))
    cells.append(_cell(sheet, 2, 2, value="Forecast", bold=True))
    cells.append(_cell(sheet, 2, 3, value="Lower 95% CI", bold=True))
    cells.append(_cell(sheet, 2, 4, value="Upper 95% CI", bold=True))

    # Historical data
    r = 3
    for idx, val in enumerate(historical_data):
        cells.append(_cell(sheet, r, 1, value=f"Historical {idx + 1}"))
        cells.append(_cell(sheet, r, 2, value=round(val, 2), number_format=FMT_CURRENCY))
        r += 1

    # Separator
    r += 1

    # Forecast data
    for idx in range(len(forecasts)):
        cells.append(_cell(sheet, r, 1, value=f"Forecast {idx + 1}",
                            font_color=BLUE_INPUT))
        cells.append(_cell(sheet, r, 2, value=round(forecasts[idx], 2),
                            number_format=FMT_CURRENCY))
        if idx < len(ci):
            cells.append(_cell(sheet, r, 3, value=round(ci[idx].get("lower", 0), 2),
                                number_format=FMT_CURRENCY))
            cells.append(_cell(sheet, r, 4, value=round(ci[idx].get("upper", 0), 2),
                                number_format=FMT_CURRENCY))
        r += 1

    return cells


def _compose_budget_vs_actual(
    budget_data: dict[str, Any],
    actuals_by_period: dict[int, dict[str, float]] | dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Build Budget vs Actual sheet with variance formulas."""
    if not budget_data or not actuals_by_period:
        return []

    cells: list[dict[str, Any]] = []
    sheet = SH_BUDGET

    # Title
    cells.append(_cell(sheet, 1, 1, value="Budget vs Actual Analysis", bold=True, fill_color=HEADER_BG))

    # Headers
    cells.append(_cell(sheet, 2, 1, value="Line Item", bold=True))
    cells.append(_cell(sheet, 2, 2, value="Budget", bold=True))
    cells.append(_cell(sheet, 2, 3, value="Actual", bold=True))
    cells.append(_cell(sheet, 2, 4, value="Variance", bold=True))
    cells.append(_cell(sheet, 2, 5, value="Variance %", bold=True))

    # Extract budget items from budget_data
    bd = budget_data.get("budget_data", budget_data)
    if not isinstance(bd, dict):
        return cells

    r = 3
    # Determine actual totals — handle both dict-of-period and flat dict
    # Phase 3 Hardening: Validate budget/actuals structure and values
    actual_totals: dict[str, float] = {}
    if isinstance(actuals_by_period, dict):
        for key, val in actuals_by_period.items():
            if isinstance(val, dict):
                # period → {item: amount}
                for item, amount in val.items():
                    try:
                        amt_float = float(amount)
                        if math.isnan(amt_float) or math.isinf(amt_float):
                            log.warning(f"Budget vs Actual: skipping invalid actual value for {item}: {amount}")
                            continue
                        actual_totals[item] = actual_totals.get(item, 0) + amt_float
                    except (TypeError, ValueError):
                        log.warning(f"Budget vs Actual: skipping non-numeric actual value for {item}: {amount}")
            elif isinstance(val, (int, float)):
                try:
                    val_float = float(val)
                    if not (math.isnan(val_float) or math.isinf(val_float)):
                        actual_totals[str(key)] = val_float
                except (TypeError, ValueError):
                    log.warning(f"Budget vs Actual: skipping non-numeric actual value for {key}: {val}")

    for item, budget_val in bd.items():
        if not isinstance(budget_val, (int, float)):
            log.debug(f"Budget vs Actual: skipping non-numeric budget item {item}: {budget_val}")
            continue
        try:
            budget_val = float(budget_val)
            if math.isnan(budget_val) or math.isinf(budget_val):
                log.warning(f"Budget vs Actual: skipping invalid budget value for {item}: {budget_val}")
                continue
        except (TypeError, ValueError):
            log.warning(f"Budget vs Actual: skipping budget item {item}: invalid value {budget_val}")
            continue
        actual_val = actual_totals.get(item, 0)

        cells.append(_cell(sheet, r, 1, value=str(item).replace("_", " ").title()))
        cells.append(_cell(sheet, r, 2, value=round(budget_val, 2), number_format=FMT_CURRENCY))
        cells.append(_cell(sheet, r, 3, value=round(actual_val, 2), number_format=FMT_CURRENCY))

        # Variance as formula
        cl_b = _col_letter(3)
        cl_a = _col_letter(2)
        cells.append(_cell(sheet, r, 4,
                            formula=f"{cl_b}{r}-{cl_a}{r}",
                            font_color=BLACK_CALC, number_format=FMT_CURRENCY))
        # Variance %
        cells.append(_cell(sheet, r, 5,
                            formula=_safe_div(f"D{r}", f"{cl_a}{r}"),
                            font_color=BLACK_CALC, number_format=FMT_PERCENT))
        r += 1

    return cells


# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------

def compose_financial_model(
    assumptions: dict[str, Any],
    scenarios: list[dict[str, Any]] | None = None,
    budget_data: dict[str, Any] | None = None,
    actuals_by_period: dict[int, dict[str, float]] | dict[str, Any] | None = None,
    historical_data: list[float] | None = None,
    periods: int = 5,
) -> list[dict[str, Any]]:
    """Compose a complete financial model as a list of xlsx_cells.

    Calls existing financial services, transforms results into the
    ``xlsx_cells`` format for ``apply_cells_to_workbook()``.

    Args:
        assumptions: Model assumptions dict (revenue, growth_rate, etc.)
        scenarios: Optional list of scenario dicts with assumption_overrides
        budget_data: Optional budget setup data
        actuals_by_period: Optional actuals keyed by period number
        historical_data: Optional historical values for forecasting
        periods: Number of projection periods (default 5)

    Returns:
        List of cell dicts compatible with ``apply_cells_to_workbook()``.

    Raises:
        ValueError: If periods is out of bounds, assumptions contain invalid values, etc.
    """
    # Phase 1 Hardening: Bounds validation
    if not isinstance(periods, int):
        raise ValueError(f"periods must be an integer, got {type(periods).__name__}")
    if periods < 1 or periods > 100:
        raise ValueError(f"periods must be between 1 and 100, got {periods}")

    if not assumptions:
        assumptions = {}

    cells: list[dict[str, Any]] = []

    # 1. Assumptions (always present — foundation for everything)
    assumption_cells, ref_map = _compose_assumptions_sheet(assumptions)
    cells.extend(assumption_cells)

    # 2. Income Statement (needs at least revenue)
    has_revenue = _resolve_assumption(assumptions, "revenue") is not None
    is_row_map: dict[str, int] = {}
    bs_row_map: dict[str, int] = {}
    cf_row_map: dict[str, int] = {}

    if has_revenue:
        is_cells, is_row_map = _compose_income_statement(ref_map, periods)
        cells.extend(is_cells)

        # 3. Balance Sheet (needs asset/liability assumptions or uses defaults)
        bs_cells, bs_row_map = _compose_balance_sheet(ref_map, periods)
        cells.extend(bs_cells)

        # 4. Cash Flow (needs Income Statement)
        cf_cells, cf_row_map = _compose_cash_flow(ref_map, is_row_map, periods)
        cells.extend(cf_cells)

        # 5. Financial Ratios
        ratio_cells = _compose_ratios(is_row_map, bs_row_map, periods)
        cells.extend(ratio_cells)

        # 6. Valuation (DCF)
        has_wacc = _resolve_assumption(assumptions, "discount_rate", "wacc") is not None
        if has_wacc and cf_row_map:
            val_cells = _compose_valuation(ref_map, is_row_map, cf_row_map, periods)
            cells.extend(val_cells)

    # 7. Scenarios (optional)
    if scenarios:
        scn_cells = _compose_scenarios(scenarios, assumptions)
        cells.extend(scn_cells)

    # 8. Forecast (optional)
    if historical_data and len(historical_data) >= 3:
        fc_cells = _compose_forecast(historical_data, periods)
        cells.extend(fc_cells)

    # 9. Budget vs Actual (optional)
    if budget_data and actuals_by_period:
        bva_cells = _compose_budget_vs_actual(budget_data, actuals_by_period)
        cells.extend(bva_cells)

    # 10. Dashboard (always present if we have income statement)
    if is_row_map:
        dash_cells = _compose_dashboard(is_row_map, bs_row_map, periods)
        cells.extend(dash_cells)

    return cells


# ---------------------------------------------------------------------------
# Cowork Alignment: Tier 1 - Automatic Retry Loop with Exponential Backoff
# ---------------------------------------------------------------------------

MAX_RETRY_ATTEMPTS = 3
BASE_RETRY_DELAY = 0.25  # seconds


def _exponential_backoff(attempt: int) -> float:
    """
    Exponential backoff formula: min(1.5, 0.25 * 2^attempt) seconds.

    Matches Cowork coordinator.py retry pattern for consistency.
    """
    return min(1.5, BASE_RETRY_DELAY * (2 ** attempt))


def compose_financial_model_with_retry(
    assumptions: dict[str, Any],
    scenarios: list[dict] | None = None,
    budget_data: dict | None = None,
    actuals_by_period: dict[int, dict] | None = None,
    historical_data: list[float] | None = None,
    periods: int = 5,
    max_retries: int = MAX_RETRY_ATTEMPTS,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """
    Compose financial model with automatic retry on transient failures.

    Implements Cowork Tier 1 alignment pattern: retry with exponential backoff
    for transient failures, while failing immediately on non-transient issues.

    Args:
        assumptions: Model assumptions dict
        scenarios: Optional list of scenario dicts
        budget_data: Optional budget data dict
        actuals_by_period: Optional actuals by period dict
        historical_data: Optional historical data list
        periods: Number of forecast periods (1-100)
        max_retries: Maximum retry attempts (default 3)

    Returns:
        Tuple of (cells, error_string):
        - On success: (cells_list, None)
        - On failure: (None, error_message_string)

    Transient failures (retried):
        - MemoryError: OOM during composition
        - TimeoutError: Composition takes too long
        - Generic exceptions (may be transient service issues)

    Non-transient failures (fail immediately):
        - ValueError: Invalid assumptions, periods out of bounds
    """
    last_error = None

    for attempt in range(max_retries):
        try:
            log.debug(f"Compose attempt {attempt + 1}/{max_retries}")
            cells = compose_financial_model(
                assumptions=assumptions,
                scenarios=scenarios,
                budget_data=budget_data,
                actuals_by_period=actuals_by_period,
                historical_data=historical_data,
                periods=periods,
            )
            log.info(f"Compose success on attempt {attempt + 1}")
            return cells, None  # Success!

        except ValueError as e:
            # Non-transient: validation errors (invalid assumptions, periods bounds)
            log.error(f"Compose validation error (non-transient): {e}")
            return None, str(e)

        except (MemoryError, TimeoutError) as e:
            # Transient: memory or timeout
            last_error = str(e)
            if attempt < max_retries - 1:
                delay = _exponential_backoff(attempt)
                log.warning(
                    f"Compose transient failure (attempt {attempt + 1}): {type(e).__name__}, "
                    f"retrying in {delay:.2f}s"
                )
                time.sleep(delay)
            else:
                log.error(f"Compose failed after {max_retries} attempts: {e}")
                return None, last_error

        except Exception as e:
            # Unknown: treat as potentially transient
            last_error = str(e)
            if attempt < max_retries - 1:
                delay = _exponential_backoff(attempt)
                log.warning(
                    f"Compose unknown error (attempt {attempt + 1}): {type(e).__name__}: {e}, "
                    f"retrying in {delay:.2f}s"
                )
                time.sleep(delay)
            else:
                log.error(f"Compose failed after {max_retries} attempts (unknown error): {e}")
                return None, last_error

    return None, last_error or "Compose failed: unknown reason"
