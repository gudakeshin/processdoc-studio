from __future__ import annotations

import logging
import re
from datetime import datetime
from app.core.tz import IST
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from app.core.deliverable import DeliverableMetadata, IDeliverable
from app.core.deliverable_utils import parse_markdown_blocks, safe_text

logger = logging.getLogger(__name__)


def _rgb_tuple(value: str | None) -> tuple[int, int, int]:
    raw = str(value or "").strip().lstrip("#")
    if len(raw) != 6:
        return (0x1A, 0x1A, 0x1A)
    try:
        return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    except ValueError:
        return (0x1A, 0x1A, 0x1A)


def _apply_heading_styles(doc: Document, font_family: str, primary_rgb: tuple[int, int, int]) -> None:
    """Set Heading 1–4 styles once at the document level so every heading inherits them."""
    for level in (1, 2, 3, 4):
        style_name = f"Heading {level}"
        try:
            style = doc.styles[style_name]
            style.font.name = font_family
            style.font.color.rgb = RGBColor(*primary_rgb)
            style.font.size = Pt({1: 18, 2: 15, 3: 13, 4: 11}[level])
            style.font.bold = level <= 2
        except Exception as exc:
            logger.debug("Style %s skipped: %s", style_name, exc)


def _apply_normal_style(doc: Document, font_family: str) -> None:
    try:
        style = doc.styles["Normal"]
        style.font.name = font_family
        style.font.size = Pt(10)
        style.paragraph_format.space_after = Pt(6)
    except Exception as exc:
        logger.debug("Normal style skipped: %s", exc)


def _set_page_margins(doc: Document) -> None:
    for section in doc.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1.25)
        section.right_margin = Inches(1.25)


def _add_page_number_footer(doc: Document, company: str, primary_rgb: tuple[int, int, int]) -> None:
    """Insert 'Company | Page X of Y' in the footer of every section."""
    for section in doc.sections:
        footer = section.footer
        para = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        para.clear()
        para.alignment = WD_ALIGN_PARAGRAPH.RIGHT

        if company:
            run = para.add_run(f"{company}  |  ")
            run.font.color.rgb = RGBColor(*primary_rgb)
            run.font.size = Pt(8)

        # "Page " literal
        run_page = para.add_run("Page ")
        run_page.font.size = Pt(8)

        # PAGE field
        fld = OxmlElement("w:fldChar")
        fld.set(qn("w:fldCharType"), "begin")
        run_page._r.append(fld)

        instrText = OxmlElement("w:instrText")
        instrText.set(qn("xml:space"), "preserve")
        instrText.text = " PAGE "
        run_page._r.append(instrText)

        fld_end = OxmlElement("w:fldChar")
        fld_end.set(qn("w:fldCharType"), "end")
        run_page._r.append(fld_end)

        # " of " + NUMPAGES
        run_of = para.add_run(" of ")
        run_of.font.size = Pt(8)

        fld2 = OxmlElement("w:fldChar")
        fld2.set(qn("w:fldCharType"), "begin")
        run_of._r.append(fld2)

        instrText2 = OxmlElement("w:instrText")
        instrText2.set(qn("xml:space"), "preserve")
        instrText2.text = " NUMPAGES "
        run_of._r.append(instrText2)

        fld2_end = OxmlElement("w:fldChar")
        fld2_end.set(qn("w:fldCharType"), "end")
        run_of._r.append(fld2_end)


def _insert_toc(doc: Document) -> None:
    """Insert a Table of Contents field that Word will populate on open."""
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


def _add_cover_page(doc: Document, title: str, company: str,
                    font_family: str, primary_rgb: tuple[int, int, int]) -> None:
    """Add a minimal branded cover page with title and company, then a page break."""
    # Spacer
    for _ in range(4):
        sp = doc.add_paragraph()
        sp.paragraph_format.space_before = Pt(0)
        sp.paragraph_format.space_after = Pt(0)

    # Title
    title_para = doc.add_paragraph()
    title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title_para.add_run(title)
    run.font.name = font_family
    run.font.size = Pt(28)
    run.font.bold = True
    run.font.color.rgb = RGBColor(*primary_rgb)

    doc.add_paragraph()

    # Company / subtitle
    if company:
        co_para = doc.add_paragraph()
        co_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        co_run = co_para.add_run(company)
        co_run.font.name = font_family
        co_run.font.size = Pt(14)
        co_run.font.color.rgb = RGBColor(*primary_rgb)

    # Date
    date_para = doc.add_paragraph()
    date_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    date_run = date_para.add_run(datetime.now(IST).strftime("%B %Y"))
    date_run.font.name = font_family
    date_run.font.size = Pt(11)

    # Page break
    doc.add_page_break()


