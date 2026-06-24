"""DOCX component library — the python-docx analogue of ``pptx_components.py``.

Each builder takes a ``Document`` (or block) plus a ``DocTheme`` and emits a
themed element: cover page, styled headings, callouts, KPI tables, branded tables,
and the page chrome (TOC + footer). The composer assembles a document from these
primitives so DOCX stays on-brand and on-topic like the deck renderer.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from app.core.tz import IST
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from app.core.doc_theme import DocTheme

logger = logging.getLogger(__name__)


def _set_cell_shading(cell, hex6: str) -> None:
    """Apply a solid fill to a table cell (hex6 = 6-char hex, no '#')."""
    fh = hex6.lstrip("#").upper()
    if len(fh) != 6:
        return
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fh)
    tc_pr.append(shd)


def _set_paragraph_shading(para, hex6: str) -> None:
    fh = hex6.lstrip("#").upper()
    if len(fh) != 6:
        return
    p_pr = para._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fh)
    p_pr.append(shd)


def _add_bottom_border(para, hex6: str, size: int = 12) -> None:
    """Add a coloured bottom rule under a paragraph (accent rule on cover/sections)."""
    fh = hex6.lstrip("#").upper()
    if len(fh) != 6:
        return
    p_pr = para._p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "4")
    bottom.set(qn("w:color"), fh)
    p_bdr.append(bottom)
    p_pr.append(p_bdr)


def apply_theme_styles(doc: Document, theme: DocTheme) -> None:
    """Set Normal + Heading 1–4 styles once so every paragraph inherits the theme."""
    try:
        normal = doc.styles["Normal"]
        normal.font.name = theme.font_body
        normal.font.size = Pt(theme.pt("body"))
        normal.paragraph_format.space_after = Pt(6)
    except Exception as exc:
        logger.debug("Normal style skipped: %s", exc)

    # H1 uses primary; H2/H3/H4 step down via accent_dark for visual hierarchy.
    role_for_level = {1: "primary", 2: "accent_dark", 3: "accent_dark", 4: "ink"}
    for level in (1, 2, 3, 4):
        style_name = f"Heading {level}"
        try:
            style = doc.styles[style_name]
            style.font.name = theme.font_header
            style.font.color.rgb = RGBColor(*theme.rgb(role_for_level[level]))
            style.font.size = Pt(theme.pt(f"h{level}"))
            style.font.bold = level <= 2
        except Exception as exc:
            logger.debug("Style %s skipped: %s", style_name, exc)


def set_page_margins(doc: Document) -> None:
    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1.25)
        section.right_margin = Inches(1.25)


def apply_core_properties(doc: Document, title: str, company: str, author: str) -> None:
    try:
        props = doc.core_properties
        props.title = title[:255]
        props.author = author[:255]
        props.company = company[:255]
        props.modified = datetime.now(IST)
        props.keywords = "processdoc,docx"
    except Exception as exc:
        logger.debug("Core properties skipped: %s", exc)


def cover_page(doc: Document, theme: DocTheme, title: str, company: str) -> None:
    """Branded cover: title in primary, accent rule, company, date, then a page break."""
    for _ in range(4):
        sp = doc.add_paragraph()
        sp.paragraph_format.space_before = Pt(0)
        sp.paragraph_format.space_after = Pt(0)

    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title_para.add_run(title)
    run.font.name = theme.font_header
    run.font.size = Pt(theme.pt("cover_title"))
    run.font.bold = True
    run.font.color.rgb = RGBColor(*theme.rgb("primary"))
    # Accent rule beneath the title (uses the secondary/accent token for contrast).
    _add_bottom_border(title_para, theme.hex6("secondary"), size=18)

    doc.add_paragraph()

    if company:
        co_para = doc.add_paragraph()
        co_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        co_run = co_para.add_run(company)
        co_run.font.name = theme.font_body
        co_run.font.size = Pt(theme.pt("cover_subtitle"))
        co_run.font.color.rgb = RGBColor(*theme.rgb("accent_dark"))

    date_para = doc.add_paragraph()
    date_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    date_run = date_para.add_run(datetime.now(IST).strftime("%B %Y"))
    date_run.font.name = theme.font_body
    date_run.font.size = Pt(theme.pt("h4"))
    date_run.font.color.rgb = RGBColor(*theme.rgb("muted"))

    doc.add_page_break()


def insert_toc(doc: Document) -> None:
    """Insert a Table of Contents field that Word populates on open."""
    para = doc.add_paragraph()
    para.style = "Normal"
    run = para.add_run()

    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    fld_begin.set(qn("w:dirty"), "true")
    run._r.append(fld_begin)

    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = ' TOC \\o "1-3" \\h \\z \\u '
    run._r.append(instr)

    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_end)

    doc.add_paragraph()


def page_footer(doc: Document, theme: DocTheme, company: str) -> None:
    """Insert 'Company | Page X of Y' in the footer of every section."""
    primary_rgb = RGBColor(*theme.rgb("primary"))
    for section in doc.sections:
        footer = section.footer
        para = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        para.clear()
        para.alignment = WD_ALIGN_PARAGRAPH.RIGHT

        if company:
            run = para.add_run(f"{company}  |  ")
            run.font.color.rgb = primary_rgb
            run.font.size = Pt(8)

        run_page = para.add_run("Page ")
        run_page.font.size = Pt(8)
        _append_field(run_page, " PAGE ")

        run_of = para.add_run(" of ")
        run_of.font.size = Pt(8)
        _append_field(run_of, " NUMPAGES ")


def _append_field(run, instr_text: str) -> None:
    fld = OxmlElement("w:fldChar")
    fld.set(qn("w:fldCharType"), "begin")
    run._r.append(fld)
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instr_text
    run._r.append(instr)
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_end)


def parse_inline(text: str) -> list[tuple[str, bool, bool]]:
    """Parse inline **bold** and *italic* markers into (text, bold, italic) tuples."""
    result: list[tuple[str, bool, bool]] = []
    pattern = re.compile(r"(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)")
    last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            result.append((text[last:m.start()], False, False))
        raw = m.group(0)
        if raw.startswith("**"):
            result.append((m.group(2), True, False))
        elif raw.startswith("`"):
            result.append((m.group(4), False, False))
        else:
            result.append((m.group(3), False, True))
        last = m.end()
    if last < len(text):
        result.append((text[last:], False, False))
    return result or [(text, False, False)]


def body_paragraph(doc: Document, theme: DocTheme, text: str,
                   style: str = "Normal", bold: bool = False):
    para = doc.add_paragraph(style=style)
    for fragment, is_bold, is_italic in parse_inline(text):
        run = para.add_run(fragment)
        run.font.name = theme.font_body
        run.bold = bold or is_bold
        run.italic = is_italic
    return para


def callout(doc: Document, theme: DocTheme, text: str):
    """A shaded callout box (accent_light fill, primary left border) for emphasis."""
    para = doc.add_paragraph()
    _set_paragraph_shading(para, theme.hex6("accent_light", "#EBF5D3"))
    _add_left_border(para, theme.hex6("primary"))
    for fragment, is_bold, is_italic in parse_inline(text):
        run = para.add_run(fragment)
        run.font.name = theme.font_body
        run.bold = is_bold
        run.italic = is_italic
    return para


def _add_left_border(para, hex6: str, size: int = 18) -> None:
    fh = hex6.lstrip("#").upper()
    if len(fh) != 6:
        return
    p_pr = para._p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), str(size))
    left.set(qn("w:space"), "8")
    left.set(qn("w:color"), fh)
    p_bdr.append(left)
    p_pr.append(p_bdr)


def styled_table(doc: Document, theme: DocTheme, rows: list[list[str]], header: bool = True):
    """Branded table: primary-filled header row (inverse text), banded body rows."""
    if not rows:
        return None
    cols = max(len(r) for r in rows)
    table = doc.add_table(rows=len(rows), cols=cols)
    table.style = "Table Grid"
    header_hex = theme.hex6("primary")
    band_hex = theme.hex6("tint", "#F2F2F2")
    inverse_rgb = RGBColor(*theme.rgb("inverse", "#FFFFFF"))

    for r_idx, row in enumerate(rows):
        for c_idx in range(cols):
            val = row[c_idx] if c_idx < len(row) else ""
            cell = table.cell(r_idx, c_idx)
            cell.text = str(val or "")
            for p in cell.paragraphs:
                for run in p.runs:
                    run.font.name = theme.font_body
            if header and r_idx == 0:
                _set_cell_shading(cell, header_hex)
                for p in cell.paragraphs:
                    for run in p.runs:
                        run.bold = True
                        run.font.color.rgb = inverse_rgb
            elif r_idx % 2 == (0 if header else 1):
                _set_cell_shading(cell, band_hex)
    doc.add_paragraph()
    return table


def kpi_table(doc: Document, theme: DocTheme, stats: list[dict]):
    """Render KPI stats (list of {value,label}) as a single-row metric strip."""
    stats = [s for s in stats if isinstance(s, dict)][:5]
    if not stats:
        return None
    table = doc.add_table(rows=2, cols=len(stats))
    table.style = "Table Grid"
    for i, stat in enumerate(stats):
        val_cell = table.cell(0, i)
        val_cell.text = str(stat.get("value") or "—")
        _set_cell_shading(val_cell, theme.hex6("tint", "#F2F2F2"))
        for p in val_cell.paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in p.runs:
                run.bold = True
                run.font.size = Pt(theme.pt("h2"))
                run.font.color.rgb = RGBColor(*theme.rgb("primary"))
        lbl_cell = table.cell(1, i)
        lbl_cell.text = str(stat.get("label") or "")
        for p in lbl_cell.paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in p.runs:
                run.font.size = Pt(theme.pt("caption"))
                run.font.color.rgb = RGBColor(*theme.rgb("muted"))
    doc.add_paragraph()
    return table


def code_block(doc: Document, theme: DocTheme, text: str):
    para = doc.add_paragraph()
    run = para.add_run(text)
    run.font.name = "Courier New"
    run.font.size = Pt(9)
    _set_paragraph_shading(para, "F5F5F5")
    return para
