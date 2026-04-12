from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.core.deliverable import DeliverableMetadata, IDeliverable
from app.core.deliverable_utils import rows_from_markdown, rows_from_process_model


def apply_cells_to_workbook(
    wb: Workbook,
    cells: list[dict[str, Any]],
    header_fill: str = "D9E1F2",
) -> None:
    """Write a list of xlsx_cell dicts into an openpyxl Workbook.

    Supports: value, formula, bold, font_color, fill_color, number_format.
    Auto-sizes column widths after writing.

    This is the shared cell-writing utility used by both XLSXDeliverable.render()
    and the model export endpoint.
    """
    by_sheet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in cells:
        if isinstance(item, dict):
            by_sheet[str(item.get("sheet") or "Output")].append(item)

    first = True
    for sheet_name, sheet_cells in by_sheet.items():
        ws = wb.active if first else wb.create_sheet(title=(sheet_name[:31] or "Output"))
        ws.title = sheet_name[:31] or "Output"
        first = False

        col_widths: dict[int, int] = {}  # track max content width per column

        for cell_data in sheet_cells:
            row = max(1, int(cell_data.get("row") or 1))
            col = max(1, int(cell_data.get("col") or 1))
            cell = ws.cell(row=row, column=col)

            # Set value (formula or direct value)
            if "formula" in cell_data:
                cell.value = f"={cell_data.get('formula')}"
            else:
                cell.value = cell_data.get("value")

            # Build combined Font object (bold + color)
            font_kwargs: dict[str, Any] = {}
            if cell_data.get("bold"):
                font_kwargs["bold"] = True
            if cell_data.get("font_color"):
                fc = str(cell_data["font_color"]).strip().replace("#", "").upper()
                if len(fc) == 6:
                    font_kwargs["color"] = fc
            if font_kwargs:
                cell.font = Font(**font_kwargs)

            if cell_data.get("fill_color"):
                fill_color = str(cell_data.get("fill_color")).strip().replace("#", "").upper()
                if len(fill_color) == 6:
                    cell.fill = PatternFill(start_color=fill_color, end_color=fill_color, fill_type="solid")

            if cell_data.get("number_format"):
                cell.number_format = str(cell_data.get("number_format"))

            # Track column width
            content_len = len(str(cell.value or ""))
            col_widths[col] = max(col_widths.get(col, 8), min(content_len + 2, 40))

        # Auto-size columns
        for col_num, width in col_widths.items():
            ws.column_dimensions[get_column_letter(col_num)].width = width


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
        header_fill = "D9E1F2"
        if branding is not None:
            primary = str(getattr(branding, "primary_color", "") or "").strip().replace("#", "")
            if len(primary) == 6:
                header_fill = primary.upper()
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
                rows = [["Section", "Content"], ["Summary", str(payload.get("narrative_md") or "No content generated")]]
            ws = wb.active
            ws.title = "Output"
            for r_idx, row in enumerate(rows, start=1):
                for c_idx, value in enumerate(row, start=1):
                    ws.cell(row=r_idx, column=c_idx, value=value)
                    if r_idx == 1:
                        ws.cell(row=r_idx, column=c_idx).font = Font(bold=True)
                        ws.cell(row=r_idx, column=c_idx).fill = PatternFill(
                            start_color=header_fill,
                            end_color=header_fill,
                            fill_type="solid",
                        )
        wb.save(out)
        return out

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

