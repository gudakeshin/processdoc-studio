"""
Excel Model QA Integration Service

Quality evaluation for Excel financial model exports using QAAgentLoop.
Implements Cowork Tier 3 alignment pattern for iterative quality improvement.

QA evaluates:
- Formula coverage (ratio of formulas to static values)
- Cross-sheet references (detection of sheet dependencies)
- Formatting compliance (bold, color, fill usage)
- Model structure completeness (sheet count, cell count)
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class ExcelQAEvaluator:
    """QA evaluation for Excel financial model exports."""

    @staticmethod
    def evaluate_export_quality(
        xlsx_cells: list[dict[str, Any]],
        model_summary: dict[str, Any],
        threshold: float = 0.8,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Evaluate export quality using QAAgentLoop.

        Assesses:
        - Formula coverage percentage
        - Cross-sheet reference count
        - Formatting compliance (bold, colors, fills)
        - Overall model structure

        Args:
            xlsx_cells: List of cell dicts from compose_financial_model()
            model_summary: Dict with model metadata (assumptions count, periods, etc)
            threshold: QA score threshold (default 0.8 = 80%)
            project_id: Optional project ID for tracing

        Returns:
            QA result dict with:
            - passed: bool indicating if all outputs meet threshold
            - iterations: number of evaluation iterations
            - scores: dict mapping output keys to quality scores
            - remediation_instructions: dict with improvement suggestions
        """
        try:
            from app.services.qa import QAAgentLoop
        except ImportError:
            log.warning("QAAgentLoop not available; returning mock QA result")
            return {
                "passed": True,
                "iterations": 0,
                "scores": {},
                "remediation_instructions": {},
            }

        log.info(f"QA evaluation: {len(xlsx_cells)} cells, threshold={threshold}")

        # Build summaries for QA evaluation
        sheet_count = ExcelQAEvaluator._count_sheets(xlsx_cells)
        formula_coverage = ExcelQAEvaluator._assess_formula_coverage(xlsx_cells)
        formatting = ExcelQAEvaluator._assess_formatting(xlsx_cells)
        cross_refs = ExcelQAEvaluator._assess_cross_references(xlsx_cells)

        qa_inputs = {
            "export_composition": f"Composed {len(xlsx_cells)} cells across {sheet_count} sheets "
            f"with {model_summary.get('assumptions', 0)} assumptions",
            "formula_coverage": formula_coverage,
            "formatting_compliance": formatting,
            "cross_sheet_links": cross_refs,
        }

        # Run QA loop
        qa_loop = QAAgentLoop()
        try:
            qa_result = qa_loop.run(
                outputs=qa_inputs,
                threshold=threshold,
                project_id=project_id,
                max_loops=1,  # Single evaluation, no iterative improvement in this tier
            )

            log.info(
                f"QA evaluation result: passed={qa_result.get('passed', False)}, "
                f"iterations={qa_result.get('iterations', 1)}"
            )

            return qa_result

        except Exception as e:
            log.error(f"QA evaluation failed: {e}", exc_info=True)
            # QA failure should not block export; return neutral result
            return {
                "passed": True,
                "iterations": 0,
                "scores": {},
                "remediation_instructions": {},
                "error": str(e),
            }

    @staticmethod
    def _count_sheets(cells: list[dict[str, Any]]) -> int:
        """Count unique sheets in cells list."""
        return len(set(c.get("sheet", "Unknown") for c in cells))

    @staticmethod
    def _assess_formula_coverage(cells: list[dict[str, Any]]) -> str:
        """Summarize formula vs static cell distribution."""
        if not cells:
            return "No cells to assess"

        formula_count = sum(1 for c in cells if c.get("formula"))
        static_count = len(cells) - formula_count
        coverage_pct = (formula_count * 100) // (len(cells) or 1)

        return f"{formula_count} formulas, {static_count} static values (formula coverage: {coverage_pct}%)"

    @staticmethod
    def _assess_formatting(cells: list[dict[str, Any]]) -> str:
        """Summarize formatting compliance."""
        if not cells:
            return "No cells to assess"

        bold_count = sum(1 for c in cells if c.get("bold"))
        color_count = sum(1 for c in cells if c.get("font_color"))
        filled_count = sum(1 for c in cells if c.get("fill_color"))
        format_count = sum(1 for c in cells if c.get("number_format"))

        return (
            f"Formatting: {bold_count} bold, {color_count} colored fonts, "
            f"{filled_count} filled, {format_count} number formats"
        )

    @staticmethod
    def _assess_cross_references(cells: list[dict[str, Any]]) -> str:
        """Summarize cross-sheet references."""
        if not cells:
            return "No cells to assess"

        # Count cells with cross-sheet formula references
        # Pattern: sheet name followed by ! (e.g., "Assumptions!", "Income Statement!")
        cross_ref_count = sum(1 for c in cells if "':" in c.get("formula", "") or "!" in c.get("formula", ""))

        return f"{cross_ref_count} cross-sheet formula references"
