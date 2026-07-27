"""Multi-format deck exporter for PPTX slide JSON.

Given a list of slide dictionaries (same contract as `pptx_slides`), this module
produces two additional deliverable artifacts beside the canonical PPTX:

- ``deck.html``: a single self-contained HTML document that mirrors the canvas
  preview used in the frontend deck viewer.
- ``deck.pdf``: a portrait/landscape PDF rendering of the same deck for easy
  offline review.

The exporter is **fail-open**: any failure writing one format never prevents the
other from being written, and never raises back to the caller. This keeps the
PPTX pipeline stable even when an optional format dependency is missing or the
runtime environment is constrained.
"""

from __future__ import annotations

import html
import logging
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_DEFAULT_BRANDING: dict[str, str] = {
    "primary_color": "#86BC25",
    "secondary_color": "#E8007C",
    "accent_light": "#EBF5D3",
    "accent_dark": "#5A8A00",
    "text_primary": "#1A1A1A",
    "text_inverse": "#FFFFFF",
    "font_family": "Calibri, Helvetica, Arial, sans-serif",
    "company_name": "Deloitte",
    "footer_text": "Deloitte.",
}


@dataclass
class DeckExportResult:
    """Paths produced by the exporter. Missing values indicate a fail-open skip."""

    html_path: Path | None = None
    pdf_path: Path | None = None
    pdf_source: str | None = None
    errors: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "html_path": str(self.html_path) if self.html_path else None,
            "pdf_path": str(self.pdf_path) if self.pdf_path else None,
            "pdf_source": self.pdf_source,
            "errors": list(self.errors or []),
        }


def _normalize_branding(branding: Any) -> dict[str, str]:
    merged = dict(_DEFAULT_BRANDING)
    if isinstance(branding, dict):
        for key in _DEFAULT_BRANDING:
            value = branding.get(key)
            if value is None or value == "":
                continue
            merged[key] = str(value)
    elif branding is not None:
        for key in _DEFAULT_BRANDING:
            value = getattr(branding, key, None)
            if value is None or value == "":
                continue
            merged[key] = str(value)
    if not str(merged.get("footer_text") or "").strip():
        company = str(merged.get("company_name") or "Company").strip()
        merged["footer_text"] = company if company.endswith(".") else f"{company}."
    return merged


def _coerce_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _coerce_process_flow_steps(slide: dict[str, Any]) -> list[dict[str, Any]]:
    """Steps arrive either as {"steps": [...]} or as a bare list."""
    raw = slide.get("process_flow")
    if isinstance(raw, dict):
        raw = raw.get("steps")
    return [s for s in _coerce_list(raw) if isinstance(s, dict)]


def _safe_str(value: Any, fallback: str = "") -> str:
    text = str(value) if value is not None else ""
    return text.strip() or fallback


def _esc(value: Any) -> str:
    return html.escape(_safe_str(value), quote=True)


