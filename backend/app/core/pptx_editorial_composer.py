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

# Legacy fill tokens → editorial accent role. Accent bars/stripes stay on-brand
# (primary/accent), never plain ink — a black accent on one card amid green
# siblings reads as a defect rather than a design choice.
_FILL_TO_ACCENT = {
    "dark": "accent", "mid_dark": "accent", "green": "primary", "dark_green": "primary",
    "gray": "muted", "mid": "muted",
}

# Status key → theme color role.
_STATUS_COLOR_MAP: dict[str, str] = {
    "live": "primary",
    "in_build": "status_in_build",
    "planned": "status_planned",
    "partner": "status_partner",
}


class EditorialSlideComposer:
    """Composition-based slide builder for the editorial theme."""

    def __init__(self, prs: Presentation, branding: dict[str, Any], theme: DeckTheme):
        self.prs = prs
        self.branding = branding
        self.theme = theme
        self.logo_url = str(branding.get("logo_url") or "").strip()
        self.deck_label = self._deck_label(branding)
        # Accumulated overflow/trim events; callers can read fit_report after rendering.
        self.fit_report: list[dict[str, Any]] = []

    def _record_fit(self, slide_num: int, slide_type: str, field: str, action: str) -> None:
        self.fit_report.append({"slide": slide_num, "slide_type": slide_type, "field": field, "action": action})

    def _trim_to_budget(self, text: str, max_chars: int, label: str, page_num: int, slide_type: str) -> str:
        """Trim text to char budget; records the trim so callers can surface it in qa_report."""
        if len(text) <= max_chars:
            return text
        trimmed = text[:max_chars - 1].rsplit(" ", 1)[0] + "…"
        self._record_fit(page_num, slide_type, label, f"trimmed {len(text)}→{len(trimmed)} chars")
        return trimmed

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
        # Full-bleed dark handlers (big_number on a dark fill) paint a slide-filling
        # panel; draw it *before* the header so the heading lands on top instead of
        # being buried, and render the header in inverse so it reads on the panel.
        dark_bg = slide_type == "big_number" and self._big_number_on_dark(slide_dict)
        if dark_bg:
            add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=self.theme.color("panel"))
        content_top = C.header_block(
            slide, self.theme,
            title=str(slide_dict.get("title", "")),
            eyebrow=str(slide_dict.get("subtitle", "")),
            section_number=str(slide_dict.get("section_number", "")),
            emphasis=slide_dict.get("emphasis"),
            kicker=str(slide_dict.get("kicker", "")),
            ink_role="inverse" if dark_bg else "ink",
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
            "split_panel": self._compose_split_panel,
            "lanes": self._compose_lanes,
            "workstream_cards": self._compose_workstream_cards,
            "tower_cards": self._compose_tower_cards,
            "roadmap_matrix": self._compose_roadmap_matrix,
            "swimlane_timeline": self._compose_swimlane_timeline,
            "flagship_cards": self._compose_flagship_cards,
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
        cards = slide_dict.get("column_cards", [])[:4]
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
                    # Zebra striping: faint tint on alternate body rows for scannability.
                    body_idx = ri - (1 if headers else 0)
                    band = t.color("inverse") if body_idx % 2 == 0 else t.color("tint")
                    cell.fill.fore_color.rgb = rgb(band)

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
            "doughnut": XL_CHART_TYPE.DOUGHNUT, "column_stacked": XL_CHART_TYPE.COLUMN_STACKED,
            "percent_stacked": XL_CHART_TYPE.COLUMN_STACKED_100, "bar_stacked": XL_CHART_TYPE.BAR_STACKED,
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

    @staticmethod
    def _big_number_on_dark(slide_dict: dict[str, Any]) -> bool:
        bn = slide_dict.get("big_number", {})
        return isinstance(bn, dict) and (bn.get("fill") or "").lower() in {
            "dark", "mid_dark", "green", "dark_green"
        }

    def _compose_big_number(self, slide: Any, slide_dict: dict[str, Any], r: Rect) -> None:
        bn = slide_dict.get("big_number", {})
        if not isinstance(bn, dict) or not str(bn.get("stat", "")):
            return
        t = self.theme
        # The dark full-bleed panel is painted by the dispatcher (before the header)
        # so the heading is not buried; here we only choose text colours to suit it.
        on_dark = self._big_number_on_dark(slide_dict)
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
            card_bg = add_rect(slide, x, sy, sw, sh, fill=t.color("inverse"), line=t.color("hairline"), line_pt=0.75)
            C.soft_shadow(card_bg)
            add_rect(slide, x, sy, sw, 0.05, fill=top_color)
            C.numbered_circle(slide, t, x + 0.16, sy + 0.18, idx + 1, d=0.4)
            label = str(step.get("label", ""))
            # Vector icon (top-right) — explicit icon name wins, else derive from the label.
            # Falls back to the legacy Unicode glyph if no SVG renderer is available.
            from app.core.icon_library import place_step_icon
            from app.core.pptx_artifact_renderer import _icon_for_step_label
            place_step_icon(
                slide, x + sw - 0.56, sy + 0.16, 0.4,
                label=label,
                # Step markers stay a single consistent accent — the varying top bar
                # already differentiates steps; cycling the icon colour read as random.
                color_hex=t.color("primary"),
                explicit_icon=str(step.get("icon") or "").strip() or None,
                fallback_glyph=_icon_for_step_label(label),
            )
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
        bg = add_rect(slide, 0, 0, SLIDE_W, SLIDE_H, fill=t.color("panel"))
        C.linear_gradient(bg, t.color("panel"), t.color("primary"))
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

    # --- Phase 3: reference vocabulary slide types ----------------------------

    def _compose_split_panel(self, slide: Any, slide_dict: dict[str, Any], r: Rect) -> None:
        """40/60 vertical split — dark left assertion panel + numbered items on right."""
        items = [i for i in slide_dict.get("items", []) if isinstance(i, dict)][:5]
        if not items:
            items = [{"label": str(b), "body": ""} for b in slide_dict.get("bullets", [])][:5]
        if not items:
            return
        t = self.theme
        gut = t.spacing["gutter"]
        left_w = r.w * 0.40
        right_x = r.x + left_w + gut
        right_w = r.w - left_w - gut

        add_rect(slide, r.x, r.y, left_w, r.h, fill=t.color("panel"))
        key_text = str(slide_dict.get("left_label") or items[0].get("label", ""))
        if key_text:
            kf = tm.fit_text(key_text, box_w_in=left_w - 0.36, box_h_in=r.h - 0.4,
                             family=t.font_header, max_pt=t.type_scale["headline"], min_pt=16, bold=True)
            ktf = textbox(slide, r.x + 0.18, r.y + 0.22, left_w - 0.36, r.h - 0.4)
            for i, ln in enumerate(kf.lines or [key_text]):
                p = ktf.paragraphs[0] if i == 0 else ktf.add_paragraph()
                C.add_run(p, ln, font=t.font_header, size=kf.pt, bold=True, color=t.color("inverse"))

        row_h = r.h / len(items)
        for i, item in enumerate(items):
            y = r.y + i * row_h
            C.numbered_circle(slide, t, right_x, y + 0.06, i + 1, d=0.36)
            ix, iw = right_x + 0.52, right_w - 0.52
            label = str(item.get("label", ""))
            if label:
                lf = tm.fit_text(label, box_w_in=iw, box_h_in=0.42, family=t.font_header,
                                 max_pt=t.type_scale["card_title"], min_pt=9, bold=True, max_lines=1)
                ltf = textbox(slide, ix, y + 0.05, iw, 0.44)
                C.add_run(ltf.paragraphs[0], label, font=t.font_header, size=lf.pt, bold=True, color=t.color("ink"))
            body = str(item.get("body", "")).strip()
            if body:
                bf = tm.fit_text(body, box_w_in=iw, box_h_in=row_h - 0.52, family=t.font_body,
                                 max_pt=t.type_scale["body"], min_pt=8, max_lines=2)
                btf = textbox(slide, ix, y + 0.52, iw, row_h - 0.54)
                for k, ln in enumerate(bf.lines or [body]):
                    p = btf.paragraphs[0] if k == 0 else btf.add_paragraph()
                    C.add_run(p, ln, font=t.font_body, size=bf.pt, color=t.color("muted"))
            if i < len(items) - 1:
                C.hairline_rule(slide, t, right_x, y + row_h - 0.04, right_w)

    def _compose_lanes(self, slide: Any, slide_dict: dict[str, Any], r: Rect) -> None:
        """2–4 vertical lanes with label chips + numbered items."""
        lanes = [l for l in slide_dict.get("lanes", []) if isinstance(l, dict)][:4]
        if not lanes:
            return
        t = self.theme
        gut = t.spacing["gutter"]
        lw = (r.w - (len(lanes) - 1) * gut) / len(lanes)
        chip_h = 0.36

        for idx, lane in enumerate(lanes):
            x = r.x + idx * (lw + gut)
            label = str(lane.get("label", ""))
            # Filled label chip spanning full lane width
            add_rect(slide, x, r.y, lw, chip_h, fill=t.color("panel"))
            ctf = textbox(slide, x + 0.1, r.y + 0.04, lw - 0.2, chip_h - 0.06)
            C.add_run(ctf.paragraphs[0], label.upper(), font=t.font_body,
                      size=t.type_scale["micro"] + 0.5, bold=True, color=t.color("inverse"),
                      spc=t.spacing.get("letter_spacing", 2.2))

            items = [str(i) for i in lane.get("items", []) if str(i).strip()][:5]
            if not items:
                continue
            item_top = r.y + chip_h + 0.1
            item_h = (r.h - chip_h - 0.12) / len(items)
            for j, item_text in enumerate(items):
                iy = item_top + j * item_h
                C.numbered_circle(slide, t, x, iy + 0.02, j + 1, d=0.32)
                itf = textbox(slide, x + 0.44, iy, lw - 0.44, item_h - 0.06, anchor=MSO_ANCHOR.MIDDLE)
                iff = tm.fit_text(item_text, box_w_in=lw - 0.46, box_h_in=item_h - 0.08,
                                  family=t.font_body, max_pt=t.type_scale["body"], min_pt=8, max_lines=3)
                for k, ln in enumerate(iff.lines or [item_text]):
                    p = itf.paragraphs[0] if k == 0 else itf.add_paragraph()
                    C.add_run(p, ln, font=t.font_body, size=iff.pt, color=t.color("ink"))
                if j < len(items) - 1:
                    C.hairline_rule(slide, t, x, iy + item_h - 0.04, lw)

    def _compose_workstream_cards(self, slide: Any, slide_dict: dict[str, Any], r: Rect) -> None:
        """3–6 narrow workstream cards with top-border status + owner badge + body."""
        cards = [c for c in slide_dict.get("workstream_cards", []) if isinstance(c, dict)][:6]
        if not cards:
            return
        t = self.theme
        gut = t.spacing["gutter"] * 0.7
        cols = len(cards)
        cw = (r.w - (cols - 1) * gut) / cols
        statuses = {str(c.get("status", "")).lower() for c in cards if c.get("status")}

        for idx, card in enumerate(cards):
            x = r.x + idx * (cw + gut)
            status = str(card.get("status", "")).lower()
            top_color = t.color(_STATUS_COLOR_MAP.get(status, "primary"))
            add_rect(slide, x, r.y, cw, r.h, fill=t.color("inverse"), line=t.color("hairline"), line_pt=0.5)
            add_rect(slide, x, r.y, cw, 0.06, fill=top_color)

            heading = str(card.get("heading", ""))
            hf = tm.fit_text(heading, box_w_in=cw - 0.2, box_h_in=0.72, family=t.font_header,
                             max_pt=t.type_scale["card_title"], min_pt=8, bold=True, max_lines=2)
            htf = textbox(slide, x + 0.1, r.y + 0.12, cw - 0.2, 0.74)
            for i, ln in enumerate(hf.lines or [heading]):
                p = htf.paragraphs[0] if i == 0 else htf.add_paragraph()
                C.add_run(p, ln, font=t.font_header, size=hf.pt, bold=True, color=t.color("ink"))

            y_cur = r.y + 0.9
            owner = str(card.get("owner", "")).strip()
            if owner:
                C.label_chip(slide, t, x + 0.1, y_cur, owner, fill=t.color("muted"), text_color=t.color("inverse"))
                y_cur += 0.34

            body = str(card.get("body", "")).strip()
            if body:
                rem = r.h - (y_cur - r.y) - 0.1
                if rem > 0.2:
                    bf = tm.fit_text(body, box_w_in=cw - 0.2, box_h_in=rem,
                                     family=t.font_body, max_pt=t.type_scale["body"] - 1, min_pt=7, max_lines=4)
                    btf = textbox(slide, x + 0.1, y_cur, cw - 0.2, rem)
                    for i, ln in enumerate(bf.lines or [body]):
                        p = btf.paragraphs[0] if i == 0 else btf.add_paragraph()
                        C.add_run(p, ln, font=t.font_body, size=bf.pt, color=t.color("muted"))

        if statuses and slide_dict.get("status_legend", True):
            ordered = [s for s in ("live", "in_build", "planned", "partner") if s in statuses]
            legend_items = [(s, s.replace("_", " ").title()) for s in ordered]
            if legend_items:
                C.status_legend(slide, t, r.x, r.y + r.h + 0.08, legend_items)

    def _compose_tower_cards(self, slide: Any, slide_dict: dict[str, Any], r: Rect) -> None:
        """3–5 towers: dark teal header, items with status dots, optional takeaway strip."""
        towers = [tw for tw in slide_dict.get("tower_cards", []) if isinstance(tw, dict)][:5]
        if not towers:
            return
        t = self.theme
        gut = t.spacing["gutter"] * 0.7
        cols = len(towers)
        cw = (r.w - (cols - 1) * gut) / cols
        header_h = 0.52
        takeaway_h = 0.38

        for idx, tower in enumerate(towers):
            x = r.x + idx * (cw + gut)
            add_rect(slide, x, r.y, cw, header_h, fill=t.color("primary"))
            heading = str(tower.get("heading", ""))
            hf = tm.fit_text(heading, box_w_in=cw - 0.16, box_h_in=header_h - 0.08, family=t.font_header,
                             max_pt=t.type_scale["card_title"], min_pt=8, bold=True, max_lines=2)
            htf = textbox(slide, x + 0.08, r.y + 0.04, cw - 0.16, header_h - 0.06)
            for i, ln in enumerate(hf.lines or [heading]):
                p = htf.paragraphs[0] if i == 0 else htf.add_paragraph()
                C.add_run(p, ln, font=t.font_header, size=hf.pt, bold=True, color=t.color("inverse"))

            takeaway = str(tower.get("takeaway", "")).strip()
            item_zone_h = r.h - header_h - (takeaway_h if takeaway else 0) - 0.08
            item_y = r.y + header_h + 0.06
            items = tower.get("items", [])[:6]
            ih = item_zone_h / max(len(items), 1)
            for j, item in enumerate(items):
                iy = item_y + j * ih
                if isinstance(item, dict):
                    status, item_text = str(item.get("status", "")).lower(), str(item.get("text", item.get("label", "")))
                else:
                    status, item_text = "", str(item)
                dot_x = x + 0.08
                tx = x + 0.24 if status else x + 0.1
                tw_val = cw - 0.3 if status else cw - 0.16
                if status:
                    C.status_dot(slide, t, dot_x, iy + 0.03, status)
                iff = tm.fit_text(item_text, box_w_in=tw_val, box_h_in=ih - 0.04, family=t.font_body,
                                  max_pt=t.type_scale["body"] - 1, min_pt=7, max_lines=2)
                itf = textbox(slide, tx, iy, tw_val, ih - 0.04)
                for k, ln in enumerate(iff.lines or [item_text]):
                    p = itf.paragraphs[0] if k == 0 else itf.add_paragraph()
                    C.add_run(p, ln, font=t.font_body, size=iff.pt, color=t.color("ink"))
            if takeaway:
                C.takeaway_strip(slide, t, x, r.y + r.h - takeaway_h, cw, takeaway)

    def _compose_roadmap_matrix(self, slide: Any, slide_dict: dict[str, Any], r: Rect) -> None:
        """Quarter×workstream grid with status-colored cells."""
        data = slide_dict.get("roadmap_matrix", {})
        if not isinstance(data, dict):
            return
        periods = [str(p) for p in data.get("periods", [])][:8]
        tracks = [tr for tr in data.get("tracks", []) if isinstance(tr, dict)][:6]
        if not periods or not tracks:
            return
        t = self.theme
        label_w = 1.25
        col_w = (r.w - label_w) / len(periods)
        row_h = r.h / (len(tracks) + 1)

        # Period header row
        for ci, period in enumerate(periods):
            px = r.x + label_w + ci * col_w
            add_rect(slide, px, r.y, col_w - 0.02, row_h - 0.02, fill=t.color("panel"))
            ptf = textbox(slide, px + 0.04, r.y + 0.04, col_w - 0.1, row_h - 0.1)
            ptf.paragraphs[0].alignment = PP_ALIGN.CENTER
            pf = tm.fit_text(period, box_w_in=col_w - 0.12, box_h_in=row_h - 0.12,
                             family=t.font_header, max_pt=t.type_scale["micro"] + 0.5, min_pt=6, bold=True, max_lines=2)
            C.add_run(ptf.paragraphs[0], period, font=t.font_header, size=pf.pt, bold=True, color=t.color("inverse"))

        for ri, track in enumerate(tracks):
            ry = r.y + (ri + 1) * row_h
            # Alternating row bg
            if ri % 2 == 0:
                add_rect(slide, r.x, ry, r.w, row_h - 0.02, fill=t.color("tint"))
            track_label = str(track.get("label", ""))
            ltf = textbox(slide, r.x + 0.04, ry + 0.04, label_w - 0.08, row_h - 0.08, anchor=MSO_ANCHOR.MIDDLE)
            lf = tm.fit_text(track_label, box_w_in=label_w - 0.1, box_h_in=row_h - 0.1,
                             family=t.font_header, max_pt=t.type_scale["micro"] + 1, min_pt=7, bold=True, max_lines=2)
            C.add_run(ltf.paragraphs[0], track_label, font=t.font_header, size=lf.pt, bold=True, color=t.color("ink"))

            for ci, cell in enumerate(track.get("cells", [])[:len(periods)]):
                if not isinstance(cell, dict):
                    continue
                px = r.x + label_w + ci * col_w
                status = str(cell.get("status", "")).lower()
                fill_color = t.color(_STATUS_COLOR_MAP.get(status, "tint") if status else "tint")
                cell_label = str(cell.get("label", ""))
                add_rect(slide, px + 0.03, ry + 0.04, col_w - 0.07, row_h - 0.1, fill=fill_color)
                if cell_label:
                    ctf = textbox(slide, px + 0.07, ry + 0.08, col_w - 0.14, row_h - 0.18)
                    cff = tm.fit_text(cell_label, box_w_in=col_w - 0.16, box_h_in=row_h - 0.22,
                                      family=t.font_body, max_pt=7, min_pt=5, max_lines=2)
                    text_color = t.color("inverse") if status in {"live", "in_build"} else t.color("ink")
                    C.add_run(ctf.paragraphs[0], cell_label, font=t.font_body, size=cff.pt, color=text_color)

    def _compose_swimlane_timeline(self, slide: Any, slide_dict: dict[str, Any], r: Rect) -> None:
        """Horizontal Gantt — per-lane colored bars spanning period columns."""
        data = slide_dict.get("swimlane_timeline", {})
        if not isinstance(data, dict):
            return
        periods = [str(p) for p in data.get("periods", [])][:8]
        lanes = [l for l in data.get("lanes", []) if isinstance(l, dict)][:6]
        if not periods or not lanes:
            return
        t = self.theme
        label_w = 1.3
        col_w = (r.w - label_w) / len(periods)
        header_h = 0.34
        lane_h = (r.h - header_h) / len(lanes)

        for ci, period in enumerate(periods):
            px = r.x + label_w + ci * col_w
            add_rect(slide, px, r.y, col_w - 0.02, header_h - 0.02, fill=t.color("panel"))
            ptf = textbox(slide, px + 0.03, r.y + 0.04, col_w - 0.08, header_h - 0.08)
            ptf.paragraphs[0].alignment = PP_ALIGN.CENTER
            pf = tm.fit_text(period, box_w_in=col_w - 0.1, box_h_in=header_h - 0.1,
                             family=t.font_header, max_pt=t.type_scale["micro"], min_pt=6, bold=True, max_lines=1)
            C.add_run(ptf.paragraphs[0], period, font=t.font_header, size=pf.pt, bold=True, color=t.color("inverse"))

        for li, lane in enumerate(lanes):
            ly = r.y + header_h + li * lane_h
            if li % 2 == 0:
                add_rect(slide, r.x, ly, r.w, lane_h - 0.02, fill=t.color("tint"))
            lane_label = str(lane.get("label", ""))
            ltf = textbox(slide, r.x + 0.04, ly + 0.04, label_w - 0.08, lane_h - 0.08, anchor=MSO_ANCHOR.MIDDLE)
            lf = tm.fit_text(lane_label, box_w_in=label_w - 0.1, box_h_in=lane_h - 0.1,
                             family=t.font_header, max_pt=t.type_scale["micro"] + 1, min_pt=7, bold=True, max_lines=2)
            C.add_run(ltf.paragraphs[0], lane_label, font=t.font_header, size=lf.pt, bold=True, color=t.color("ink"))

            bar_h = lane_h * 0.52
            bar_y = ly + (lane_h - bar_h) / 2
            for bar in lane.get("bars", []):
                if not isinstance(bar, dict):
                    continue
                start = max(0, min(int(bar.get("start", 0)), len(periods) - 1))
                end = max(start, min(int(bar.get("end", start)), len(periods) - 1))
                status = str(bar.get("status", "")).lower()
                bar_color = t.color(_STATUS_COLOR_MAP.get(status, "primary"))
                bx = r.x + label_w + start * col_w + 0.04
                bw = (end - start + 1) * col_w - 0.08
                add_rect(slide, bx, bar_y, bw, bar_h, fill=bar_color)
                bar_label = str(bar.get("label", "")).strip()
                if bar_label and bw > 0.28:
                    blf = tm.fit_text(bar_label, box_w_in=bw - 0.1, box_h_in=bar_h,
                                      family=t.font_body, max_pt=7, min_pt=5, max_lines=1)
                    bltf = textbox(slide, bx + 0.05, bar_y + 0.04, bw - 0.1, bar_h - 0.08)
                    C.add_run(bltf.paragraphs[0], bar_label, font=t.font_body, size=blf.pt, color=t.color("inverse"))

    def _compose_flagship_cards(self, slide: Any, slide_dict: dict[str, Any], r: Rect) -> None:
        """2–3 flagship cards: dark header, KPI row, body text, optional client badge."""
        cards = [c for c in slide_dict.get("flagship_cards", []) if isinstance(c, dict)][:3]
        if not cards:
            return
        t = self.theme
        gut = t.spacing["gutter"]
        cols = len(cards)
        cw = (r.w - (cols - 1) * gut) / cols
        header_h = 0.9

        for idx, card in enumerate(cards):
            x = r.x + idx * (cw + gut)
            add_rect(slide, x, r.y, cw, header_h, fill=t.color("panel"))
            heading = str(card.get("heading", ""))
            hf = tm.fit_text(heading, box_w_in=cw - 0.24, box_h_in=header_h - 0.12, family=t.font_header,
                             max_pt=t.type_scale["card_title"] + 2, min_pt=10, bold=True, max_lines=2)
            htf = textbox(slide, x + 0.12, r.y + 0.1, cw - 0.24, header_h - 0.14)
            for i, ln in enumerate(hf.lines or [heading]):
                p = htf.paragraphs[0] if i == 0 else htf.add_paragraph()
                C.add_run(p, ln, font=t.font_header, size=hf.pt, bold=True, color=t.color("inverse"))

            add_rect(slide, x, r.y + header_h, cw, r.h - header_h, fill=t.color("inverse"),
                     line=t.color("hairline"), line_pt=0.5)

            y_cur = r.y + header_h + 0.12
            kpis = [k for k in card.get("kpis", []) if isinstance(k, dict)][:3]
            if kpis:
                kpi_w = cw / len(kpis)
                for ki, kpi in enumerate(kpis):
                    kx = x + ki * kpi_w
                    val = str(kpi.get("value", ""))
                    lbl = str(kpi.get("label", ""))
                    if val:
                        vtf = textbox(slide, kx + 0.06, y_cur, kpi_w - 0.12, 0.38)
                        vtf.paragraphs[0].alignment = PP_ALIGN.CENTER
                        C.add_run(vtf.paragraphs[0], val, font=t.font_header,
                                  size=t.type_scale["kicker"] + 2, bold=True, color=t.color("primary"))
                    if lbl:
                        ltf = textbox(slide, kx + 0.06, y_cur + 0.38, kpi_w - 0.12, 0.26)
                        ltf.paragraphs[0].alignment = PP_ALIGN.CENTER
                        C.add_run(ltf.paragraphs[0], lbl, font=t.font_body,
                                  size=t.type_scale["micro"] + 0.5, color=t.color("muted"))
                y_cur += 0.7
                C.hairline_rule(slide, t, x, y_cur, cw)
                y_cur += 0.08

            client = str(card.get("client", "")).strip()
            client_h = 0.28 if client else 0
            body = str(card.get("body", "")).strip()
            body_h = r.h - header_h - (y_cur - (r.y + header_h)) - client_h - 0.1
            if body and body_h > 0.2:
                bf = tm.fit_text(body, box_w_in=cw - 0.24, box_h_in=body_h, family=t.font_body,
                                 max_pt=t.type_scale["body"], min_pt=8, max_lines=4)
                btf = textbox(slide, x + 0.12, y_cur, cw - 0.24, body_h)
                for i, ln in enumerate(bf.lines or [body]):
                    p = btf.paragraphs[0] if i == 0 else btf.add_paragraph()
                    C.add_run(p, ln, font=t.font_body, size=bf.pt, color=t.color("muted"))

            if client:
                ctf = textbox(slide, x + 0.12, r.y + r.h - 0.3, cw - 0.24, 0.26)
                C.add_run(ctf.paragraphs[0], f"TARGET: {client}", font=t.font_body,
                          size=t.type_scale["micro"], bold=True, color=t.color("primary"))
