from __future__ import annotations

import contextlib
import logging
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, PieChart, Reference
from openpyxl.styles import (
    Alignment,
    Border,
    Font,
    NamedStyle,
    PatternFill,
    Side,
)
from openpyxl.styles.numbers import FORMAT_NUMBER_COMMA_SEPARATED1, FORMAT_PERCENTAGE_00
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from app.core.deliverable import DeliverableMetadata, IDeliverable
from app.core.deliverable_utils import rows_from_markdown, rows_from_process_model

logger = logging.getLogger(__name__)

_THIN = Side(style="thin")
_THICK = Side(style="medium")
_NONE = Side(style=None)
_BORDER_THIN = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_BORDER_THICK_BOTTOM = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THICK)
_ALIGN_WRAP = Alignment(wrap_text=True, vertical="top")
_ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
_ALIGN_RIGHT = Alignment(horizontal="right", vertical="center")


def _build_named_styles(primary_hex: str = "86BC25") -> list[NamedStyle]:
    """Return brand-consistent NamedStyles. Safe to call multiple times — styles are wb-local."""
    ph = primary_hex.lstrip("#").upper()
    if len(ph) != 6:
        ph = "86BC25"

    def _style(name: str, bold: bool, fill_hex: str | None, font_color: str = "000000",
                border: Border = _BORDER_THIN, align: Alignment = _ALIGN_WRAP,
                num_fmt: str | None = None) -> NamedStyle:
        ns = NamedStyle(name=name)
        ns.font = Font(bold=bold, color=font_color, size=10)
        ns.border = border
        ns.alignment = align
        if fill_hex:
            fh = fill_hex.lstrip("#").upper()
            if len(fh) == 6:
                ns.fill = PatternFill("solid", fgColor=fh)
        if num_fmt:
            ns.number_format = num_fmt
        return ns

    return [
        _style("brand_header", bold=True, fill_hex=ph, font_color="FFFFFF",
               border=_BORDER_THICK_BOTTOM, align=_ALIGN_CENTER),
        _style("brand_total", bold=True, fill_hex="F2F2F2"),
        _style("brand_input", bold=False, fill_hex="EAF4E0"),
        _style("brand_calc", bold=False, fill_hex="FFFDE7"),
        _style("brand_link", bold=False, fill_hex=None, font_color="0563C1"),
        _style("brand_variance_pos", bold=False, fill_hex=None, num_fmt='#,##0.00;[Red]-#,##0.00'),
        _style("brand_variance_neg", bold=False, fill_hex=None, font_color="CC0000"),
        _style("brand_currency", bold=False, fill_hex=None, num_fmt=FORMAT_NUMBER_COMMA_SEPARATED1),
        _style("brand_pct", bold=False, fill_hex=None, num_fmt=FORMAT_PERCENTAGE_00),
    ]


def _register_styles(wb: Workbook, primary_hex: str) -> None:
    existing = {s.name for s in wb._named_styles}  # noqa: SLF001
    for ns in _build_named_styles(primary_hex):
        if ns.name not in existing:
            wb.add_named_style(ns)


def _add_chart(ws: Any, chart_def: dict[str, Any], anchor: str) -> None:
    """Add a chart from a chart_def dict: {type, data_range, title, sheet}."""
    ctype = str(chart_def.get("type") or "bar").lower()
    title = str(chart_def.get("title") or "")
    min_row = int(chart_def.get("min_row") or 1)
    max_row = int(chart_def.get("max_row") or 2)
    min_col = int(chart_def.get("min_col") or 1)
    max_col = int(chart_def.get("max_col") or 2)
    titles_from_data = bool(chart_def.get("titles_from_data", True))
    cats_col = int(chart_def.get("cats_col") or min_col)

    if ctype == "line":
        chart: Any = LineChart()
    elif ctype == "pie":
        chart = PieChart()
    else:
        chart = BarChart()
        chart.type = "col"
        chart.grouping = "clustered"

    if title:
        chart.title = title
    chart.style = 10

    data = Reference(ws, min_col=min_col + 1, min_row=min_row, max_col=max_col, max_row=max_row)
    chart.add_data(data, titles_from_data=titles_from_data)

    cats = Reference(ws, min_col=cats_col, min_row=min_row + (1 if titles_from_data else 0), max_row=max_row)
    with contextlib.suppress(Exception):
        chart.set_categories(cats)

    chart.height = float(chart_def.get("height") or 10)
    chart.width = float(chart_def.get("width") or 18)
    ws.add_chart(chart, anchor or "A1")