def _render_slide_body_html(slide: dict[str, Any], brand: dict[str, str]) -> str:
    slide_type = _safe_str(slide.get("slide_type"), "bullets").lower()
    if slide_type == "title":
        return (
            f"<h1 class=\"deck-title\">{_esc(slide.get('title') or 'Untitled')}</h1>"
            f"<p class=\"deck-subtitle\">{_esc(slide.get('subtitle') or 'Executive overview')}</p>"
        )
    if slide_type == "section_divider":
        return (
            "<div class=\"deck-divider\">"
            f"<h2>{_esc(slide.get('title') or 'Section')}</h2>"
            f"<p>{_esc(slide.get('subtitle') or '')}</p>"
            "</div>"
        )
    if slide_type == "stat_cards":
        cards = _coerce_list(slide.get("stat_cards"))
        items = "".join(
            (
                "<div class=\"deck-card\">"
                f"<p class=\"deck-card-stat\">{_esc((c or {}).get('stat') if isinstance(c, dict) else c) or '—'}</p>"
                f"<p class=\"deck-card-label\">{_esc((c or {}).get('label') if isinstance(c, dict) else '')}</p>"
                f"<p class=\"deck-card-body\">{_esc((c or {}).get('description') if isinstance(c, dict) else '')}</p>"
                "</div>"
            )
            for c in cards[:6]
        )
        return f"<div class=\"deck-grid\">{items}</div>"
    if slide_type == "process_flow":
        steps = _coerce_process_flow_steps(slide)
        items = "".join(
            (
                "<div class=\"deck-card\">"
                f"<p class=\"deck-card-heading\">{i}. {_esc(step.get('label') or '')}</p>"
                f"<p class=\"deck-card-body\">{_esc(step.get('description') or '')}</p>"
                "</div>"
            )
            for i, step in enumerate(steps[:8], start=1)
        )
        return f"<div class=\"deck-grid\">{items}</div>"
    if slide_type == "big_number":
        big = slide.get("big_number") if isinstance(slide.get("big_number"), dict) else {}
        return (
            "<div class=\"deck-divider\">"
            f"<p class=\"deck-card-stat\">{_esc(big.get('stat') or '—')}</p>"
            f"<p class=\"deck-card-label\">{_esc(big.get('label') or '')}</p>"
            f"<p class=\"deck-card-body\">{_esc(big.get('context') or '')}</p>"
            "</div>"
        )
    if slide_type == "chart":
        chart = slide.get("chart") if isinstance(slide.get("chart"), dict) else {}
        categories = [_safe_str(c) for c in _coerce_list(chart.get("categories"))]
        series_rows: list[str] = []
        for series in _coerce_list(chart.get("series"))[:6]:
            if not isinstance(series, dict):
                continue
            values = [_safe_str(v) for v in _coerce_list(series.get("values"))]
            cells = "".join(f"<td>{_esc(v)}</td>" for v in values[: len(categories) or None])
            series_rows.append(f"<tr><td>{_esc(series.get('name') or '')}</td>{cells}</tr>")
        head = "".join(f"<th>{_esc(c)}</th>" for c in categories)
        return (
            "<table class=\"deck-table\">"
            f"<thead><tr><th></th>{head}</tr></thead>"
            f"<tbody>{''.join(series_rows)}</tbody>"
            "</table>"
        )
    if slide_type in {"column_cards", "stack_layers"}:
        key = slide_type
        rows = _coerce_list(slide.get(key))
        items = "".join(
            (
                "<div class=\"deck-card\">"
                f"<p class=\"deck-card-heading\">{_esc((c or {}).get('heading') or (c or {}).get('label') or '')}</p>"
                f"<p class=\"deck-card-body\">{_esc((c or {}).get('body') or (c or {}).get('description') or '')}</p>"
                "</div>"
            )
            for c in rows[:6]
            if isinstance(c, dict)
        )
        css = "deck-grid" if slide_type == "column_cards" else "deck-stack"
        return f"<div class=\"{css}\">{items}</div>"
    if slide_type == "table":
        table = slide.get("table") if isinstance(slide.get("table"), dict) else {}
        headers = _coerce_list(table.get("headers"))
        rows = _coerce_list(table.get("rows"))
        head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
        body_rows: list[str] = []
        for row in rows[:20]:
            if not isinstance(row, list):
                continue
            cells = "".join(f"<td>{_esc(cell)}</td>" for cell in row)
            body_rows.append(f"<tr>{cells}</tr>")
        return (
            "<table class=\"deck-table\">"
            f"<thead><tr>{head}</tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody>"
            "</table>"
        )
    bullets = _coerce_list(slide.get("bullets"))
    items = "".join(f"<li>{_esc(b)}</li>" for b in bullets[:10])
    return f"<ul class=\"deck-bullets\">{items}</ul>"


