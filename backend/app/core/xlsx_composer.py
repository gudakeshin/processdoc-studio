"""XLSX composer — the openpyxl analogue of ``EditorialSlideComposer``.

Routes a deliverable payload through the themed component library: the typed-cell
path reuses the battle-tested ``apply_cells_to_workbook`` (kept in
``deliverable_xlsx`` for its external importers), while the markdown/process-model
fallback is rendered via ``xlsx_components.write_section``. Records
format-appropriate "overflow" signals into ``fit_report`` for QA.
"""

from __future__ import annotations

import logging
from typing import Any

from openpyxl import Workbook

from app.core import xlsx_components as C
from app.core.deliverable_utils import rows_from_markdown, rows_from_process_model
from app.core.doc_theme import DocTheme

logger = logging.getLogger(__name__)

_COL_WIDTH_CAP = 40


class XlsxComposer:
    def __init__(self, wb: Workbook, theme: DocTheme):
        self.wb = wb
        self.theme = theme
        self.fit_report: list[dict[str, Any]] = []
        C.register_theme_styles(wb, theme)

    def _record(self, kind: str, detail: str) -> None:
        self.fit_report.append({"kind": kind, "detail": detail})

    def compose(self, payload: dict[str, Any]) -> None:
        typed_cells = payload.get("xlsx_cells")
        if isinstance(typed_cells, list) and typed_cells:
            # Lazy import avoids a circular import with deliverable_xlsx.
            from app.core.deliverable_xlsx import apply_cells_to_workbook

            apply_cells_to_workbook(self.wb, typed_cells, header_fill=self.theme.hex6("primary"))
            self._scan_overflow(typed_cells)
            return

        rows = self._fallback_rows(payload)
        ws = self.wb.active
        ws.title = "Output"
        C.write_section(ws, self.theme, rows, start_row=1, header=True)
        if len(rows) <= 1:
            self._record("empty_content", "fallback produced no data rows")

    def _fallback_rows(self, payload: dict[str, Any]) -> list[list[str]]:
        rows: list[list[str]] = []
        if isinstance(payload.get("xlsx_markdown"), str):
            rows = rows_from_markdown(str(payload.get("xlsx_markdown") or ""))
        if not rows and isinstance(payload.get("raci_markdown"), str):
            rows = rows_from_markdown(str(payload.get("raci_markdown") or ""))
        if not rows and isinstance(payload.get("process_model"), dict):
            rows = rows_from_process_model(payload.get("process_model") or {})
        if not rows:
            rows = [
                ["Section", "Content"],
                ["Summary", str(payload.get("narrative_md") or "No content generated")],
            ]
        return rows

    def _scan_overflow(self, cells: list[dict[str, Any]]) -> None:
        wide = sum(
            1 for c in cells
            if isinstance(c, dict) and isinstance(c.get("value"), str)
            and len(c["value"]) > _COL_WIDTH_CAP * 2
        )
        if wide:
            self._record("column_overflow", f"{wide} cell(s) exceed twice the column width cap")
