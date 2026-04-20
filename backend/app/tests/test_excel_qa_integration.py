"""Tests for Excel QA integration service (Cowork Tier 3)."""


from app.services.excel_qa_integration import ExcelQAEvaluator


class TestExcelQAEvaluatorCountSheets:
    """Test sheet counting functionality."""

    def test_count_sheets_empty(self):
        """Empty cells list returns 0 sheets."""
        cells = []
        count = ExcelQAEvaluator._count_sheets(cells)
        assert count == 0

    def test_count_sheets_single(self):
        """Single sheet counted correctly."""
        cells = [
            {"sheet": "Assumptions", "row": 1, "col": 1},
            {"sheet": "Assumptions", "row": 2, "col": 1},
        ]
        count = ExcelQAEvaluator._count_sheets(cells)
        assert count == 1

    def test_count_sheets_multiple(self):
        """Multiple sheets counted correctly."""
        cells = [
            {"sheet": "Assumptions", "row": 1, "col": 1},
            {"sheet": "Income Statement", "row": 1, "col": 1},
            {"sheet": "Balance Sheet", "row": 1, "col": 1},
        ]
        count = ExcelQAEvaluator._count_sheets(cells)
        assert count == 3

    def test_count_sheets_missing_sheet_key(self):
        """Missing sheet key treated as 'Unknown'."""
        cells = [
            {"row": 1, "col": 1},  # No sheet key
            {"sheet": "Assumptions", "row": 2, "col": 1},
        ]
        count = ExcelQAEvaluator._count_sheets(cells)
        assert count == 2  # Unknown + Assumptions


class TestExcelQAEvaluatorFormulaCoverage:
    """Test formula coverage assessment."""

    def test_formula_coverage_no_cells(self):
        """Empty cells list returns appropriate message."""
        result = ExcelQAEvaluator._assess_formula_coverage([])
        assert "No cells" in result

    def test_formula_coverage_all_formulas(self):
        """All formulas returns 100% coverage."""
        cells = [
            {"sheet": "Test", "row": 1, "col": 1, "formula": "=A1+B1"},
            {"sheet": "Test", "row": 2, "col": 1, "formula": "=A2+B2"},
        ]
        result = ExcelQAEvaluator._assess_formula_coverage(cells)
        assert "2 formulas" in result
        assert "0 static" in result
        assert "100%" in result

    def test_formula_coverage_all_static(self):
        """All static cells returns 0% coverage."""
        cells = [
            {"sheet": "Test", "row": 1, "col": 1, "value": 1},
            {"sheet": "Test", "row": 2, "col": 1, "value": 2},
        ]
        result = ExcelQAEvaluator._assess_formula_coverage(cells)
        assert "0 formulas" in result
        assert "2 static" in result
        assert "0%" in result

    def test_formula_coverage_mixed(self):
        """Mixed formulas and static cells."""
        cells = [
            {"sheet": "Test", "row": 1, "col": 1, "formula": "=A1+B1"},
            {"sheet": "Test", "row": 2, "col": 1, "value": 2},
            {"sheet": "Test", "row": 3, "col": 1, "formula": "=A3+B3"},
        ]
        result = ExcelQAEvaluator._assess_formula_coverage(cells)
        assert "2 formulas" in result
        assert "1 static" in result
        assert "66%" in result


class TestExcelQAEvaluatorFormatting:
    """Test formatting compliance assessment."""

    def test_formatting_no_cells(self):
        """Empty cells list returns appropriate message."""
        result = ExcelQAEvaluator._assess_formatting([])
        assert "No cells" in result

    def test_formatting_with_bold(self):
        """Bold cells counted."""
        cells = [
            {"sheet": "Test", "row": 1, "col": 1, "bold": True},
            {"sheet": "Test", "row": 2, "col": 1, "bold": True},
        ]
        result = ExcelQAEvaluator._assess_formatting(cells)
        assert "2 bold" in result

    def test_formatting_with_colors(self):
        """Font colors counted."""
        cells = [
            {"sheet": "Test", "row": 1, "col": 1, "font_color": "0000FF"},
            {"sheet": "Test", "row": 2, "col": 1, "font_color": "008000"},
        ]
        result = ExcelQAEvaluator._assess_formatting(cells)
        assert "2 colored fonts" in result

    def test_formatting_with_fills(self):
        """Fill colors counted."""
        cells = [
            {"sheet": "Test", "row": 1, "col": 1, "fill_color": "FFFF00"},
            {"sheet": "Test", "row": 2, "col": 1, "fill_color": "FFFF00"},
        ]
        result = ExcelQAEvaluator._assess_formatting(cells)
        assert "2 filled" in result

    def test_formatting_with_number_formats(self):
        """Number formats counted."""
        cells = [
            {"sheet": "Test", "row": 1, "col": 1, "number_format": "$#,##0"},
            {"sheet": "Test", "row": 2, "col": 1, "number_format": "0.0%"},
        ]
        result = ExcelQAEvaluator._assess_formatting(cells)
        assert "2 number formats" in result

    def test_formatting_comprehensive(self):
        """All formatting types combined."""
        cells = [
            {
                "sheet": "Test",
                "row": 1,
                "col": 1,
                "bold": True,
                "font_color": "0000FF",
                "fill_color": "FFFF00",
                "number_format": "$#,##0",
            },
        ]
        result = ExcelQAEvaluator._assess_formatting(cells)
        assert "1 bold" in result
        assert "1 colored" in result
        assert "1 filled" in result
        assert "1 number format" in result


