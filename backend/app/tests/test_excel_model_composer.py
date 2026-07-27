"""Comprehensive tests for the Excel Financial Model Composer."""

import io

from openpyxl import Workbook, load_workbook

from app.services.excel_model_composer import (
    BLUE_INPUT,
    FMT_CURRENCY,
    FMT_PERCENT,
    HEADER_BG,
    SH_ASSUMPTIONS,
    SH_BALANCE,
    SH_BUDGET,
    SH_CASHFLOW,
    SH_DASHBOARD,
    SH_FORECAST,
    SH_INCOME,
    SH_RATIOS,
    SH_SCENARIOS,
    SH_VALUATION,
    YELLOW_BG,
    _cell,
    _col_letter,
    _compose_assumptions_sheet,
    _compose_balance_sheet,
    _compose_budget_vs_actual,
    _compose_cash_flow,
    _compose_forecast,
    _compose_income_statement,
    _compose_ratios,
    _compose_scenarios,
    _compose_valuation,
    _safe_div,
    compose_financial_model,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FULL_ASSUMPTIONS = {
    "revenue": 1000000,
    "growth_rate": 0.10,
    "cogs_pct": 0.40,
    "opex": 200000,
    "tax_rate": 0.21,
    "discount_rate": 0.10,
    "terminal_growth": 0.02,
    "capex": 50000,
    "current_assets": 500000,
    "fixed_assets": 2000000,
    "current_liabilities": 300000,
    "long_term_debt": 1000000,
    "shareholders_equity": 1200000,
}

MINIMAL_ASSUMPTIONS = {
    "revenue": 500000,
    "growth_rate": 0.05,
}


# ---------------------------------------------------------------------------
# Helper Tests
# ---------------------------------------------------------------------------

class TestColLetter:
    def test_single_letter(self):
        assert _col_letter(1) == "A"
        assert _col_letter(2) == "B"
        assert _col_letter(26) == "Z"

    def test_double_letter(self):
        assert _col_letter(27) == "AA"
        assert _col_letter(28) == "AB"
        assert _col_letter(52) == "AZ"

    def test_triple_letter(self):
        assert _col_letter(703) == "AAA"


class TestCellBuilder:
    def test_value_cell(self):
        c = _cell("Sheet1", 1, 1, value="Hello")
        assert c == {"sheet": "Sheet1", "row": 1, "col": 1, "value": "Hello"}

    def test_formula_cell(self):
        c = _cell("Sheet1", 2, 3, formula="A1+B1")
        assert c["formula"] == "A1+B1"
        assert "value" not in c

    def test_formatting(self):
        c = _cell("S", 1, 1, value=100, bold=True, font_color="0000FF",
                   fill_color="FFFF00", number_format="$#,##0")
        assert c["bold"] is True
        assert c["font_color"] == "0000FF"
        assert c["fill_color"] == "FFFF00"
        assert c["number_format"] == "$#,##0"

    def test_formula_overrides_value(self):
        c = _cell("S", 1, 1, value=100, formula="A1")
        assert c["formula"] == "A1"
        assert "value" not in c

    def test_no_optional_keys_when_absent(self):
        c = _cell("S", 1, 1, value="x")
        assert "bold" not in c
        assert "font_color" not in c
        assert "fill_color" not in c
        assert "number_format" not in c


class TestSafeDiv:
    def test_produces_if_formula(self):
        result = _safe_div("A1", "B1")
        assert result == "IF(B1=0,0,A1/B1)"


# ---------------------------------------------------------------------------
# Assumptions Sheet
# ---------------------------------------------------------------------------

class TestAssumptionsSheet:
    def test_layout_and_ref_map(self):
        cells, ref_map = _compose_assumptions_sheet(FULL_ASSUMPTIONS)
        assert len(cells) > 0
        assert "revenue" in ref_map
        assert ref_map["revenue"].startswith("Assumptions!B")

    def test_blue_font_on_values(self):
        cells, _ = _compose_assumptions_sheet(FULL_ASSUMPTIONS)
        value_cells = [c for c in cells if c.get("font_color") == BLUE_INPUT]
        assert len(value_cells) > 0

    def test_yellow_highlight_on_key_assumptions(self):
        cells, _ = _compose_assumptions_sheet(FULL_ASSUMPTIONS)
        yellow_cells = [c for c in cells if c.get("fill_color") == YELLOW_BG]
        assert len(yellow_cells) >= 3  # revenue, growth_rate, tax_rate

    def test_empty_assumptions(self):
        cells, ref_map = _compose_assumptions_sheet({})
        # Should still have title and header row
        assert len(cells) >= 2
        assert len(ref_map) == 0

    def test_ref_map_has_all_assumptions(self):
        cells, ref_map = _compose_assumptions_sheet(FULL_ASSUMPTIONS)
        for key in FULL_ASSUMPTIONS:
            assert key in ref_map, f"Missing ref_map entry for {key}"

    def test_all_cells_on_correct_sheet(self):
        cells, _ = _compose_assumptions_sheet(FULL_ASSUMPTIONS)
        for c in cells:
            if c.get("_type") in {"named_range", "chart", "table", "data_validation"}:
                continue
            assert c["sheet"] == SH_ASSUMPTIONS


# ---------------------------------------------------------------------------
# Income Statement
# ---------------------------------------------------------------------------

class TestIncomeStatementSheet:
    def _make_ref_map(self):
        _, ref_map = _compose_assumptions_sheet(FULL_ASSUMPTIONS)
        return ref_map

    def test_revenue_year1_references_assumptions(self):
        ref_map = self._make_ref_map()
        cells, row_map = _compose_income_statement(ref_map, 5)
        rev_row = row_map["revenue"]
        year1_cell = [c for c in cells if c["row"] == rev_row and c["col"] == 2
                      and c.get("formula")]
        assert len(year1_cell) == 1
        assert "Assumptions!" in year1_cell[0]["formula"]

    def test_revenue_year2_growth_formula(self):
        ref_map = self._make_ref_map()
        cells, row_map = _compose_income_statement(ref_map, 5)
        rev_row = row_map["revenue"]
        year2_cell = [c for c in cells if c["row"] == rev_row and c["col"] == 3
                      and c.get("formula")]
        assert len(year2_cell) == 1
        assert "*(1+" in year2_cell[0]["formula"]

    def test_gross_profit_is_revenue_minus_cogs(self):
        ref_map = self._make_ref_map()
        cells, row_map = _compose_income_statement(ref_map, 5)
        gp_row = row_map["gross_profit"]
        gp_cell = [c for c in cells if c["row"] == gp_row and c["col"] == 2
                    and c.get("formula")]
        assert len(gp_cell) == 1
        formula = gp_cell[0]["formula"]
        # Should be B{revenue_row}-B{cogs_row}
        assert f"B{row_map['revenue']}" in formula
        assert f"B{row_map['cogs']}" in formula

    def test_no_div_zero_in_margin_formulas(self):
        ref_map = self._make_ref_map()
        cells, row_map = _compose_income_statement(ref_map, 5)
        margin_rows = [row_map.get("gross_margin"), row_map.get("net_margin")]
        for mr in margin_rows:
            if mr is None:
                continue
            margin_cells = [c for c in cells if c["row"] == mr and c.get("formula")]
            for mc in margin_cells:
                assert "IF(" in mc["formula"], f"Missing IF guard in {mc['formula']}"

    def test_5_period_columns(self):
        ref_map = self._make_ref_map()
        cells, row_map = _compose_income_statement(ref_map, 5)
        rev_row = row_map["revenue"]
        rev_cells = [c for c in cells if c["row"] == rev_row and c["col"] >= 2]
        assert len(rev_cells) == 5

    def test_currency_format_on_monetary_rows(self):
        ref_map = self._make_ref_map()
        cells, row_map = _compose_income_statement(ref_map, 5)
        rev_cells = [c for c in cells if c["row"] == row_map["revenue"]
                     and c["col"] >= 2]
        for c in rev_cells:
            assert c.get("number_format") == FMT_CURRENCY

    def test_percent_format_on_margin_rows(self):
        ref_map = self._make_ref_map()
        cells, row_map = _compose_income_statement(ref_map, 5)
        margin_cells = [c for c in cells if c["row"] == row_map["gross_margin"]
                        and c["col"] >= 2]
        for c in margin_cells:
            assert c.get("number_format") == FMT_PERCENT

    def test_all_cells_on_correct_sheet(self):
        ref_map = self._make_ref_map()
        cells, _ = _compose_income_statement(ref_map, 5)
        for c in cells:
            assert c["sheet"] == SH_INCOME


# ---------------------------------------------------------------------------
# Balance Sheet
# ---------------------------------------------------------------------------

class TestBalanceSheetSheet:
    def test_total_assets_formula(self):
        _, ref_map = _compose_assumptions_sheet(FULL_ASSUMPTIONS)
        cells, row_map = _compose_balance_sheet(ref_map, 5)
        ta_row = row_map["total_assets"]
        ta_cell = [c for c in cells if c["row"] == ta_row and c["col"] == 2
                   and c.get("formula")]
        assert len(ta_cell) == 1
        formula = ta_cell[0]["formula"]
        assert f"B{row_map['current_assets']}" in formula
        assert f"B{row_map['fixed_assets']}" in formula

    def test_balance_check_formula(self):
        _, ref_map = _compose_assumptions_sheet(FULL_ASSUMPTIONS)
        cells, row_map = _compose_balance_sheet(ref_map, 5)
        bc_row = row_map["balance_check"]
        bc_cell = [c for c in cells if c["row"] == bc_row and c["col"] == 2
                   and c.get("formula")]
        assert len(bc_cell) == 1
        formula = bc_cell[0]["formula"]
        assert f"B{row_map['total_assets']}" in formula
        assert f"B{row_map['total_le']}" in formula


# ---------------------------------------------------------------------------
# Cash Flow
# ---------------------------------------------------------------------------

class TestCashFlowSheet:
    def test_net_income_cross_sheet_ref(self):
        _, ref_map = _compose_assumptions_sheet(FULL_ASSUMPTIONS)
        is_cells, is_row_map = _compose_income_statement(ref_map, 5)
        cf_cells, cf_row_map = _compose_cash_flow(ref_map, is_row_map, 5)

        ni_row = cf_row_map["net_income"]
        ni_cell = [c for c in cf_cells if c["row"] == ni_row and c["col"] == 2
                   and c.get("formula")]
        assert len(ni_cell) == 1
        assert "'Income Statement'!" in ni_cell[0]["formula"]

    def test_cumulative_cash_formula(self):
        _, ref_map = _compose_assumptions_sheet(FULL_ASSUMPTIONS)
        _, is_row_map = _compose_income_statement(ref_map, 5)
        cf_cells, cf_row_map = _compose_cash_flow(ref_map, is_row_map, 5)

        cum_row = cf_row_map["cumulative_cash"]
        # Year 2 should reference previous year
        y2_cell = [c for c in cf_cells if c["row"] == cum_row and c["col"] == 3
                   and c.get("formula")]
        assert len(y2_cell) == 1
        assert "B" in y2_cell[0]["formula"]  # references previous column


# ---------------------------------------------------------------------------
# Ratios
# ---------------------------------------------------------------------------

class TestRatiosSheet:
    def test_all_ratios_are_formulas(self):
        _, ref_map = _compose_assumptions_sheet(FULL_ASSUMPTIONS)
        _, is_row_map = _compose_income_statement(ref_map, 5)
        _, bs_row_map = _compose_balance_sheet(ref_map, 5)
        cells = _compose_ratios(is_row_map, bs_row_map, 5)

        data_cells = [c for c in cells if c["col"] >= 2
                      and c.get("fill_color") != HEADER_BG
                      and c.get("formula") is not None]
        non_formula_data = [c for c in cells if c["col"] >= 2
                            and c.get("value") is not None
                            and not c.get("bold")  # exclude headers
                            and c.get("fill_color") != HEADER_BG]
        # All data cells should be formulas (no static values in ratio sheet)
        assert len(data_cells) > 0
        assert len(non_formula_data) == 0

    def test_cross_sheet_references(self):
        _, ref_map = _compose_assumptions_sheet(FULL_ASSUMPTIONS)
        _, is_row_map = _compose_income_statement(ref_map, 5)
        _, bs_row_map = _compose_balance_sheet(ref_map, 5)
        cells = _compose_ratios(is_row_map, bs_row_map, 5)

        formula_cells = [c for c in cells if c.get("formula")]
        cross_sheet = [c for c in formula_cells if "'" in c["formula"]]
        assert len(cross_sheet) > 0


# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------

class TestValuationSheet:
    def test_terminal_value_formula(self):
        _, ref_map = _compose_assumptions_sheet(FULL_ASSUMPTIONS)
        _, is_row_map = _compose_income_statement(ref_map, 5)
        cf_cells, cf_row_map = _compose_cash_flow(ref_map, is_row_map, 5)
        val_cells = _compose_valuation(ref_map, is_row_map, cf_row_map, 5)

        tv_cells = [c for c in val_cells if c.get("value") == "Terminal Value"]
        assert len(tv_cells) == 1
        tv_row = tv_cells[0]["row"]
        tv_formula = [c for c in val_cells if c["row"] == tv_row and c["col"] == 2
                      and c.get("formula")]
        assert len(tv_formula) == 1

    def test_pv_discount_formula(self):
        _, ref_map = _compose_assumptions_sheet(FULL_ASSUMPTIONS)
        _, is_row_map = _compose_income_statement(ref_map, 5)
        _, cf_row_map = _compose_cash_flow(ref_map, is_row_map, 5)
        val_cells = _compose_valuation(ref_map, is_row_map, cf_row_map, 5)

        df_cells = [c for c in val_cells if c.get("value") == "Discount Factor"]
        assert len(df_cells) == 1
        df_row = df_cells[0]["row"]
        df_formulas = [c for c in val_cells if c["row"] == df_row and c.get("formula")]
        assert len(df_formulas) == 5
        # Should reference WACC
        for f in df_formulas:
            assert "Assumptions!" in f["formula"] or "wacc" in f["formula"].lower()

    def test_irr_uses_excel_function(self):
        _, ref_map = _compose_assumptions_sheet(FULL_ASSUMPTIONS)
        _, is_row_map = _compose_income_statement(ref_map, 5)
        _, cf_row_map = _compose_cash_flow(ref_map, is_row_map, 5)
        val_cells = _compose_valuation(ref_map, is_row_map, cf_row_map, 5)

        irr_cells = [c for c in val_cells if c.get("formula") and "IRR(" in c["formula"]]
        assert len(irr_cells) >= 1


# ---------------------------------------------------------------------------
# Optional Sheets
# ---------------------------------------------------------------------------

class TestOptionalSheets:
    def test_scenarios_skipped_when_none(self):
        assert _compose_scenarios([], FULL_ASSUMPTIONS) == []
        assert _compose_scenarios(None, FULL_ASSUMPTIONS) == []

    def test_scenarios_included_when_present(self):
        scenarios = [
            {"id": "opt", "name": "Optimistic", "assumption_overrides": {"growth_rate": 0.20}},
        ]
        cells = _compose_scenarios(scenarios, FULL_ASSUMPTIONS)
        assert len(cells) > 0
        sheets = {c["sheet"] for c in cells}
        assert SH_SCENARIOS in sheets

    def test_forecast_skipped_when_insufficient_data(self):
        assert _compose_forecast([], 5) == []
        assert _compose_forecast([1, 2], 5) == []
        assert _compose_forecast(None, 5) == []

    def test_forecast_included_when_sufficient_data(self):
        data = [100, 110, 120, 130, 140]
        cells = _compose_forecast(data, 3)
        assert len(cells) > 0
        sheets = {c["sheet"] for c in cells}
        assert SH_FORECAST in sheets

    def test_variance_skipped_when_no_budget(self):
        assert _compose_budget_vs_actual(None, None) == []
        assert _compose_budget_vs_actual({}, None) == []
        assert _compose_budget_vs_actual(None, {}) == []

    def test_variance_included_when_data_present(self):
        budget = {"budget_data": {"revenue": 1000000, "opex": 200000}}
        actuals = {1: {"revenue": 900000, "opex": 210000}}
        cells = _compose_budget_vs_actual(budget, actuals)
        assert len(cells) > 0
        # Should have variance formulas
        formula_cells = [c for c in cells if c.get("formula")]
        assert len(formula_cells) > 0


# ---------------------------------------------------------------------------
# Full Composition
# ---------------------------------------------------------------------------

class TestComposeFinancialModel:
    def test_full_model_all_core_sheets(self):
        cells = compose_financial_model(FULL_ASSUMPTIONS)
        sheets = {c["sheet"] for c in cells if "sheet" in c}
        assert SH_ASSUMPTIONS in sheets
        assert SH_INCOME in sheets
        assert SH_BALANCE in sheets
        assert SH_CASHFLOW in sheets
        assert SH_RATIOS in sheets
        assert SH_VALUATION in sheets
        assert SH_DASHBOARD in sheets

    def test_full_model_with_optional_sheets(self):
        scenarios = [{"id": "s1", "name": "Bull", "assumption_overrides": {"growth_rate": 0.2}}]
        budget = {"budget_data": {"revenue": 1000000}}
        actuals = {1: {"revenue": 950000}}
        historical = [100, 110, 120, 130, 140]

        cells = compose_financial_model(
            assumptions=FULL_ASSUMPTIONS,
            scenarios=scenarios,
            budget_data=budget,
            actuals_by_period=actuals,
            historical_data=historical,
        )
        sheets = {c["sheet"] for c in cells if "sheet" in c}
        assert SH_SCENARIOS in sheets
        assert SH_FORECAST in sheets
        assert SH_BUDGET in sheets

    def test_minimal_model_core_sheets(self):
        cells = compose_financial_model(MINIMAL_ASSUMPTIONS)
        sheets = {c["sheet"] for c in cells if "sheet" in c}
        assert SH_ASSUMPTIONS in sheets
        assert SH_INCOME in sheets
        # Dashboard present because revenue exists
        assert SH_DASHBOARD in sheets

    def test_empty_assumptions_only_produces_assumptions_sheet(self):
        cells = compose_financial_model({})
        sheets = {c["sheet"] for c in cells if "sheet" in c}
        assert SH_ASSUMPTIONS in sheets
        assert SH_INCOME not in sheets

    def test_no_duplicate_cells(self):
        cells = compose_financial_model(FULL_ASSUMPTIONS)
        seen = set()
        for c in cells:
            if c.get("_type") in {"named_range", "chart", "table", "data_validation"}:
                continue
            key = (c["sheet"], c["row"], c["col"])
            assert key not in seen, f"Duplicate cell at {key}"
            seen.add(key)

    def test_cell_count_reasonable(self):
        cells = compose_financial_model(FULL_ASSUMPTIONS)
        # A 5-period model should have 200-2000 cells
        assert 100 < len(cells) < 3000, f"Cell count {len(cells)} out of range"

    def test_all_sheet_names_within_limit(self):
        cells = compose_financial_model(FULL_ASSUMPTIONS)
        sheets = {c["sheet"] for c in cells if "sheet" in c}
        for name in sheets:
            assert len(name) <= 31, f"Sheet name too long: {name} ({len(name)} chars)"


# ---------------------------------------------------------------------------
# End-to-End Excel Rendering
# ---------------------------------------------------------------------------

class TestEndToEndExcelExport:
    def test_compose_and_render(self):
        """Compose cells, render to workbook, verify output structure."""
        from app.core.deliverable_xlsx import apply_cells_to_workbook

        cells = compose_financial_model(FULL_ASSUMPTIONS)
        wb = Workbook()
        apply_cells_to_workbook(wb, cells)

        # Verify sheet names
        assert SH_ASSUMPTIONS in wb.sheetnames
        assert SH_INCOME in wb.sheetnames
        assert SH_BALANCE in wb.sheetnames
        assert SH_CASHFLOW in wb.sheetnames
        assert SH_RATIOS in wb.sheetnames
        assert SH_VALUATION in wb.sheetnames
        assert SH_DASHBOARD in wb.sheetnames

    def test_formulas_are_written_correctly(self):
        from app.core.deliverable_xlsx import apply_cells_to_workbook

        cells = compose_financial_model(FULL_ASSUMPTIONS)
        wb = Workbook()
        apply_cells_to_workbook(wb, cells)

        ws = wb[SH_INCOME]
        # Revenue Year 1 should be a formula referencing Assumptions
        rev_cell = ws.cell(row=3, column=2)
        assert rev_cell.value is not None
        assert str(rev_cell.value).startswith("=")
        assert "Assumptions!" in str(rev_cell.value)

    def test_font_color_applied(self):
        from app.core.deliverable_xlsx import apply_cells_to_workbook

        cells = compose_financial_model(FULL_ASSUMPTIONS)
        wb = Workbook()
        apply_cells_to_workbook(wb, cells)

        # Check assumptions sheet has blue font on value cells
        ws = wb[SH_ASSUMPTIONS]
        # Row 3, Col 2 should be the first assumption value (Revenue)
        cell = ws.cell(row=3, column=2)
        assert cell.font.color is not None

    def test_fill_colors_applied(self):
        from app.core.deliverable_xlsx import apply_cells_to_workbook

        cells = compose_financial_model(FULL_ASSUMPTIONS)
        wb = Workbook()
        apply_cells_to_workbook(wb, cells)

        # Title row should have header fill
        ws = wb[SH_ASSUMPTIONS]
        title_cell = ws.cell(row=1, column=1)
        assert title_cell.fill.start_color.rgb is not None

    def test_number_formats_applied(self):
        from app.core.deliverable_xlsx import apply_cells_to_workbook

        cells = compose_financial_model(FULL_ASSUMPTIONS)
        wb = Workbook()
        apply_cells_to_workbook(wb, cells)

        ws = wb[SH_INCOME]
        # Revenue cell should have currency format
        rev_cell = ws.cell(row=3, column=2)
        assert "$" in rev_cell.number_format or "#,##0" in rev_cell.number_format

    def test_column_widths_auto_sized(self):
        from app.core.deliverable_xlsx import apply_cells_to_workbook

        cells = compose_financial_model(FULL_ASSUMPTIONS)
        wb = Workbook()
        apply_cells_to_workbook(wb, cells)

        ws = wb[SH_ASSUMPTIONS]
        # Column A should be wider than default (8.43)
        col_a_width = ws.column_dimensions["A"].width
        assert col_a_width > 8

    def test_save_and_reload(self):
        """Verify the workbook can be saved and reloaded."""
        from app.core.deliverable_xlsx import apply_cells_to_workbook

        cells = compose_financial_model(FULL_ASSUMPTIONS)
        wb = Workbook()
        apply_cells_to_workbook(wb, cells)

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        wb2 = load_workbook(buf)
        assert len(wb2.sheetnames) >= 7
        assert SH_INCOME in wb2.sheetnames

        # Spot-check: Revenue Year 1 formula preserved
        ws = wb2[SH_INCOME]
        rev_cell = ws.cell(row=3, column=2)
        assert str(rev_cell.value).startswith("=")
