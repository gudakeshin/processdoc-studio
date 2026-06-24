"""DOCX composer — the python-docx analogue of ``EditorialSlideComposer``.

Turns parsed markdown blocks (plus optional enriched callout/kpi blocks) into a
themed document via ``docx_components``. Records format-appropriate "overflow"
signals (over-budget headings, wide tables) into ``fit_report`` for QA, the same
way the editorial deck composer records trims.
"""

from __future__ import annotations

import logging
from typing import Any

from docx import Document

from app.core import docx_components as C
from app.core.doc_theme import DocTheme

logger = logging.getLogger(__name__)

# Format-appropriate char budgets (DOCX reflows, so these flag readability, not clipping).
_HEADING_BUDGET = 120
# Page content width (8.5" − 2.5" margins ≈ 6") fits ~8 comfortable columns.
_MAX_TABLE_COLS = 8


class DocxComposer:
    def __init__(self, doc: Document, theme: DocTheme):
        self.doc = doc
        self.theme = theme
        self.fit_report: list[dict[str, Any]] = []

    def _record(self, kind: str, detail: str) -> None:
        self.fit_report.append({"kind": kind, "detail": detail})

    def compose(self, blocks: list[dict[str, Any]]) -> None:
        for block in blocks:
            btype = block.get("type")
            if btype == "heading":
                self._heading(block)
            elif btype == "paragraph":
                C.body_paragraph(self.doc, self.theme, str(block.get("text") or ""))
            elif btype == "bullets":
                for item in block.get("items", []):
                    C.body_paragraph(self.doc, self.theme, str(item or ""), style="List Bullet")
            elif btype == "numbered":
                for item in block.get("items", []):
                    C.body_paragraph(self.doc, self.theme, str(item or ""), style="List Number")
            elif btype == "code":
                C.code_block(self.doc, self.theme, str(block.get("text") or ""))
            elif btype == "table":
                self._table(block)
            elif btype == "callout":
                C.callout(self.doc, self.theme, str(block.get("text") or ""))
            elif btype == "kpi":
                C.kpi_table(self.doc, self.theme, block.get("stats") or [])

    def _heading(self, block: dict[str, Any]) -> None:
        text = str(block.get("text") or "")
        level = min(4, max(1, int(block.get("level", 1) or 1)))
        if len(text) > _HEADING_BUDGET:
            self._record("heading_overflow", f"L{level} heading {len(text)} chars > {_HEADING_BUDGET}")
        heading = self.doc.add_heading(text, level=level)
        for run in heading.runs:
            run.font.name = self.theme.font_header

    def _table(self, block: dict[str, Any]) -> None:
        rows = block.get("rows") or []
        if not rows:
            return
        cols = max(len(r) for r in rows)
        if cols > _MAX_TABLE_COLS:
            self._record("table_overflow", f"table has {cols} cols > {_MAX_TABLE_COLS} (page width)")
        C.styled_table(self.doc, self.theme, rows, header=True)