def _render_html(slides: Iterable[dict[str, Any]], brand: dict[str, str]) -> str:
    slide_list = [s for s in slides if isinstance(s, dict)]
    cards = []
    for i, slide in enumerate(slide_list, start=1):
        idx = int(slide.get("slide_index") or i)
        title = _esc(slide.get("title") or f"Slide {idx}")
        slide_type = _esc(slide.get("slide_type") or "bullets")
        body = _render_slide_body_html(slide, brand)
        title_header = ""
        if _safe_str(slide.get("slide_type")).lower() != "title":
            title_header = f"<h2 class=\"deck-slide-title\">{title}</h2>"
        cards.append(
            "<section class=\"deck-slide\">"
            f"<header><span class=\"deck-slide-tag\">Slide {idx}</span>"
            f"<span class=\"deck-slide-type\">{slide_type}</span></header>"
            f"{title_header}{body}"
            "</section>"
        )
    footer_text = _esc(brand.get("footer_text") or "")
    primary = _esc(brand.get("primary_color"))
    accent_light = _esc(brand.get("accent_light"))
    text_primary = _esc(brand.get("text_primary"))
    font_family = _esc(brand.get("font_family"))
    company = _esc(brand.get("company_name"))
    return (
        "<!doctype html><html lang=\"en\"><head>"
        "<meta charset=\"utf-8\"/>"
        f"<title>{company} — Deck Preview</title>"
        "<style>"
        f"body{{font-family:{font_family};color:{text_primary};background:#F6F7F9;"
        "margin:0;padding:24px;}}"
        ".deck-slide{background:#fff;border:1px solid #E5E7EB;border-radius:8px;"
        "padding:18px;margin-bottom:14px;box-shadow:0 1px 2px rgba(15,23,42,.05);}"
        f".deck-slide header{{display:flex;justify-content:space-between;"
        f"color:#6B7280;font-size:12px;border-bottom:2px solid {primary};"
        "padding-bottom:6px;margin-bottom:10px;}}"
        ".deck-slide-type{text-transform:uppercase;letter-spacing:.05em;}"
        f".deck-title{{font-size:28px;margin:0;color:{text_primary};}}"
        ".deck-subtitle{color:#6B7280;margin-top:6px;}"
        ".deck-slide-title{font-size:18px;margin:0 0 10px 0;}"
        ".deck-bullets{margin:0;padding-left:20px;}"
        ".deck-bullets li{margin:4px 0;}"
        ".deck-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;}"
        ".deck-stack{display:flex;flex-direction:column;gap:8px;}"
        f".deck-card{{border:1px solid #E5E7EB;border-radius:6px;padding:10px;background:{accent_light};}}"
        ".deck-card-stat{font-size:20px;font-weight:600;margin:0;}"
        ".deck-card-label{color:#6B7280;font-size:12px;margin:0;}"
        ".deck-card-heading{font-weight:600;margin:0 0 4px 0;}"
        ".deck-card-body{color:#374151;font-size:13px;margin:0;}"
        ".deck-table{width:100%;border-collapse:collapse;font-size:13px;}"
        ".deck-table th,.deck-table td{border:1px solid #E5E7EB;padding:6px 8px;"
        "text-align:left;}"
        ".deck-table thead th{background:#F3F4F6;}"
        f".deck-divider{{background:{accent_light};border-radius:6px;padding:28px;"
        "text-align:center;}}"
        ".deck-footer{color:#9CA3AF;font-size:11px;text-align:right;margin-top:8px;}"
        "</style></head><body>"
        f"{''.join(cards)}"
        f"<p class=\"deck-footer\">{footer_text}</p>"
        "</body></html>"
    )


