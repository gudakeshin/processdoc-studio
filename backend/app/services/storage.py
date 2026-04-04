import json
import uuid
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from docx import Document
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.enum.chart import XL_CHART_TYPE
from pptx.chart.data import ChartData
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pypdf import PdfWriter

from app.core.config import settings


def workspace_path(project_id: str) -> Path:
    return Path(settings.workspace_root) / project_id


def ensure_workspace(project_id: str) -> Path:
    base = workspace_path(project_id)
    for rel in ["source_docs", "parsed_docs", "runs", "custom_skills", "brand", "dpdp"]:
        (base / rel).mkdir(parents=True, exist_ok=True)
    context = base / "CONTEXT.md"
    if not context.exists():
        context.write_text("# Project Context\n")
    return base


def create_run(project_id: str, output_types: list[str]) -> dict:
    ensure_workspace(project_id)
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    run_dir = workspace_path(project_id) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "project_id": project_id,
        "status": "plan_ready",
        "output_types": output_types,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def save_run_artifacts(project_id: str, run_id: str, payload: dict) -> None:
    run_dir = workspace_path(project_id) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Spec-aligned artifact filenames.
    string_file_map: dict[str, str] = {
        "drawio_xml": "drawio.xml",
        "process_map_mermaid": "process_map.mmd",
        "raci_html": "raci.html",
        "raci_markdown": "raci.md",
        "sop_markdown": "sop.md",
        "narrative_md": "narrative.md",
        "assembled_context": "assembled_context.txt",
    }
    json_file_map: dict[str, str] = {
        "dpdp_report_json": "dpdp_report.json",
        "qa_report": "qa_report.json",
        "guardrail_report": "guardrail_report.json",
        "compaction_snapshot": "compaction_snapshot.json",
        "memory_summary": "memory_summary.json",
        "process_model": "process_model.json",
    }
    requested_outputs = payload.get("requested_outputs")
    requested_set = {
        str(x).strip().lower()
        for x in (requested_outputs if isinstance(requested_outputs, list) else [])
        if str(x).strip()
    }

    for key, value in payload.items():
        if key in json_file_map and isinstance(value, dict):
            (run_dir / json_file_map[key]).write_text(json.dumps(value, indent=2), encoding="utf-8")
            continue

        if key in string_file_map and isinstance(value, str):
            (run_dir / string_file_map[key]).write_text(value, encoding="utf-8")
            continue

        # Backwards-compatible fallbacks for any other string/json keys.
        if key.endswith("_json") and isinstance(value, dict):
            (run_dir / f"{key}.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
        elif isinstance(value, str):
            suffix = ".md" if key.endswith("_md") else ".txt"
            (run_dir / f"{key}{suffix}").write_text(value, encoding="utf-8")

    def _rows_from_markdown(md: str) -> list[list[str]]:
        rows: list[list[str]] = []
        for line in (md or "").splitlines():
            text = line.strip()
            if not text.startswith("|") or "|" not in text[1:]:
                continue
            cols = [c.strip() for c in text.strip("|").split("|")]
            if not cols:
                continue
            if all(re.fullmatch(r"-{2,}:?", c.replace(" ", "")) for c in cols):
                continue
            rows.append(cols)
        return rows

    def _rows_from_html(html_text: str) -> list[list[str]]:
        rows: list[list[str]] = []
        tr_blocks = re.findall(r"<tr[^>]*>(.*?)</tr>", html_text or "", flags=re.I | re.S)
        for block in tr_blocks:
            cols = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", block, flags=re.I | re.S)
            cleaned = [re.sub(r"<[^>]+>", "", c).strip() for c in cols]
            if cleaned:
                rows.append(cleaned)
        return rows

    def _rows_from_process_model(pm: dict[str, Any]) -> list[list[str]]:
        steps = pm.get("steps") if isinstance(pm, dict) else []
        if not isinstance(steps, list):
            return []
        rows: list[list[str]] = [["Activity", "Responsible", "Accountable", "Consulted", "Informed"]]
        roles = [str(r).strip() for r in (pm.get("roles") or []) if str(r).strip()] if isinstance(pm, dict) else []
        accountable = roles[0] if roles else "Process Owner"
        for st in steps[:120]:
            if not isinstance(st, dict):
                continue
            activity = str(st.get("name") or "—").strip()
            responsible = str(st.get("role") or "—").strip()
            consulted = ", ".join([r for r in roles if r not in {responsible, accountable}][:4]) if roles else "—"
            rows.append([activity, responsible, accountable, consulted or "—", "—"])
        return rows

    def _write_raci_xlsx(rows: list[list[str]]) -> Path | None:
        if not rows:
            return None
        wb = Workbook()
        ws = wb.active
        ws.title = "RACI"
        for r_idx, row in enumerate(rows, start=1):
            for c_idx, value in enumerate(row, start=1):
                ws.cell(row=r_idx, column=c_idx, value=value)
                if r_idx == 1:
                    ws.cell(row=r_idx, column=c_idx).font = Font(bold=True)
                    ws.cell(row=r_idx, column=c_idx).fill = PatternFill(
                        start_color="D9E1F2", end_color="D9E1F2", fill_type="solid"
                    )
        for col in ("A", "B", "C", "D", "E", "F", "G"):
            ws.column_dimensions[col].width = 28
        out = run_dir / "raci.xlsx"
        wb.save(out)
        return out

    def _safe_text(value: object, default: str = "") -> str:
        return str(value or default).strip()

    def _parse_markdown_blocks(md_text: str) -> list[dict[str, Any]]:
        lines = (md_text or "").splitlines()
        blocks: list[dict[str, Any]] = []
        i = 0
        while i < len(lines):
            raw = lines[i]
            line = raw.rstrip()
            stripped = line.strip()
            if not stripped:
                i += 1
                continue
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if heading_match:
                blocks.append(
                    {
                        "type": "heading",
                        "level": len(heading_match.group(1)),
                        "text": heading_match.group(2).strip(),
                    }
                )
                i += 1
                continue
            if stripped.startswith("|") and "|" in stripped[1:]:
                table_lines: list[str] = []
                while i < len(lines):
                    cur = lines[i].strip()
                    if not cur.startswith("|") or "|" not in cur[1:]:
                        break
                    table_lines.append(cur)
                    i += 1
                rows = _rows_from_markdown("\n".join(table_lines))
                if rows:
                    blocks.append({"type": "table", "rows": rows})
                continue
            if re.match(r"^[-*]\s+.+$", stripped):
                bullets: list[str] = []
                while i < len(lines):
                    cur = lines[i].strip()
                    m = re.match(r"^[-*]\s+(.+)$", cur)
                    if not m:
                        break
                    bullets.append(m.group(1).strip())
                    i += 1
                if bullets:
                    blocks.append({"type": "bullets", "items": bullets})
                continue
            if re.match(r"^\d+\.\s+.+$", stripped):
                numbered: list[str] = []
                while i < len(lines):
                    cur = lines[i].strip()
                    m = re.match(r"^\d+\.\s+(.+)$", cur)
                    if not m:
                        break
                    numbered.append(m.group(1).strip())
                    i += 1
                if numbered:
                    blocks.append({"type": "numbered", "items": numbered})
                continue
            paragraph_lines = [stripped]
            i += 1
            while i < len(lines):
                nxt = lines[i].strip()
                if (
                    not nxt
                    or re.match(r"^(#{1,6})\s+.+$", nxt)
                    or nxt.startswith("|")
                    or re.match(r"^[-*]\s+.+$", nxt)
                    or re.match(r"^\d+\.\s+.+$", nxt)
                ):
                    break
                paragraph_lines.append(nxt)
                i += 1
            blocks.append({"type": "paragraph", "text": " ".join(paragraph_lines).strip()})
        return blocks

    def _write_xlsx_output() -> Path | None:
        wb = Workbook()
        typed_cells = payload.get("xlsx_cells")
        if isinstance(typed_cells, list) and typed_cells:
            by_sheet: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for item in typed_cells:
                if not isinstance(item, dict):
                    continue
                by_sheet[_safe_text(item.get("sheet"), "Output")].append(item)
            first = True
            for sheet_name, cells in by_sheet.items():
                ws = wb.active if first else wb.create_sheet(title=sheet_name[:31] or "Output")
                ws.title = sheet_name[:31] or "Output"
                first = False
                max_col = 1
                max_width: dict[int, int] = defaultdict(lambda: 10)
                for cell_data in cells:
                    row = int(cell_data.get("row") or 1)
                    col = int(cell_data.get("col") or 1)
                    max_col = max(max_col, col)
                    cell = ws.cell(row=max(1, row), column=max(1, col))
                    formula = cell_data.get("formula")
                    if isinstance(formula, str) and formula.strip():
                        text = formula.strip()
                        cell.value = text if text.startswith("=") else f"={text}"
                    else:
                        cell.value = cell_data.get("value")
                    if isinstance(cell_data.get("number_format"), str):
                        cell.number_format = str(cell_data["number_format"])
                    if bool(cell_data.get("bold")):
                        cell.font = Font(bold=True)
                    if isinstance(cell_data.get("fill_color"), str) and cell_data.get("fill_color"):
                        color = str(cell_data["fill_color"]).replace("#", "").upper()
                        if len(color) == 6:
                            cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
                    max_width[col] = max(max_width[col], len(_safe_text(cell.value, "")) + 2)
                for idx in range(1, max_col + 1):
                    col_letter = ws.cell(row=1, column=idx).column_letter
                    ws.column_dimensions[col_letter].width = min(48, max(10, max_width.get(idx, 10)))
        else:
            rows: list[list[str]] = []
            if isinstance(payload.get("xlsx_markdown"), str) and payload.get("xlsx_markdown"):
                rows = _rows_from_markdown(str(payload.get("xlsx_markdown") or ""))
            if not rows and isinstance(payload.get("raci_markdown"), str) and payload.get("raci_markdown"):
                rows = _rows_from_markdown(str(payload.get("raci_markdown") or ""))
            if not rows and isinstance(payload.get("process_model"), dict):
                rows = _rows_from_process_model(payload.get("process_model") or {})
            if not rows:
                rows = [["Section", "Content"], ["Summary", _safe_text(payload.get("narrative_md"), "No content generated")]]
            ws = wb.active
            ws.title = "Output"
            for r_idx, row in enumerate(rows, start=1):
                for c_idx, value in enumerate(row, start=1):
                    ws.cell(row=r_idx, column=c_idx, value=value)
                    if r_idx == 1:
                        ws.cell(row=r_idx, column=c_idx).font = Font(bold=True)
                        ws.cell(row=r_idx, column=c_idx).fill = PatternFill(
                            start_color="D9E1F2", end_color="D9E1F2", fill_type="solid"
                        )
        out = run_dir / "output.xlsx"
        wb.save(out)
        return out

    def _write_pdf_output() -> Path:
        out = run_dir / "output.pdf"
        summary = _safe_text(payload.get("pdf_markdown") or payload.get("narrative_md"), "Generated ProcessDoc PDF output")
        title = _safe_text(
            (payload.get("process_model") or {}).get("process_name")
            if isinstance(payload.get("process_model"), dict)
            else "Process Output",
            "Process Output",
        )
        try:
            from reportlab.lib.pagesizes import LETTER
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem

            doc = SimpleDocTemplate(str(out), pagesize=LETTER, title=title)
            styles = getSampleStyleSheet()
            story: list[Any] = [Paragraph(title, styles["Title"]), Spacer(1, 10)]
            for block in _parse_markdown_blocks(summary):
                if block["type"] == "heading":
                    style_name = f"Heading{min(3, max(1, int(block.get('level', 1))))}"
                    story.append(Paragraph(_safe_text(block.get("text"), ""), styles[style_name]))
                    story.append(Spacer(1, 6))
                elif block["type"] == "paragraph":
                    story.append(Paragraph(_safe_text(block.get("text"), ""), styles["BodyText"]))
                    story.append(Spacer(1, 6))
                elif block["type"] in {"bullets", "numbered"}:
                    items = [_safe_text(v, "") for v in block.get("items", []) if _safe_text(v, "")]
                    if items:
                        flow = ListFlowable(
                            [ListItem(Paragraph(item, styles["BodyText"])) for item in items],
                            bulletType="bullet" if block["type"] == "bullets" else "1",
                        )
                        story.append(flow)
                        story.append(Spacer(1, 6))
            doc.build(story)
            return out
        except Exception:
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            writer.add_metadata({"/Title": title, "/Subject": summary[:500]})
            with out.open("wb") as f:
                writer.write(f)
            return out

    def _write_docx_output() -> Path:
        out = run_dir / "output.docx"
        text = _safe_text(payload.get("docx_markdown") or payload.get("narrative_md"), "Process document")
        doc = Document()
        title = _safe_text((payload.get("process_model") or {}).get("process_name") if isinstance(payload.get("process_model"), dict) else "Process Output", "Process Output")
        doc.add_heading(title, level=1)
        for block in _parse_markdown_blocks(text):
            if block["type"] == "heading":
                doc.add_heading(_safe_text(block.get("text"), ""), level=min(4, max(1, int(block.get("level", 1)))))
            elif block["type"] == "paragraph":
                doc.add_paragraph(_safe_text(block.get("text"), ""))
            elif block["type"] == "bullets":
                for item in block.get("items", []):
                    doc.add_paragraph(_safe_text(item, ""), style="List Bullet")
            elif block["type"] == "numbered":
                for item in block.get("items", []):
                    doc.add_paragraph(_safe_text(item, ""), style="List Number")
            elif block["type"] == "table":
                rows = block.get("rows") or []
                if not rows:
                    continue
                cols = max(len(r) for r in rows)
                table = doc.add_table(rows=len(rows), cols=cols)
                table.style = "Table Grid"
                for r_idx, row in enumerate(rows):
                    for c_idx in range(cols):
                        val = row[c_idx] if c_idx < len(row) else ""
                        table.cell(r_idx, c_idx).text = _safe_text(val, "")
                if rows:
                    for cell in table.rows[0].cells:
                        for run in cell.paragraphs[0].runs:
                            run.bold = True
        doc.save(out)
        return out

    def _write_pptx_output() -> Path:  # noqa: C901
        out = run_dir / "output.pptx"

        # ── Brand design tokens ────────────────────────────────────────────
        _B: dict[str, RGBColor] = {
            "green":       RGBColor(0x86, 0xBC, 0x25),
            "dark":        RGBColor(0x1A, 0x1A, 0x1A),
            "mid_dark":    RGBColor(0x2D, 0x2D, 0x2D),
            "mid":         RGBColor(0x3D, 0x3D, 0x3D),
            "dark_green":  RGBColor(0x5A, 0x8A, 0x00),
            "gray":        RGBColor(0x75, 0x78, 0x7B),
            "light_gray":  RGBColor(0xAA, 0xAA, 0xAA),
            "white":       RGBColor(0xFF, 0xFF, 0xFF),
            "light_green": RGBColor(0xEB, 0xF5, 0xD3),
            "e8":          RGBColor(0xE8, 0xE8, 0xE8),
        }
        _FONT = "Calibri"

        # Legacy layout → slide_type mapping for backward compatibility
        _LAYOUT_COMPAT: dict[str, str] = {
            "title_content":    "bullets",
            "title_and_content":"bullets",
            "title_only":       "bullets",
            "two_content":      "column_cards",
            "blank":            "bullets",
        }

        def _rgb(token: str) -> RGBColor:
            return _B.get(str(token).lower(), _B["mid"])

        def _add_rect(slide: Any, x: float, y: float, w: float, h: float, color_token: str) -> Any:
            from pptx.util import Inches as _In
            shape = slide.shapes.add_shape(1, _In(x), _In(y), _In(w), _In(h))  # MSO_SHAPE_TYPE.RECTANGLE=1
            fill = shape.fill
            fill.solid()
            fill.fore_color.rgb = _rgb(color_token)
            shape.line.fill.background()
            return shape

        def _add_text(
            slide: Any, x: float, y: float, w: float, h: float,
            text: str, size: float, color_token: str,
            bold: bool = False, align: str = "left",
        ) -> Any:
            from pptx.util import Inches as _In
            txb = slide.shapes.add_textbox(_In(x), _In(y), _In(w), _In(h))
            tf = txb.text_frame
            tf.word_wrap = True
            tf.auto_size = None
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER if align == "center" else (PP_ALIGN.RIGHT if align == "right" else PP_ALIGN.LEFT)
            run = p.add_run()
            run.text = _safe_text(text, "")
            run.font.name = _FONT
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.color.rgb = _rgb(color_token)
            return txb

        def _add_chrome(slide: Any, title: str, page_num: int, total: int) -> None:
            _add_rect(slide, 0.0, 0.0, 10.0, 0.07, "green")
            _add_rect(slide, 0.0, 0.07, 0.06, 5.55, "dark")
            _add_text(slide, 0.28, 0.18, 8.50, 0.60, title, 22, "dark", bold=True)
            _add_text(slide, 8.80, 5.30, 1.00, 0.25, f"{page_num} / {total}", 9, "light_gray")
            _add_text(slide, 0.18, 5.30, 1.50, 0.25, "Deloitte.", 10, "gray", bold=True)

        def _blank_slide(prs: Any) -> Any:
            # Use the blank layout (index 6 if available, else last layout)
            layouts = prs.slide_layouts
            blank = layouts[6] if len(layouts) > 6 else layouts[-1]
            return prs.slides.add_slide(blank)

        def _render_footer_note(slide: Any, note: str) -> None:
            _add_rect(slide, 0.28, 5.22, 9.44, 0.26, "light_green")
            _add_text(slide, 0.38, 5.22, 9.24, 0.26, note, 9, "mid")

        # ── Slide renderers ────────────────────────────────────────────────

        def _render_title_slide(prs: Any, item: dict[str, Any]) -> None:
            slide = _blank_slide(prs)
            _add_rect(slide, 0.0,  0.0,   0.35, 5.625, "green")
            _add_rect(slide, 0.0,  5.35, 10.0,  0.28,  "green")
            _add_text(slide, 0.60, 0.40,  3.00, 0.50, "Deloitte.", 20, "white", bold=True)
            title_text = _safe_text(item.get("title"), "Process Overview")
            _add_text(slide, 0.60, 1.15, 8.80, 1.05, title_text, 44, "white", bold=True)
            _add_rect(slide, 0.60, 2.28, 5.50, 0.06, "green")
            subtitle = _safe_text(item.get("subtitle"), "Executive Presentation")
            _add_text(slide, 0.60, 2.48, 8.80, 0.55, subtitle, 18, "light_gray")
            badges = item.get("badges") if isinstance(item.get("badges"), list) else []
            xs = [0.60, 3.80]
            y_start = 3.22
            for i, badge in enumerate(badges[:4]):
                col = i % 2
                row = i // 2
                bx = xs[col]
                by = y_start + row * 0.54
                _add_rect(slide, bx, by, 3.00, 0.38, "mid_dark")
                _add_text(slide, bx, by, 3.00, 0.38, _safe_text(badge), 11, "green")
            version_line = _safe_text(item.get("footer_note"), "")
            if version_line:
                _add_text(slide, 0.60, 4.80, 6.00, 0.30, version_line, 9, "gray")

        def _render_bullets_slide(prs: Any, item: dict[str, Any], page_num: int, total: int) -> None:
            slide = _blank_slide(prs)
            _add_chrome(slide, _safe_text(item.get("title"), ""), page_num, total)
            bullets = item.get("bullets") if isinstance(item.get("bullets"), list) else []
            if bullets:
                n = len(bullets)
                # Content-driven sizing: fewer bullets → larger font + more breathing room
                if n <= 3:
                    font_size, space_after, top = 16, Pt(14), 1.05
                elif n <= 5:
                    font_size, space_after, top = 14, Pt(10), 0.95
                elif n <= 8:
                    font_size, space_after, top = 12, Pt(6),  0.92
                else:
                    font_size, space_after, top = 10, Pt(3),  0.92
                txb = slide.shapes.add_textbox(Inches(0.28), Inches(top), Inches(9.44), Inches(5.10 - top))
                tf = txb.text_frame
                tf.word_wrap = True
                for b_idx, bullet in enumerate(bullets[:12]):
                    p = tf.paragraphs[0] if b_idx == 0 else tf.add_paragraph()
                    p.alignment = PP_ALIGN.LEFT
                    run = p.add_run()
                    run.text = _safe_text(bullet)
                    run.font.name = _FONT
                    run.font.size = Pt(font_size)
                    run.font.color.rgb = _B["mid"]
                    p.space_after = space_after
            note = item.get("footer_note")
            if note:
                _render_footer_note(slide, _safe_text(note))

        def _render_stat_cards_slide(prs: Any, item: dict[str, Any], page_num: int, total: int) -> None:
            """3-column full-width grid: each card spans 1/3 of the slide.
            Stat (large, bold), label (medium), description (small body) fill the card.
            Layout is driven entirely by what the AI provides in each card dict."""
            slide = _blank_slide(prs)
            _add_chrome(slide, _safe_text(item.get("title"), ""), page_num, total)
            cards = item.get("stat_cards") if isinstance(item.get("stat_cards"), list) else []
            _DEFAULT_FILLS = ["dark", "mid_dark", "gray"]
            card_w = 3.02
            card_h = 3.55
            card_y = 0.88
            gap = 0.16
            xs = [0.28, 0.28 + card_w + gap, 0.28 + 2 * (card_w + gap)]
            for i in range(3):
                card = cards[i] if i < len(cards) and isinstance(cards[i], dict) else {}
                fill_token = str(card.get("fill") or _DEFAULT_FILLS[i % len(_DEFAULT_FILLS)])
                cx = xs[i]
                # Full colored card background
                _add_rect(slide, cx, card_y, card_w, card_h, fill_token)
                # Thin green top accent bar on each card
                _add_rect(slide, cx, card_y, card_w, 0.06, "green")
                # Large stat number — centred, upper portion of card
                stat_text = _safe_text(card.get("stat"), "—")
                _add_text(slide, cx + 0.10, card_y + 0.20, card_w - 0.20, 0.90,
                          stat_text, 38, "white", bold=True, align="center")
                # Label — medium weight, just below stat
                label_text = _safe_text(card.get("label"), "")
                _add_text(slide, cx + 0.12, card_y + 1.14, card_w - 0.24, 0.44,
                          label_text, 11, "light_gray", bold=True, align="center")
                # Description — AI-provided context sentence fills the lower half
                desc_text = _safe_text(card.get("description"), "")
                if desc_text:
                    _add_text(slide, cx + 0.14, card_y + 1.65, card_w - 0.28, card_h - 1.80,
                              desc_text, 9, "light_gray", align="center")
            note = item.get("footer_note")
            if note:
                _render_footer_note(slide, _safe_text(note))

        def _render_column_cards_slide(prs: Any, item: dict[str, Any], page_num: int, total: int) -> None:
            slide = _blank_slide(prs)
            _add_chrome(slide, _safe_text(item.get("title"), ""), page_num, total)
            cards = item.get("column_cards") if isinstance(item.get("column_cards"), list) else []
            _ACCENT_DEFAULTS = ["green", "dark", "gray"]
            card_w = 3.02
            card_h = 3.45
            card_y = 0.88
            gap = 0.16
            xs = [0.28, 0.28 + card_w + gap, 0.28 + 2 * (card_w + gap)]
            for i in range(3):
                card = cards[i] if i < len(cards) and isinstance(cards[i], dict) else {}
                accent = str(card.get("accent") or _ACCENT_DEFAULTS[i])
                cx = xs[i]
                _add_rect(slide, cx, card_y, card_w, card_h, "white")
                _add_rect(slide, cx, card_y, card_w, 0.06, accent)
                heading = _safe_text(card.get("heading"), f"Pillar {i + 1}")
                _add_text(slide, cx + 0.18, card_y + 0.15, card_w - 0.36, 0.42, heading, 13, accent, bold=True)
                body = _safe_text(card.get("body"), "")
                _add_text(slide, cx + 0.18, card_y + 0.67, card_w - 0.36, card_h - 0.85, body, 11, "mid")
            note = item.get("footer_note")
            if note:
                _render_footer_note(slide, _safe_text(note))

        def _render_stack_layers_slide(prs: Any, item: dict[str, Any], page_num: int, total: int) -> None:
            slide = _blank_slide(prs)
            _add_chrome(slide, _safe_text(item.get("title"), ""), page_num, total)
            layers = item.get("stack_layers") if isinstance(item.get("stack_layers"), list) else []
            _FILL_CYCLE = ["dark", "mid_dark", "dark_green", "gray", "mid", "green"]
            y = 0.90
            row_h = 0.60
            gap = 0.05
            for i, layer in enumerate(layers[:7]):
                if not isinstance(layer, dict):
                    continue
                fill_token = str(layer.get("fill") or _FILL_CYCLE[i % len(_FILL_CYCLE)])
                _add_rect(slide, 0.28, y, 1.55, row_h, fill_token)
                label = _safe_text(layer.get("label"), f"Layer {i + 1}")
                _add_text(slide, 0.28, y, 1.55, row_h, label, 11, "white", bold=True, align="center")
                _add_rect(slide, 1.86, y + 0.04, 7.86, row_h - 0.08, "white")
                desc = _safe_text(layer.get("description"), "")
                _add_text(slide, 1.96, y + 0.04, 7.66, row_h - 0.08, desc, 10, "mid")
                y += row_h + gap
            note = item.get("footer_note")
            if note:
                _render_footer_note(slide, _safe_text(note))

        def _render_table_slide(prs: Any, item: dict[str, Any], page_num: int, total: int) -> None:
            slide = _blank_slide(prs)
            _add_chrome(slide, _safe_text(item.get("title"), ""), page_num, total)
            table_spec = item.get("table") if isinstance(item.get("table"), dict) else {}
            headers = table_spec.get("headers") if isinstance(table_spec.get("headers"), list) else []
            rows = table_spec.get("rows") if isinstance(table_spec.get("rows"), list) else []
            data_rows = [r for r in rows if isinstance(r, list)]
            all_rows = ([headers] + data_rows) if headers else data_rows
            if not all_rows:
                note = item.get("footer_note")
                if note:
                    _render_footer_note(slide, _safe_text(note))
                return
            n_rows = len(all_rows)
            n_cols = max((len(r) for r in all_rows), default=1)
            x = float(table_spec.get("x") or 0.28)
            y = float(table_spec.get("y") or 1.00)
            w = float(table_spec.get("w") or 9.44)
            h = float(table_spec.get("h") or 4.30)
            shape = slide.shapes.add_table(n_rows, n_cols, Inches(x), Inches(y), Inches(w), Inches(h))
            tbl = shape.table
            for r_idx, row in enumerate(all_rows):
                for c_idx in range(n_cols):
                    value = row[c_idx] if c_idx < len(row) else ""
                    cell = tbl.cell(r_idx, c_idx)
                    cell.text = _safe_text(value, "")
                    # Style header row
                    if r_idx == 0 and headers:
                        from pptx.oxml.ns import qn as _qn
                        tc = cell._tc
                        tcPr = tc.get_or_add_tcPr()
                        solidFill = tcPr.get_or_add_solidFill() if hasattr(tcPr, "get_or_add_solidFill") else None
                        try:
                            from lxml import etree
                            ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
                            solidFill = etree.SubElement(tcPr, f"{{{ns}}}solidFill")
                            srgb = etree.SubElement(solidFill, f"{{{ns}}}srgbClr")
                            srgb.set("val", "1A1A1A")
                        except Exception:
                            pass
                        for para in cell.text_frame.paragraphs:
                            for run in para.runs:
                                run.font.bold = True
                                run.font.size = Pt(11)
                                run.font.color.rgb = _B["white"]
                    else:
                        for para in cell.text_frame.paragraphs:
                            for run in para.runs:
                                run.font.size = Pt(10)
                                run.font.color.rgb = _B["mid"]
                        # Alternating row fill
                        if r_idx % 2 == 0:
                            try:
                                from lxml import etree
                                tc = cell._tc
                                tcPr = tc.get_or_add_tcPr()
                                ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
                                solidFill = etree.SubElement(tcPr, f"{{{ns}}}solidFill")
                                srgb = etree.SubElement(solidFill, f"{{{ns}}}srgbClr")
                                srgb.set("val", "E8E8E8")
                            except Exception:
                                pass
            note = item.get("footer_note")
            if note:
                _render_footer_note(slide, _safe_text(note))

        def _render_chart_slide(prs: Any, item: dict[str, Any], page_num: int, total: int) -> None:
            slide = _blank_slide(prs)
            _add_chrome(slide, _safe_text(item.get("title"), ""), page_num, total)
            chart_spec = item.get("chart") if isinstance(item.get("chart"), dict) else {}
            categories = chart_spec.get("categories") if isinstance(chart_spec.get("categories"), list) else []
            series_list = chart_spec.get("series") if isinstance(chart_spec.get("series"), list) else []
            if categories and series_list:
                data = ChartData()
                data.categories = [str(c) for c in categories]
                for s in series_list:
                    if not isinstance(s, dict):
                        continue
                    name = _safe_text(s.get("name"), "Series")
                    values = s.get("values") if isinstance(s.get("values"), list) else []
                    numeric = []
                    for v in values:
                        try:
                            numeric.append(float(v))
                        except Exception:
                            numeric.append(0.0)
                    if numeric:
                        data.add_series(name, numeric)
                if data._series:
                    chart_type_map = {
                        "bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
                        "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
                        "line": XL_CHART_TYPE.LINE_MARKERS,
                        "pie": XL_CHART_TYPE.PIE,
                    }
                    ct = chart_type_map.get(
                        _safe_text(chart_spec.get("type"), "bar").lower(),
                        XL_CHART_TYPE.COLUMN_CLUSTERED,
                    )
                    slide.shapes.add_chart(ct, Inches(0.28), Inches(0.90), Inches(9.44), Inches(4.10), data)
            note = item.get("footer_note")
            if note:
                _render_footer_note(slide, _safe_text(note))

        def _render_section_divider_slide(prs: Any, item: dict[str, Any], page_num: int, total: int) -> None:
            slide = _blank_slide(prs)
            _add_rect(slide, 0.0, 0.0, 10.0, 5.625, "dark")
            _add_rect(slide, 0.0, 0.0, 10.0, 0.07, "green")
            title_text = _safe_text(item.get("title"), "")
            _add_text(slide, 0.60, 2.10, 8.80, 1.05, title_text, 34, "white", bold=True)
            subtitle = _safe_text(item.get("subtitle"), "")
            if subtitle:
                _add_text(slide, 0.60, 3.25, 8.80, 0.55, subtitle, 16, "light_gray")
            _add_text(slide, 0.18, 5.30, 1.50, 0.25, "Deloitte.", 10, "gray", bold=True)
            _add_text(slide, 8.80, 5.30, 1.00, 0.25, f"{page_num} / {total}", 9, "light_gray")

        # ── Dispatch ───────────────────────────────────────────────────────
        _RENDERERS = {
            "title":            _render_title_slide,
            "bullets":          _render_bullets_slide,
            "stat_cards":       _render_stat_cards_slide,
            "column_cards":     _render_column_cards_slide,
            "stack_layers":     _render_stack_layers_slide,
            "table":            _render_table_slide,
            "chart":            _render_chart_slide,
            "section_divider":  _render_section_divider_slide,
        }

        prs = Presentation()
        prs.slide_width = Inches(10.0)
        prs.slide_height = Inches(5.625)

        slides = payload.get("pptx_slides")
        if not (isinstance(slides, list) and slides):
            # Minimal fallback
            slides = [
                {"title": "Process Output", "slide_type": "title", "subtitle": "Generated by ProcessDoc Studio"},
                {"title": "Summary", "slide_type": "bullets", "bullets": [
                    _safe_text(payload.get("narrative_md"), "No content generated")[:120],
                ]},
            ]

        total = min(len(slides), 20)
        for page_num, item in enumerate(slides[:20], start=1):
            if not isinstance(item, dict):
                continue
            # Resolve slide_type — support legacy "layout" field for backward compat
            slide_type = str(item.get("slide_type") or "").strip()
            if not slide_type:
                legacy = str(item.get("layout") or "").strip().lower().replace("-", "_")
                slide_type = _LAYOUT_COMPAT.get(legacy, "bullets")
                # If legacy slide carries explicit table/chart data, honour it
                if slide_type == "bullets" and item.get("table"):
                    slide_type = "table"
                elif slide_type == "bullets" and item.get("chart"):
                    slide_type = "chart"
            renderer = _RENDERERS.get(slide_type, _render_bullets_slide)
            if slide_type == "title":
                renderer(prs, item)
            else:
                renderer(prs, item, page_num, total)

        prs.save(out)
        return out

    raci_rows: list[list[str]] = []
    if isinstance(payload.get("raci_markdown"), str) and payload.get("raci_markdown"):
        raci_rows = _rows_from_markdown(str(payload.get("raci_markdown") or ""))
    elif isinstance(payload.get("raci_html"), str) and payload.get("raci_html"):
        raci_rows = _rows_from_html(str(payload.get("raci_html") or ""))
    if not raci_rows and isinstance(payload.get("process_model"), dict):
        raci_rows = _rows_from_process_model(payload.get("process_model") or {})
    if "raci" in requested_set:
        _write_raci_xlsx(raci_rows)
    if "xlsx" in requested_set:
        _write_xlsx_output()
    if "pdf" in requested_set:
        _write_pdf_output()
    if "docx" in requested_set:
        _write_docx_output()
    if "pptx" in requested_set:
        _write_pptx_output()
        # Persist slide JSON for targeted Visual QA remediation (merge on retry).
        ps = payload.get("pptx_slides")
        if isinstance(ps, list) and ps:
            (run_dir / "pptx_slides.json").write_text(
                json.dumps(ps, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    typed_artifacts: list[dict[str, str]] = []
    if isinstance(payload.get("narrative_md"), str) and payload.get("narrative_md"):
        typed_artifacts.append({"output_type": "narrative", "representation": "markdown", "content_type": "text/markdown", "body": payload["narrative_md"]})
    if isinstance(payload.get("sop_markdown"), str) and payload.get("sop_markdown"):
        typed_artifacts.append({"output_type": "sop", "representation": "markdown", "content_type": "text/markdown", "body": payload["sop_markdown"]})
    if isinstance(payload.get("raci_html"), str) and payload.get("raci_html"):
        typed_artifacts.append({"output_type": "raci", "representation": "html", "content_type": "text/html", "body": payload["raci_html"]})
    if isinstance(payload.get("raci_markdown"), str) and payload.get("raci_markdown"):
        typed_artifacts.append({"output_type": "raci", "representation": "markdown", "content_type": "text/markdown", "body": payload["raci_markdown"]})
    if (run_dir / "raci.xlsx").exists():
        typed_artifacts.append({"output_type": "raci", "representation": "xlsx", "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "body": "binary_file:raci.xlsx"})
    if (run_dir / "output.xlsx").exists():
        typed_artifacts.append({"output_type": "xlsx", "representation": "xlsx", "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "body": "binary_file:output.xlsx"})
    if isinstance(payload.get("drawio_xml"), str) and payload.get("drawio_xml"):
        typed_artifacts.append({"output_type": "process_map", "representation": "drawio_xml", "content_type": "application/xml", "body": payload["drawio_xml"]})
    if isinstance(payload.get("process_map_mermaid"), str) and payload.get("process_map_mermaid"):
        typed_artifacts.append({"output_type": "process_map", "representation": "mermaid", "content_type": "text/plain", "body": payload["process_map_mermaid"]})
    if (run_dir / "output.pdf").exists():
        typed_artifacts.append({"output_type": "pdf", "representation": "pdf", "content_type": "application/pdf", "body": "binary_file:output.pdf"})
    if (run_dir / "output.docx").exists():
        typed_artifacts.append({"output_type": "docx", "representation": "docx", "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "body": "binary_file:output.docx"})
    if (run_dir / "output.pptx").exists():
        typed_artifacts.append({"output_type": "pptx", "representation": "pptx", "content_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "body": "binary_file:output.pptx"})
    (run_dir / "artifacts_typed.json").write_text(json.dumps(typed_artifacts, indent=2), encoding="utf-8")