class TestExcelQAEvaluatorCrossReferences:
    """Test cross-sheet reference detection."""

    def test_cross_references_none(self):
        """No cross-references returns appropriate count."""
        cells = [
            {"sheet": "Test", "row": 1, "col": 1, "formula": "=A1+B1"},
        ]
        result = ExcelQAEvaluator._assess_cross_references(cells)
        assert "0 cross-sheet" in result

    def test_cross_references_with_colon_pattern(self):
        """Detect pattern with colon (e.g., 'Sheet':A1)."""
        cells = [
            {"sheet": "Test", "row": 1, "col": 1, "formula": "='Assumptions':B3"},
        ]
        result = ExcelQAEvaluator._assess_cross_references(cells)
        assert "1 cross-sheet" in result

    def test_cross_references_with_exclamation_pattern(self):
        """Detect pattern with exclamation mark (e.g., Sheet!A1)."""
        cells = [
            {"sheet": "Test", "row": 1, "col": 1, "formula": "=Assumptions!B3"},
        ]
        result = ExcelQAEvaluator._assess_cross_references(cells)
        assert "1 cross-sheet" in result

    def test_cross_references_multiple(self):
        """Count multiple cross-references."""
        cells = [
            {"sheet": "Test", "row": 1, "col": 1, "formula": "='Assumptions':B3"},
            {"sheet": "Test", "row": 2, "col": 1, "formula": "='Income Statement':C5"},
            {"sheet": "Test", "row": 3, "col": 1, "formula": "=A1+B1"},  # No cross-ref
        ]
        result = ExcelQAEvaluator._assess_cross_references(cells)
        assert "2 cross-sheet" in result


class TestExcelQAEvaluatorIntegration:
    """Test QA evaluation with QAAgentLoop integration."""

    def test_evaluate_export_quality_returns_dict(self):
        """QA evaluation returns proper result dict structure."""
        cells = [
            {"sheet": "Assumptions", "row": 1, "col": 1, "value": 1000000},
            {"sheet": "Income Statement", "row": 1, "col": 1, "formula": "=A1+B1"},
        ]

        # Will gracefully handle missing QAAgentLoop
        result = ExcelQAEvaluator.evaluate_export_quality(
            xlsx_cells=cells,
            model_summary={"assumptions": 10, "periods": 5},
            threshold=0.8,
            project_id="test-project",
        )

        # Should have expected keys
        assert isinstance(result, dict)
        assert "passed" in result
        assert "iterations" in result
        assert "scores" in result

    def test_evaluate_export_quality_with_empty_cells(self):
        """QA evaluation handles empty cells list."""
        result = ExcelQAEvaluator.evaluate_export_quality(
            xlsx_cells=[],
            model_summary={"assumptions": 10, "periods": 5},
            threshold=0.8,
        )

        assert isinstance(result, dict)
        assert "passed" in result

    def test_evaluate_with_different_thresholds(self):
        """QA evaluation accepts various threshold values."""
        cells = [{"sheet": "Test", "row": 1, "col": 1}]

        # Test multiple thresholds
        for threshold in [0.5, 0.8, 0.95]:
            result = ExcelQAEvaluator.evaluate_export_quality(
                xlsx_cells=cells,
                model_summary={"assumptions": 10, "periods": 5},
                threshold=threshold,
            )
            assert isinstance(result, dict)

    def test_evaluate_graceful_fallback_when_qa_unavailable(self):
        """QA evaluation returns neutral result gracefully when service unavailable."""
        cells = [{"sheet": "Test", "row": 1, "col": 1}]

        # The function should handle missing QAAgentLoop gracefully
        result = ExcelQAEvaluator.evaluate_export_quality(
            xlsx_cells=cells,
            model_summary={"assumptions": 10, "periods": 5},
        )

        # Should return neutral/safe result
        assert result["passed"] is True
        assert result["iterations"] >= 0