def _add_table(ws: Any, name: str, ref: str, display_name: str, style_name: str = "TableStyleMedium9") -> None:
    tab = Table(displayName=display_name, ref=ref)
    tab.tableStyleInfo = TableStyleInfo(
        name=style_name, showFirstColumn=False, showLastColumn=False,
        showRowStripes=True, showColumnStripes=False,
    )
    try:
        ws.add_table(tab)
    except Exception as exc:
        logger.debug("Table add skipped (%s): %s", name, exc)


def apply_cells_to_workbook(
    wb: Workbook,
    cells: list[dict[str, Any]],
    header_fill: str = "D9E1F2",
) -> None:
    """Write a list of xlsx_cell dicts into an openpyxl Workbook.

    Supports: value, formula, bold, italic, font_color, fill_color, number_format,
    border (thin|thick|none), align (left|center|right), wrap, named_style, chart.
    """
    by_sheet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    charts_by_sheet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tables_by_sheet: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for item in cells:
        if not isinstance(item, dict):
            continue
        sheet = str(item.get("sheet") or "Output")
        if item.get("_type") == "chart":
            charts_by_sheet[sheet].append(item)
        elif item.get("_type") == "table":
            tables_by_sheet[sheet].append(item)
        else:
            by_sheet[sheet].append(item)

    all_sheets = list(dict.fromkeys(
        list(by_sheet) + list(charts_by_sheet) + list(tables_by_sheet)
    ))
    if not all_sheets:
        all_sheets = ["Output"]

    first = True
    for sheet_name in all_sheets:
        ws = wb.active if first else wb.create_sheet(title=(sheet_name[:31] or "Output"))
        ws.title = sheet_name[:31] or "Output"
        first = False

        col_widths: dict[int, int] = {}
        max_row_seen = 1

        for cell_data in by_sheet.get(sheet_name, []):
            row = max(1, int(cell_data.get("row") or 1))
            col = max(1, int(cell_data.get("col") or 1))
            cell = ws.cell(row=row, column=col)
            max_row_seen = max(max_row_seen, row)

            named_style = str(cell_data.get("named_style") or "").strip()
            if named_style:
                with contextlib.suppress(Exception):
                    cell.style = named_style

            if "formula" in cell_data:
                cell.value = f"={cell_data['formula']}"
            else:
                cell.value = cell_data.get("value")

            font_kwargs: dict[str, Any] = {}
            if cell_data.get("bold"):
                font_kwargs["bold"] = True
            if cell_data.get("italic"):
                font_kwargs["italic"] = True
            if cell_data.get("font_color"):
                fc = str(cell_data["font_color"]).strip().replace("#", "").upper()
                if len(fc) == 6:
                    font_kwargs["color"] = fc
            if font_kwargs and not named_style:
                cell.font = Font(**font_kwargs)

            if cell_data.get("fill_color") and not named_style:
                fh = str(cell_data["fill_color"]).strip().replace("#", "").upper()
                if len(fh) == 6:
                    cell.fill = PatternFill(start_color=fh, end_color=fh, fill_type="solid")

            if cell_data.get("number_format"):
                cell.number_format = str(cell_data["number_format"])

            border_mode = str(cell_data.get("border") or "").lower()
            if border_mode and not named_style:
                if border_mode == "thin":
                    cell.border = _BORDER_THIN
                elif border_mode in ("thick", "medium"):
                    cell.border = _BORDER_THICK_BOTTOM
                elif border_mode == "none":
                    cell.border = Border()

            align_mode = str(cell_data.get("align") or "").lower()
            wrap = bool(cell_data.get("wrap"))
            if (align_mode or wrap) and not named_style:
                horiz = {"left": "left", "center": "center", "right": "right"}.get(align_mode)
                cell.alignment = Alignment(horizontal=horiz, wrap_text=wrap, vertical="top")

            content_len = len(str(cell.value or ""))
            col_widths[col] = max(col_widths.get(col, 8), min(content_len + 2, 40))

        for col_num, width in col_widths.items():
            ws.column_dimensions[get_column_letter(col_num)].width = width

        # Freeze panes at A2 for any sheet with data
        if by_sheet.get(sheet_name):
            ws.freeze_panes = "A2"

        # Tables
        for tdef in tables_by_sheet.get(sheet_name, []):
            ref = str(tdef.get("ref") or "")
            dname = str(tdef.get("display_name") or sheet_name.replace(" ", "_"))
            style = str(tdef.get("table_style") or "TableStyleMedium9")
            if ref:
                _add_table(ws, sheet_name, ref, dname, style)

        # Charts (added after data so Reference rows are populated)
        for cdef in charts_by_sheet.get(sheet_name, []):
            anchor = str(cdef.get("anchor") or f"{get_column_letter(max(1, int(cdef.get('max_col', 2)) + 2))}2")
            try:
                _add_chart(ws, cdef, anchor)
            except Exception as exc:
                logger.warning("Chart add failed (%s): %s", sheet_name, exc)