def _render_pdf(
    slides: Iterable[dict[str, Any]], brand: dict[str, str], out_path: Path
) -> Path | None:
    try:
        from reportlab.lib.colors import HexColor  # type: ignore
        from reportlab.lib.pagesizes import LETTER, landscape  # type: ignore
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # type: ignore
        from reportlab.platypus import (  # type: ignore
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except Exception as exc:  # pragma: no cover - reportlab missing
        logger.warning("deck_exporter: reportlab unavailable; skipping PDF (%s)", exc)
        return None

    try:
        doc = SimpleDocTemplate(
            str(out_path),
            pagesize=landscape(LETTER),
            title=f"{brand.get('company_name', 'Company')} Deck",
            leftMargin=36,
            rightMargin=36,
            topMargin=36,
            bottomMargin=36,
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "DeckTitle",
            parent=styles["Title"],
            textColor=HexColor(brand.get("text_primary") or "#1A1A1A"),
            fontSize=22,
            leading=26,
        )
        heading_style = ParagraphStyle(
            "DeckHeading",
            parent=styles["Heading2"],
            textColor=HexColor(brand.get("text_primary") or "#1A1A1A"),
        )
        body_style = ParagraphStyle(
            "DeckBody",
            parent=styles["BodyText"],
            textColor=HexColor(brand.get("text_primary") or "#1A1A1A"),
            fontSize=11,
            leading=14,
        )
        story: list[Any] = []
        slide_list = [s for s in slides if isinstance(s, dict)]
        for i, slide in enumerate(slide_list, start=1):
            idx = int(slide.get("slide_index") or i)
            slide_type = _safe_str(slide.get("slide_type"), "bullets").lower()
            title_text = _esc(slide.get("title") or f"Slide {idx}")
            if slide_type == "title":
                story.append(Paragraph(title_text, title_style))
                story.append(Spacer(1, 12))
                story.append(
                    Paragraph(
                        _esc(slide.get("subtitle") or "Executive overview"),
                        body_style,
                    )
                )
            elif slide_type == "table":
                story.append(Paragraph(title_text, heading_style))
                story.append(Spacer(1, 6))
                table_payload = slide.get("table") if isinstance(slide.get("table"), dict) else {}
                headers = [_safe_str(h) for h in _coerce_list(table_payload.get("headers"))]
                rows = []
                for row in _coerce_list(table_payload.get("rows"))[:20]:
                    if isinstance(row, list):
                        rows.append([_safe_str(cell) for cell in row])
                data = [headers] + rows if headers else rows
                if data:
                    tbl = Table(data, repeatRows=1 if headers else 0)
                    tbl.setStyle(
                        TableStyle(
                            [
                                (
                                    "BACKGROUND",
                                    (0, 0),
                                    (-1, 0),
                                    HexColor(brand.get("accent_light") or "#EBF5D3"),
                                ),
                                ("GRID", (0, 0), (-1, -1), 0.25, HexColor("#E5E7EB")),
                                ("FONTSIZE", (0, 0), (-1, -1), 9),
                                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ]
                        )
                    )
                    story.append(tbl)
            elif slide_type == "section_divider":
                story.append(Paragraph(title_text, title_style))
                story.append(Spacer(1, 8))
                story.append(
                    Paragraph(_esc(slide.get("subtitle") or ""), body_style)
                )
            else:
                story.append(Paragraph(title_text, heading_style))
                story.append(Spacer(1, 6))
                bullet_source: list[str] = []
                if slide_type == "bullets":
                    bullet_source = [_safe_str(b) for b in _coerce_list(slide.get("bullets"))][:10]
                elif slide_type == "stat_cards":
                    for card in _coerce_list(slide.get("stat_cards"))[:6]:
                        if isinstance(card, dict):
                            stat_line = f"{_safe_str(card.get('stat'))} — {_safe_str(card.get('label'))}".strip(" —")
                            desc = _safe_str(card.get("description"))
                            bullet_source.append(f"{stat_line}: {desc}".strip(": ") if desc else stat_line)
                elif slide_type in {"column_cards", "stack_layers"}:
                    key = slide_type
                    for card in _coerce_list(slide.get(key))[:6]:
                        if isinstance(card, dict):
                            heading = _safe_str(card.get("heading") or card.get("label"))
                            body = _safe_str(card.get("body") or card.get("description"))
                            bullet_source.append(f"{heading}: {body}".strip(": "))
                elif slide_type == "process_flow":
                    for step_no, step in enumerate(_coerce_process_flow_steps(slide)[:8], start=1):
                        label = _safe_str(step.get("label"))
                        desc = _safe_str(step.get("description"))
                        bullet_source.append(f"{step_no}. {label} — {desc}".strip(" —. "))
                elif slide_type == "big_number":
                    big = slide.get("big_number") if isinstance(slide.get("big_number"), dict) else {}
                    stat_line = f"{_safe_str(big.get('stat'))} — {_safe_str(big.get('label'))}".strip(" —")
                    if stat_line:
                        bullet_source.append(stat_line)
                    context = _safe_str(big.get("context"))
                    if context:
                        bullet_source.append(context)
                elif slide_type == "chart":
                    chart = slide.get("chart") if isinstance(slide.get("chart"), dict) else {}
                    categories = [_safe_str(c) for c in _coerce_list(chart.get("categories"))]
                    if categories:
                        bullet_source.append("Categories: " + ", ".join(categories))
                    for series in _coerce_list(chart.get("series"))[:6]:
                        if isinstance(series, dict):
                            values = ", ".join(_safe_str(v) for v in _coerce_list(series.get("values")))
                            bullet_source.append(f"{_safe_str(series.get('name'))}: {values}".strip(": "))
                else:
                    bullet_source = [_safe_str(b) for b in _coerce_list(slide.get("bullets"))][:10]
                for item in bullet_source:
                    if item:
                        story.append(Paragraph(f"• {_esc(item)}", body_style))
            if i != len(slide_list):
                story.append(PageBreak())
        if not story:
            story = [Paragraph("Empty deck", title_style)]
        doc.build(story)
        return out_path
    except Exception as exc:
        logger.warning("deck_exporter: PDF render failed: %s", exc)
        return None


def _convert_pptx_to_pdf(pptx_path: Path, run_dir: Path, pdf_filename: str) -> Path | None:
    """Convert the rendered PPTX to ``pdf_filename`` via LibreOffice. Fail-open."""
    from app.core.soffice_convert import convert_office_to_pdf

    with tempfile.TemporaryDirectory(prefix="deck-pdf-") as tmp:
        produced = convert_office_to_pdf(pptx_path, Path(tmp))
        if produced is None:
            return None
        target = run_dir / pdf_filename
        try:
            target.write_bytes(produced.read_bytes())
        except OSError as exc:
            logger.warning("deck_exporter: cannot write %s: %s", target, exc)
            return None
        return target


def export_deck_artifacts(
    slides: list[dict[str, Any]] | None,
    run_dir: Path,
    branding: Any | None = None,
    *,
    html_filename: str = "deck.html",
    pdf_filename: str = "deck.pdf",
    pptx_path: Path | None = None,
) -> DeckExportResult:
    """Write HTML and PDF representations of the deck. Fail-open on either side.

    When ``pptx_path`` points at the rendered deck and LibreOffice is available,
    the PDF is a faithful conversion of the PPTX; otherwise the ReportLab
    outline renderer produces a text approximation.
    """

    result = DeckExportResult(errors=[])
    if not slides:
        return result
    brand = _normalize_branding(branding)
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("deck_exporter: cannot create run_dir %s: %s", run_dir, exc)
        result.errors.append(f"run_dir: {exc}")
        return result

    try:
        html_text = _render_html(slides, brand)
        html_path = run_dir / html_filename
        html_path.write_text(html_text, encoding="utf-8")
        result.html_path = html_path
    except Exception as exc:
        logger.warning("deck_exporter: HTML write failed: %s", exc)
        result.errors.append(f"html: {exc}")

    from app.core.config import settings

    if (
        settings.deck_pdf_via_soffice_enabled
        and pptx_path is not None
        and pptx_path.exists()
    ):
        converted = _convert_pptx_to_pdf(pptx_path, run_dir, pdf_filename)
        if converted is not None:
            result.pdf_path = converted
            result.pdf_source = "soffice"
            return result
        result.errors.append("pdf: soffice conversion unavailable; using outline fallback")

    pdf_path = run_dir / pdf_filename
    produced = _render_pdf(slides, brand, pdf_path)
    if produced is not None:
        result.pdf_path = produced
        result.pdf_source = "reportlab"
    else:
        result.errors.append("pdf: skipped")

    return result
