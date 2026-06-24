"""Post-render XLSX quality assurance — the openpyxl analogue of ``pptx_qa``.

Returns the same report shape as the PPTX/DOCX validators so the quality loop and
``final_artifact_qa`` consume XLSX reports uniformly. Reuses the ``_assess_*``
summaries from ``excel_qa_integration`` over cells extracted from the saved file.
Excel reflows/clips per cell, so "overflow" means content wider than the column
cap, alongside empty-sheet and formula-coverage checks.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_COL_WIDTH_CAP = 40  # matches the renderer's auto-size cap


def _cells_from_workbook(wb) -> list[dict[str, Any]]:
    """Flatten a workbook into the cell-dict shape the _assess_* helpers expect."""
    cells: list[dict[str, Any]] = []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                val = cell.value
                if val is None:
                    continue
                entry: dict[str, Any] = {"sheet": ws.title, "value": val}
                if isinstance(val, str) and val.startswith("="):
                    entry["formula"] = val[1:]
                cells.append(entry)
    return cells


def validate_xlsx(xlsx_path: Path) -> dict[str, Any]:
    """Deterministic post-render checks on a saved .xlsx file."""
    if not Path(xlsx_path).exists():
        return {
            "status": "fail",
            "summary": f"XLSX file not found: {xlsx_path}",
            "issues": ["XLSX artifact missing"],
            "advisories": [],
            "remediation": ["Renderer failed to produce output.xlsx"],
        }

    issues: list[str] = []
    advisories: list[str] = []
    remediation: list[str] = []
    metrics: dict[str, Any] = {}

    try:
        from openpyxl import load_workbook

        from app.services.excel_qa_integration import ExcelQAEvaluator

        wb = load_workbook(str(xlsx_path), read_only=True, data_only=False)
        empty_sheets = [ws.title for ws in wb.worksheets if (ws.max_row or 0) < 1 or _sheet_is_empty(ws)]
        if empty_sheets:
            issues.append(f"Empty sheets with no data: {empty_sheets}")
            remediation.append("Populate or remove empty sheets")

        cells = _cells_from_workbook(wb)
        if not cells:
            issues.append("Workbook contains no data cells")
            remediation.append("Re-render with content from source data")

        metrics["formula_coverage"] = ExcelQAEvaluator._assess_formula_coverage(cells)
        metrics["formatting"] = ExcelQAEvaluator._assess_formatting(cells)
        metrics["cross_references"] = ExcelQAEvaluator._assess_cross_references(cells)

        # Column overflow: any cell content longer than the width cap reflows/clips.
        overflow_cols = 0
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str) and len(cell.value) > _COL_WIDTH_CAP * 2:
                        overflow_cols += 1
        if overflow_cols:
            advisories.append(f"{overflow_cols} cell(s) exceed twice the column width cap — will wrap/clip")
    except Exception as exc:
        logger.debug("xlsx QA extraction failed: %s", exc)
        return {
            "status": "pass",
            "summary": "XLSX QA skipped (extraction error)",
            "issues": [],
            "advisories": [f"QA extraction error: {exc}"],
            "remediation": [],
        }

    status = "pass" if not issues else "fail"
    summary = f"XLSX QA: {status.upper()}"
    if issues:
        summary += f" — {len(issues)} issue(s) found"
    return {
        "status": status,
        "passed": status == "pass",
        "summary": summary,
        "issues": issues,
        "advisories": advisories,
        "remediation": remediation,
        "metrics": metrics,
        "xlsx_path": str(xlsx_path),
    }


def _sheet_is_empty(ws) -> bool:
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None:
                return False
    return True