class XLSXDeliverable(IDeliverable):
    def get_metadata(self) -> DeliverableMetadata:
        return DeliverableMetadata(
            output_type="xlsx",
            file_extension=".xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            intermediate_format="table",
            skill_output_key="xlsx_markdown",
        )

    def render(self, payload: dict[str, Any], run_dir: Path, branding: Any | None = None) -> Path | None:
        out = run_dir / "output.xlsx"
        wb = Workbook()

        primary_hex = ""
        if branding is not None:
            primary_hex = str(getattr(branding, "primary_color", "") or "").strip().replace("#", "")
        if len(primary_hex) != 6:
            primary_hex = "86BC25"

        _register_styles(wb, primary_hex)
        header_fill = primary_hex.upper()

        self._apply_workbook_properties(wb, payload, branding)

        typed_cells = payload.get("xlsx_cells")
        if isinstance(typed_cells, list) and typed_cells:
            apply_cells_to_workbook(wb, typed_cells, header_fill=header_fill)
        else:
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

            ws = wb.active
            ws.title = "Output"
            for r_idx, row in enumerate(rows, start=1):
                for c_idx, value in enumerate(row, start=1):
                    cell = ws.cell(row=r_idx, column=c_idx, value=value)
                    if r_idx == 1:
                        try:
                            cell.style = "brand_header"
                        except Exception:
                            cell.font = Font(bold=True)
                            fh = header_fill.upper()
                            if len(fh) == 6:
                                cell.fill = PatternFill(start_color=fh, end_color=fh, fill_type="solid")
                    else:
                        cell.border = _BORDER_THIN
                        cell.alignment = _ALIGN_WRAP

            # Auto-size
            for col_cells in ws.columns:
                width = max((len(str(c.value or "")) for c in col_cells), default=8)
                ws.column_dimensions[get_column_letter(col_cells[0].column)].width = min(width + 2, 40)

            if len(rows) > 1:
                ws.freeze_panes = "A2"

        wb.save(out)
        return out

    def _apply_workbook_properties(self, wb: Workbook, payload: dict[str, Any], branding: Any) -> None:
        try:
            props = wb.properties
            props.creator = str(
                getattr(branding, "company_name", None) or payload.get("owner_name") or "ProcessDoc Studio"
            )
            pm = payload.get("process_model") if isinstance(payload.get("process_model"), dict) else {}
            props.title = str(
                payload.get("presentation_title") or pm.get("process_name") or "ProcessDoc Output"
            )[:255]
            props.company = str(getattr(branding, "company_name", None) or "")[:255]
            props.modified = datetime.now(UTC)
        except Exception as exc:
            logger.debug("Workbook properties skipped: %s", exc)

    def extract_quality_signals(self, artifact_path: Path) -> dict[str, Any]:
        try:
            from openpyxl import load_workbook

            wb = load_workbook(str(artifact_path), read_only=True, data_only=True)
            rows = 0
            cols = 0
            for ws in wb.worksheets:
                rows = max(rows, int(getattr(ws, "max_row", 0) or 0))
                cols = max(cols, int(getattr(ws, "max_column", 0) or 0))
            return {"sheet_count": len(wb.sheetnames), "max_rows": rows, "max_cols": cols}
        except Exception:
            return super().extract_quality_signals(artifact_path)
