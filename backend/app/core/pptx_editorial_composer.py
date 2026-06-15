"""Editorial slide composer.

A drop-in sibling of ``SlideComposer`` (same ``compose_title_slide`` /
``compose_content_slide`` interface) that renders the typography-led consulting
design language from the component library. The renderer selects between the two
composers by theme; this one is reached when the resolved theme is ``editorial``.

It re-skins the original nine slide types (title, bullets, stat_cards,
column_cards, table, chart, big_number, process_flow, stack_layers,
section_divider). New reference-vocabulary types arrive in Phase 3.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

from app.core import pptx_components as C
from app.core import pptx_text_metrics as tm
from app.core.deliverable_utils import fetch_logo_source
from app.core.pptx_components import Rect, add_rect, rgb, textbox
from app.core.pptx_theme import DeckTheme

logger = logging.getLogger(__name__)

SLIDE_W = C.SLIDE_W
SLIDE_H = C.SLIDE_H

# Legacy fill tokens → editorial accent role.
_FILL_TO_ACCENT = {
    "dark": "ink", "mid_dark": "ink", "green": "primary", "dark_green": "primary",
    "gray": "muted", "mid": "muted",
}


class EditorialSlideComposer:
    """Composition-based slide builder for the editorial theme."""

    def __init__(self, prs: Presentation, branding: dict[str, Any], theme: DeckTheme):
        self.prs = prs
        self.branding = branding
        self.theme = theme
        self.logo_url = str(branding.get("logo_url") or "").strip()
        self.deck_label = self._deck_label(branding)

    def _deck_label(self, b: dict[str, Any]) -> str:
        ft = str(b.get("footer_text") or "").strip()
        if ft:
            return ft.rstrip(".")
        return str(b.get("company_name") or "Deloitte").strip().rstrip(".")

    def _accent_for(self, token: str | None) -> str:
        return self.theme.color(_FILL_TO_ACCENT.get((token or "").lower().strip(), "primary"))

    def _blank(self) -> Any:
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = rgb(self.theme.color("inverse"))
        return slide

    # --- cover ---------------------------------------------------------------

    def compose_title_slide(self, slide_dict: dict[str, Any]) -> None:
        slide = self._blank()
        t = self.theme
        m_h = t.spacing["margin_h"]
        # Concentric motif anchored on the right.
        with contextlib.suppress(Exception):
            C.concentric_circles_motif(slide, t, cx=SLIDE_W - 3.0, cy=SLIDE_H * 0.42)
        # Eyebrow (company / context), large two-tone title, kicker.
        eyebrow = str(slide_dict.get("eyebrow") or slide_dict.get("company_context") or self.deck_label)
        C.micro_label(slide, t, m_h, 0.7, SLIDE_W * 0.6, eyebrow, color=t.color("primary"))
        title = str(slide_dict.get("title", "Title"))
        emphasis = slide_dict.get("emphasis")
        fit = tm.fit_text(title, box_w_in=SLIDE_W * 0.62, box_h_in=2.6, family=t.font_header,
                          max_pt=t.type_scale["display"], min_pt=30, bold=True, max_lines=3)
        ttf = textbox(slide, m_h, 2.0, SLIDE_W * 0.62, 2.8)
        title_p = ttf.paragraphs[0]
        # Two-tone headline: all runs share one paragraph so wrapping flows.
        for seg, is_emph in C._split_emphasis(title, emphasis):
            C.add_run(title_p, seg, font=t.font_header, size=fit.pt, bold=True,
                      color=t.color("primary") if is_emph else t.color("ink"))
        subtitle = str(slide_dict.get("subtitle") or "")
        if subtitle:
            sf = tm.fit_text(subtitle, box_w_in=SLIDE_W * 0.55, box_h_in=1.2, family=t.font_header,
                             max_pt=t.type_scale["cover_subtitle"], min_pt=12, max_lines=3)
            stf = textbox(slide, m_h, 2.2 + fit.pt * 3 * 1.1 / 72.0, SLIDE_W * 0.55, sf.height_in + 0.3)
            for i, ln in enumerate(sf.lines or [subtitle]):
                p = stf.paragraphs[0] if i == 0 else stf.add_paragraph()
                C.add_run(p, ln, font=t.font_header, size=sf.pt, color=t.color("muted"))
        # Metadata band (PREPARED FOR / HORIZON / DATE).
        C.cover_metadata_band(slide, t, self._cover_meta(slide_dict))
        self._add_logo(slide)

    def _cover_meta(self, slide_dict: dict[str, Any]) -> list[tuple[str, str]]:
        meta = slide_dict.get("metadata") or slide_dict.get("cover_meta")
        out: list[tuple[str, str]] = []
        if isinstance(meta, dict):
            out = [(str(k), str(v)) for k, v in meta.items()]
        elif isinstance(meta, list):
            for item in meta:
                if isinstance(item, dict) and "label" in item:
                    out.append((str(item.get("label")), str(item.get("value", ""))))
                elif isinstance(item, (list, tuple)) and len(item) == 2:
                    out.append((str(item[0]), str(item[1])))
        if not out:
            badges = slide_dict.get("badges") or []
            if badges:
                out = [("HIGHLIGHTS", " · ".join(str(b) for b in badges))]
        return out[:4]

    def _add_logo(self, slide: Any) -> None:
        if not self.logo_url:
            return
        source = fetch_logo_source(self.logo_url)
        if not source:
            return
        with contextlib.suppress(Exception):
            slide.shapes.add_picture(source, Inches(SLIDE_W - 2.1), Inches(0.55), width=Inches(1.4))

    # --- content dispatch ----------------------------------------------------

    def compose_content_slide(
        self, slide_dict: dict[str, Any], slide_type: str, page_num: int, total_pages: int
    ) -> None:
        if slide_type == "section_divider":
            self._compose_section_divider(slide_dict)
            return
        slide = self._blank()
        C.slide_border_frame(slide, self.theme)
        content_top = C.header_block(
            slide, self.theme,
            title=str(slide_dict.get("title", "")),
            eyebrow=str(slide_dict.get("subtitle", "")),
            section_number=str(slide_dict.get("section_number", "")),
            emphasis=slide_dict.get("emphasis"),
            kicker=str(slide_dict.get("kicker", "")),
        )
        content_bottom = SLIDE_H - self.theme.spacing["margin_v"] - 0.55
        m_h = self.theme.spacing["margin_h"]
        rect = Rect(m_h, content_top, SLIDE_W - 2 * m_h, max(0.5, content_bottom - content_top))

        handlers = {
            "bullets": self._compose_bullets,
            "stat_cards": self._compose_stat_cards,
            "column_cards": self._compose_column_cards,
            "table": self._compose_table,
            "chart": self._compose_chart,
            "big_number": self._compose_big_number,
            "process_flow": self._compose_process_flow,
            "stack_layers": self._compose_stack_layers,
        }
        handler = handlers.get(slide_type, self._compose_bullets)
        with contextlib.suppress(Exception):
            handler(slide, slide_dict, rect)
        C.footer_band(slide, self.theme, self.deck_label, page_num, total_pages)

    # --- type composers ------------------------------------------------------

    def _compose_bullets(self, slide: Any, slide_dict: dict[str, Any], r: Rect) -> None:
        bullets = [str(b) for b in slide_dict.get("bullets", []) if str(b).strip()][:6]
        if not bullets:
            return
        t = self.theme
        row_h = r.h / len(bullets)
        for i, bullet in enumerate(bullets):
            y = r.y + i * row_h
            C.numbered_circle(slide, t, r.x, y + 0.04, i + 1, d=0.4)
            tx = r.x + 0.62
            tw = r.w - 0.62
            bf = tm.fit_text(bullet, box_w_in=tw, box_h_in=row_h - 0.12, family=t.font_body,
                             max_pt=t.type_scale["body"] + 1, min_pt=10, max_lines=3)
            tf = C.textbox(slide, tx, y, tw, row_h - 0.1, anchor=MSO_ANCHOR.MIDDLE)
            for j, ln in enumerate(bf.lines or [bullet]):
                p = tf.paragraphs[0] if j == 0 else tf.add_paragraph()
                C.add_run(p, ln, font=t.font_body, size=bf.pt, color=t.color("ink"))
            if i < len(bullets) - 1:
                C.hairline_rule(slide, t, r.x, y + row_h - 0.02, r.w)

    def _compose_stat_cards(self, slide: Any, slide_dict: dict[str, Any], r: Rect) -> None:
        cards = slide_dict.get("stat_cards", [])[:6]
        if not cards:
            return
        cols = min(len(cards), 3) or 1
        rows = (len(cards) + cols - 1) // cols
        gut = self.theme.spacing["gutter"]
        cw = (r.w - (cols - 1) * gut) / cols
        ch = min((r.h - (rows - 1) * gut) / rows, 1.7)
        # Vertically centre the card block in the band so short decks stay balanced.
        block_h = rows * ch + (rows - 1) * gut
        y0 = r.y + max(0.0, (r.h - block_h) / 2)
        for idx, c in enumerate(cards):
            col = idx % cols
            row = idx // cols
            cx = r.x + col * (cw + gut)
            cy = y0 + row * (ch + gut)
            C.stat_block(
                slide, self.theme, Rect(cx, cy, cw, ch),
                value=str(c.get("stat", "")), label=str(c.get("label", "")),
                desc=str(c.get("description", "")), accent=self._accent_for(c.get("fill")),
            )

    def _compose_column_cards(self, slide: Any, slide_dict: dict[str, Any], r: Rect) -> None:
        cards = slide_dict.get("column_cards", [])[:3]
        if not cards:
            return
        cols = len(cards)
        gut = self.theme.spacing["gutter"]
        cw = (r.w - (cols - 1) * gut) / cols
        for idx, c in enumerate(cards):
            cx = r.x + idx * (cw + gut)
            C.card(
                slide, self.theme, Rect(cx, r.y, cw, r.h),
                heading=str(c.get("heading", "")), body=str(c.get("body", "")),
                top_color=self._accent_for(c.get("accent")),
            )

    def _compose_table(self, slide: Any, slide_dict: dict[str, Any], r: Rect) -> None:
        data = slide_dict.get("table", {})
        if not isinstance(data, dict):
            return
        headers = data.get("headers", [])
        rows = data.get("rows", [])[:10]
        if not rows and not headers:
            return
        all_rows = ([headers] if headers else []) + rows
        cols = max(len(headers) if headers else 0, max((len(x) for x in rows), default=0))
        if cols == 0:
            return
        t = self.theme
        tbl = slide.shapes.add_table(
            len(all_rows), cols, Inches(r.x), Inches(r.y), Inches(r.w), Inches(min(r.h, 0.45 * len(all_rows)))
        ).table
        for ri, row in enumerate(all_rows):
            is_header = ri == 0 and bool(headers)
            for ci in range(cols):
                cell = tbl.cell(ri, ci)
                cell.text = str(row[ci]) if ci < len(row) else ""
                para = cell.text_frame.paragraphs[0]
                para.alignment = PP_ALIGN.LEFT
                cell.fill.solid()
                if is_header:
                    para.font.bold = True
                    para.font.size = Pt(11)
                    para.font.name = t.font_header
                    para.font.color.rgb = rgb(t.color("inverse"))
                    cell.fill.fore_color.rgb = rgb(t.color("primary"))
                else:
                    para.font.size = Pt(10)
                    para.font.name = t.font_body
                    para.font.color.rgb = rgb(t.color("ink"))
                    cell.fill.fore_color.rgb = rgb(t.color("inverse"))

    def _chart_palette(self) -> list[RGBColor]:
        t = self.theme
        return [rgb(t.color(role)) for role in ("primary", "status_in_build", "status_planned", "accent", "muted")]

    def _compose_chart(self, slide: Any, slide_dict: dict[str, Any], r: Rect) -> None:
        data = slide_dict.get("chart", {})
        if not isinstance(data, dict):
            return
        categories = data.get("categories", [])
        series_data = data.get("series", [])
        if not categories or not series_data:
            return
        type_map = {
            "column": XL_CHART_TYPE.COLUMN_CLUSTERED, "line": XL_CHART_TYPE.LINE,
            "bar": XL_CHART_TYPE.BAR_CLUSTERED, "pie": XL_CHART_TYPE.PIE, "area": XL_CHART_TYPE.AREA,
        }
        ctype = type_map.get(str(data.get("type", "column")).lower(), XL_CHART_TYPE.COLUMN_CLUSTERED)
        cd = CategoryChartData()
        cd.categories = categories
        for s in series_data:
            if isinstance(s, dict) and s.get("name") and s.get("values"):
                cd.add_series(str(s["name"]), tuple(s["values"]))
        try:
            chart = slide.shapes.add_chart(ctype, Inches(r.x), Inches(r.y), Inches(r.w), Inches(r.h * 0.92), cd).chart
            with contextlib.suppress(Exception):
                chart.has_legend = len(series_data) > 1
            palette = self._chart_palette()
            for i, series in enumerate(chart.series):
                with contextlib.suppress(Exception):
                    series.format.fill.solid()
                    series.format.fill.fore_color.rgb = palette[i % len(palette)]
                    series.format.line.fill.solid()
                    series.format.line.fill.fore_color.rgb = palette[i % len(palette)]
        except Exception as exc:
            logger.warning("editorial chart failed: %s", exc)

    def _compose_big_number(self, slide: Any, slide_dict: dict[str, Any], r: Rect) -> None:
        bn = slide_dict.get("big_number", {})
        if not isinstance(bn, dict) or not str(bn.get("stat", "")):
            return
        t = self.theme
        on_dark = (bn.get("fill") or "").lower() in {"dark", "mid_dark", "green", "dark_green"}
        if on_dark:
            add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=t.color("panel"))
        ink = t.color("inverse") if on_dark else t.color("ink")
        accent = t.color("inverse") if on_dark else t.color("primary")
        stat = str(bn.get("stat", ""))
        sf = tm.fit_text(stat, box_w_in=r.w, box_h_in=r.h * 0.55, family=t.font_header,
                         max_pt=96, min_pt=40, bold=True, max_lines=1)
        stf = textbox(slide, r.x, r.y + r.h * 0.12, r.w, sf.pt * 1.2 / 72.0 + 0.2)
        sp = stf.paragraphs[0]
        sp.alignment = PP_ALIGN.CENTER
        C.add_run(sp, stat, font=t.font_header, size=sf.pt, bold=True, color=accent)
        label = str(bn.get("label", ""))
        if label:
            ltf = textbox(slide, r.x, r.y + r.h * 0.12 + sf.pt * 1.3 / 72.0, r.w, 0.6)
            lp = ltf.paragraphs[0]
            lp.alignment = PP_ALIGN.CENTER
            C.add_run(lp, label, font=t.font_header, size=t.type_scale["kicker"], color=ink)
        context = str(bn.get("context", "")).strip()
        if context:
            ctf = textbox(slide, r.x + r.w * 0.15, r.bottom - 0.6, r.w * 0.7, 0.5)
            cp = ctf.paragraphs[0]
            cp.alignment = PP_ALIGN.CENTER
            C.add_run(cp, context, font=t.font_body, size=t.type_scale["body"], color=ink)

    def _compose_process_flow(self, slide: Any, slide_dict: dict[str, Any], r: Rect) -> None:
        raw = slide_dict.get("process_flow", [])
        steps = raw.get("steps", []) if isinstance(raw, dict) else raw
        steps = [s for s in steps if isinstance(s, dict)][:5]
        if not steps:
            return
        t = self.theme
        gut = t.spacing["gutter"]
        sw = (r.w - (len(steps) - 1) * gut) / len(steps)
        sh = min(r.h, 2.6)
        sy = r.y + max(0.0, (r.h - sh) / 2)
        for idx, step in enumerate(steps):
            x = r.x + idx * (sw + gut)
            top_color = self._accent_for(step.get("fill"))
            add_rect(slide, x, sy, sw, sh, fill=t.color("inverse"), line=t.color("hairline"), line_pt=0.75)
            add_rect(slide, x, sy, sw, 0.05, fill=top_color)
            C.numbered_circle(slide, t, x + 0.16, sy + 0.18, idx + 1, d=0.4)
            label = str(step.get("label", ""))
            ltf = textbox(slide, x + 0.16, sy + 0.7, sw - 0.32, 0.5)
            lf = tm.fit_text(label, box_w_in=sw - 0.32, box_h_in=0.5, family=t.font_header,
                             max_pt=t.type_scale["card_title"], min_pt=10, bold=True, max_lines=2)
            for i, ln in enumerate(lf.lines or [label]):
                p = ltf.paragraphs[0] if i == 0 else ltf.add_paragraph()
                C.add_run(p, ln, font=t.font_header, size=lf.pt, bold=True, color=t.color("ink"))
            desc = str(step.get("description", "")).strip()
            if desc:
                dtf = textbox(slide, x + 0.16, sy + 1.35, sw - 0.32, sh - 1.45)
                df = tm.fit_text(desc, box_w_in=sw - 0.32, box_h_in=sh - 1.45, family=t.font_body,
                                 max_pt=t.type_scale["body"] - 2, min_pt=8)
                for i, ln in enumerate(df.lines or [desc]):
                    p = dtf.paragraphs[0] if i == 0 else dtf.add_paragraph()
                    C.add_run(p, ln, font=t.font_body, size=df.pt, color=t.color("muted"))

    def _compose_stack_layers(self, slide: Any, slide_dict: dict[str, Any], r: Rect) -> None:
        layers = [x for x in slide_dict.get("stack_layers", []) if isinstance(x, dict)][:6]
        if not layers:
            return
        t = self.theme
        gut = t.spacing["gutter"] * 0.6
        lh = (r.h - (len(layers) - 1) * gut) / len(layers)
        for idx, layer in enumerate(layers):
            y = r.y + idx * (lh + gut)
            accent = self._accent_for(layer.get("fill"))
            add_rect(slide, r.x, y, r.w, lh, fill=t.color("tint"))
            add_rect(slide, r.x, y, 0.06, lh, fill=accent)
            label = str(layer.get("label", ""))
            ltf = textbox(slide, r.x + 0.22, y, r.w * 0.24, lh, anchor=MSO_ANCHOR.MIDDLE)
            C.add_run(ltf.paragraphs[0], label, font=t.font_header, size=t.type_scale["card_title"],
                      bold=True, color=t.color("ink"))
            desc = str(layer.get("description", "")).strip()
            if desc:
                dtf = textbox(slide, r.x + r.w * 0.28, y, r.w * 0.7, lh, anchor=MSO_ANCHOR.MIDDLE)
                df = tm.fit_text(desc, box_w_in=r.w * 0.68, box_h_in=lh, family=t.font_body,
                                 max_pt=t.type_scale["body"], min_pt=8, max_lines=3)
                C.add_run(dtf.paragraphs[0], desc, font=t.font_body, size=df.pt, color=t.color("muted"))

    def _compose_section_divider(self, slide_dict: dict[str, Any]) -> None:
        slide = self._blank()
        t = self.theme
        add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=t.color("panel"))
        with contextlib.suppress(Exception):
            C.concentric_circles_motif(slide, t, cx=SLIDE_W - 2.6, cy=SLIDE_H * 0.5, on_dark=True)
        m_h = t.spacing["margin_h"]
        eyebrow = str(slide_dict.get("subtitle") or slide_dict.get("eyebrow") or "")
        if eyebrow:
            C.micro_label(slide, t, m_h, SLIDE_H * 0.30, SLIDE_W * 0.7, eyebrow, color=t.color("primary"))
        title = str(slide_dict.get("title", ""))
        emphasis = slide_dict.get("emphasis")
        fit = tm.fit_text(title, box_w_in=SLIDE_W * 0.7, box_h_in=2.2, family=t.font_header,
                          max_pt=t.type_scale["display"], min_pt=28, bold=True, max_lines=3)
        ttf = textbox(slide, m_h, SLIDE_H * 0.36, SLIDE_W * 0.72, 2.4)
        p = ttf.paragraphs[0]
        for seg, is_emph in C._split_emphasis(title, emphasis):
            C.add_run(p, seg, font=t.font_header, size=fit.pt, bold=True,
                      color=t.color("primary") if is_emph else t.color("inverse"))
