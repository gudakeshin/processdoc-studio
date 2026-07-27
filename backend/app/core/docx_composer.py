"""DOCX composer — the python-docx analogue of ``EditorialSlideComposer``.

Turns parsed markdown blocks (plus optional enriched callout/kpi blocks) into a
themed document via ``docx_components``. Records format-appropriate "overflow"
signals (over-budget headings, wide tables) into ``fit_report`` for QA, the same
way the editorial deck composer records trims.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from docx import Document

from app.core import docx_components as C
from app.core.doc_theme import DocTheme

logger = logging.getLogger(__name__)

# Format-appropriate char budgets (DOCX reflows, so these flag readability, not clipping).
_HEADING_BUDGET = 120
# Page content width (8.5" − 2.5" margins ≈ 6") fits ~8 comfortable columns.
_MAX_TABLE_COLS = 8
_CROSS_REF_RE = re.compile(r"\[(fig|tbl):([^\]]+)\]")


class DocxComposer:
    def __init__(self, doc: Document, theme: DocTheme):
        self.doc = doc
        self.theme = theme
        self.fit_report: list[dict[str, Any]] = []
        self._fig_count = 0
        self._tbl_count = 0
        self._figure_ids: dict[str, int] = {}
        self._table_ids: dict[str, int] = {}
        self._unresolved_tokens: list[str] = []

    def _record(self, kind: str, detail: str) -> None:
        self.fit_report.append({"kind": kind, "detail": detail})

    def register_figure_id(self, fig_id: str, number: int) -> None:
        self._figure_ids[str(fig_id)] = number

    def register_table_id(self, tbl_id: str, number: int) -> None:
        self._table_ids[str(tbl_id)] = number

    def _write_text_with_refs(self, text: str, *, style: str | None = None) -> None:
        """Emit a paragraph; convert ``[fig:id]`` / ``[tbl:id]`` to Word REF fields."""
        if not _CROSS_REF_RE.search(text or ""):
            C.body_paragraph(self.doc, self.theme, text, style=style)
            return
        para = self.doc.add_paragraph(style=style)
        C.append_text_with_cross_refs(
            para,
            self.theme,
            text,
            figure_ids=self._figure_ids,
            table_ids=self._table_ids,
            unresolved=self._unresolved_tokens,
        )

    def compose(self, blocks: list[dict[str, Any]]) -> None:
        for block in blocks:
            btype = block.get("type")
            if btype == "heading":
                self._heading(block)
            elif btype == "paragraph":
                self._write_text_with_refs(str(block.get("text") or ""))
            elif btype == "pull_quote":
                C.pull_quote(self.doc, self.theme, str(block.get("text") or ""))
            elif btype == "executive_callout":
                C.executive_callout(self.doc, self.theme, str(block.get("text") or ""))
            elif btype == "bullets":
                for item in block.get("items", []):
                    self._write_text_with_refs(str(item or ""), style="List Bullet")
            elif btype == "numbered":
                for item in block.get("items", []):
                    self._write_text_with_refs(str(item or ""), style="List Number")
            elif btype == "code":
                C.code_block(self.doc, self.theme, str(block.get("text") or ""))
            elif btype == "table":
                self._table(block)
            elif btype == "callout":
                C.callout(
                    self.doc,
                    self.theme,
                    str(block.get("text") or ""),
                    subtype=str(block.get("subtype") or "note"),
                )
            elif btype == "kpi":
                C.kpi_table(self.doc, self.theme, block.get("stats") or [])
            elif btype == "figure":
                self._figure(block)
        if self._unresolved_tokens:
            self._record("unresolved_cross_refs", ", ".join(self._unresolved_tokens[:8]))

    def _figure(self, block: dict[str, Any]) -> None:
        spec = block.get("figure") if isinstance(block.get("figure"), dict) else None
        if not spec or not str(spec.get("type") or "").strip():
            return
        self._fig_count += 1
        fig_id = str(block.get("id") or spec.get("type") or self._fig_count)
        self.register_figure_id(fig_id, self._fig_count)
        result = C.embed_figure(
            self.doc, self.theme, spec,
            caption=str(block.get("caption") or ""),
            number=self._fig_count,
        )
        if result is None:
            self._fig_count -= 1
            self._figure_ids.pop(fig_id, None)
            self._record("figure_skipped", f"figure '{spec.get('type')}' could not render")

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
        self._tbl_count += 1
        tbl_id = str(block.get("id") or self._tbl_count)
        self.register_table_id(tbl_id, self._tbl_count)
        cols = max(len(r) for r in rows)
        if cols > _MAX_TABLE_COLS:
            self._record("table_overflow", f"table has {cols} cols > {_MAX_TABLE_COLS} (page width)")
        C.styled_table(self.doc, self.theme, rows, header=True)
        caption = str(block.get("caption") or "").strip()
        from app.core.config import settings

        if getattr(settings, "docx_formatting_v2_enabled", False):
            C.table_caption(
                self.doc,
                self.theme,
                caption or f"Table {self._tbl_count}",
                number=self._tbl_count,
                bookmark_id=f"tbl_{tbl_id}",
            )