def _apply_core_properties(doc: Document, title: str, company: str, author: str) -> None:
    try:
        props = doc.core_properties
        props.title = title[:255]
        props.author = author[:255]
        props.company = company[:255]
        props.modified = datetime.now(IST)
        props.keywords = "processdoc,docx"
    except Exception as exc:
        logger.debug("Core properties skipped: %s", exc)


def _parse_inline(text: str) -> list[tuple[str, bool, bool]]:
    """Parse inline **bold** and *italic* markers.
    Returns list of (text, bold, italic) tuples.
    """
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
            result.append((m.group(4), False, False))  # code inline treated as plain
        else:
            result.append((m.group(3), False, True))
        last = m.end()
    if last < len(text):
        result.append((text[last:], False, False))
    return result or [(text, False, False)]


def _add_inline_paragraph(doc: Document, text: str, font_family: str,
                           style: str = "Normal", bold: bool = False) -> None:
    para = doc.add_paragraph(style=style)
    for fragment, is_bold, is_italic in _parse_inline(text):
        run = para.add_run(fragment)
        run.font.name = font_family
        run.bold = bold or is_bold
        run.italic = is_italic
    return para


class DOCXDeliverable(IDeliverable):
    def get_metadata(self) -> DeliverableMetadata:
        return DeliverableMetadata(
            output_type="docx",
            file_extension=".docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            intermediate_format="markdown",
            skill_output_key="docx_markdown",
        )

    def render(self, payload: dict[str, Any], run_dir: Path, branding: Any | None = None) -> Path | None:
        from app.core.config import settings

        if getattr(settings, "docx_composer_enabled", True):
            try:
                return self._render_composed(payload, run_dir, branding)
            except Exception as exc:  # noqa: BLE001 - fail-soft to the legacy path
                logger.warning("DOCX composer path failed (%s); falling back to legacy render", exc)
        return self._render_legacy(payload, run_dir, branding)

    def _render_composed(self, payload: dict[str, Any], run_dir: Path, branding: Any | None = None) -> Path | None:
        import json

        from app.core import docx_components as C
        from app.core.deliverable_utils import parse_markdown_blocks
        from app.core.doc_theme import resolve_doc_theme
        from app.core.docx_composer import DocxComposer
        from app.core.markdown_guard import detect_code_document

        out = run_dir / "output.docx"
        text = safe_text(payload.get("docx_markdown") or payload.get("narrative_md"), "Process document")
        code_issues = detect_code_document(text)
        if code_issues:
            logger.warning("DOCX body looks like generator code (%s); using narrative fallback", code_issues)
            fallback = safe_text(payload.get("narrative_md"), "")
            text = fallback if fallback and not detect_code_document(fallback) else "Process document"

        pm = payload.get("process_model") if isinstance(payload.get("process_model"), dict) else {}
        process_name = safe_text(pm.get("process_name") if pm else None, "Process Output")
        theme = resolve_doc_theme(branding, process_name)
        company = theme.company_name
        author = str(payload.get("owner_name") or company or "ProcessDoc Studio")

        doc = Document()
        C.apply_theme_styles(doc, theme)
        C.set_page_margins(doc)
        C.apply_core_properties(doc, process_name, company, author)
        C.cover_page(doc, theme, process_name, company)

        toc_heading = doc.add_heading("Table of Contents", level=1)
        for run in toc_heading.runs:
            run.font.name = theme.font_header
        C.insert_toc(doc)
        C.page_footer(doc, theme, company)

        composer = DocxComposer(doc, theme)
        composer.compose(parse_markdown_blocks(text))
        doc.save(out)

        try:
            (run_dir / "docx_render_signals.json").write_text(
                json.dumps({"fit_report": composer.fit_report}, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug("docx_render_signals persist skipped: %s", exc)

        try:
            from app.core.docx_qa import validate_docx

            (run_dir / "docx_qa.json").write_text(
                json.dumps(validate_docx(out), indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug("docx_qa skipped: %s", exc)

        return out

    def _render_legacy(self, payload: dict[str, Any], run_dir: Path, branding: Any | None = None) -> Path | None:
        out = run_dir / "output.docx"
        text = safe_text(payload.get("docx_markdown") or payload.get("narrative_md"), "Process document")

        # Last line of defence: never render generator source code as the body.
        from app.core.markdown_guard import detect_code_document

        code_issues = detect_code_document(text)
        if code_issues:
            logger.warning("DOCX body looks like generator code (%s); using narrative fallback", code_issues)
            fallback = safe_text(payload.get("narrative_md"), "")
            text = fallback if fallback and not detect_code_document(fallback) else "Process document"

        from app.core.deliverable_pptx import _merge_branding_dict

        brand = _merge_branding_dict(branding)
        pm = payload.get("process_model") if isinstance(payload.get("process_model"), dict) else {}
        title = safe_text(pm.get("process_name") if pm else None, "Process Output")
        font_family = str(brand.get("font_family") or "Calibri")
        primary_rgb = _rgb_tuple(brand.get("primary_color"))
        company = str(brand.get("company_name") or "Deloitte")
        author = str(payload.get("owner_name") or company or "ProcessDoc Studio")

        doc = Document()

        _apply_normal_style(doc, font_family)
        _apply_heading_styles(doc, font_family, primary_rgb)
        _set_page_margins(doc)
        _apply_core_properties(doc, title, company, author)

        _add_cover_page(doc, title, company, font_family, primary_rgb)

        # TOC heading + field
        toc_heading = doc.add_heading("Table of Contents", level=1)
        for run in toc_heading.runs:
            run.font.name = font_family
        _insert_toc(doc)

        _add_page_number_footer(doc, company, primary_rgb)

        # Body
        for block in parse_markdown_blocks(text):
            btype = block["type"]
            if btype == "heading":
                level = min(4, max(1, int(block.get("level", 1))))
                doc.add_heading(safe_text(block.get("text"), ""), level=level)

            elif btype == "paragraph":
                _add_inline_paragraph(doc, safe_text(block.get("text"), ""), font_family)

            elif btype == "bullets":
                for item in block.get("items", []):
                    _add_inline_paragraph(doc, safe_text(item, ""), font_family, style="List Bullet")

            elif btype == "numbered":
                for item in block.get("items", []):
                    _add_inline_paragraph(doc, safe_text(item, ""), font_family, style="List Number")

            elif btype == "code":
                para = doc.add_paragraph()
                run = para.add_run(block.get("text", ""))
                run.font.name = "Courier New"
                run.font.size = Pt(9)
                # Light gray background
                pPr = para._p.get_or_add_pPr()
                shd = OxmlElement("w:shd")
                shd.set(qn("w:val"), "clear")
                shd.set(qn("w:color"), "auto")
                shd.set(qn("w:fill"), "F5F5F5")
                pPr.append(shd)

            elif btype == "table":
                rows = block.get("rows") or []
                if not rows:
                    continue
                cols = max(len(r) for r in rows)
                table = doc.add_table(rows=len(rows), cols=cols)
                table.style = "Table Grid"
                for r_idx, row in enumerate(rows):
                    for c_idx in range(cols):
                        val = row[c_idx] if c_idx < len(row) else ""
                        cell = table.cell(r_idx, c_idx)
                        cell.text = safe_text(val, "")
                        if r_idx == 0:
                            for run in cell.paragraphs[0].runs:
                                run.bold = True
                doc.add_paragraph()

        doc.save(out)
        return out

    def extract_quality_signals(self, artifact_path: Path) -> dict[str, Any]:
        try:
            doc = Document(str(artifact_path))
            headings = 0
            words = 0
            for p in doc.paragraphs:
                text = (p.text or "").strip()
                if not text:
                    continue
                words += len(text.split())
                style_name = str(getattr(p.style, "name", "") or "").lower()
                if "heading" in style_name:
                    headings += 1
            return {"paragraph_count": len(doc.paragraphs), "word_count": words, "heading_count": headings}
        except Exception:
            return super().extract_quality_signals(artifact_path)
