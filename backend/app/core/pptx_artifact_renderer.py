"""Artifact-tool-style PPTX renderer: composition-based layouts for boardroom-standard executive slides.

Implements compose-first design using grid/row/column abstractions on top of python-pptx.
Supports dynamic text wrapping, balanced layouts, evidence-driven content, and post-render QA.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.text import MSO_AUTO_SIZE, PP_ALIGN
from pptx.util import Inches, Pt

from app.core.pptx_qa import validate_pptx_against_slides
from app.core.evidence_validator import validate_pptx_slides_evidence

logger = logging.getLogger(__name__)

# Canvas dimensions: widescreen 16:9
SLIDE_W = 13.333  # inches
SLIDE_H = 7.5     # inches

# Safe margins (inches)
MARGIN_H = 0.4    # horizontal
MARGIN_V = 0.3    # vertical

# Slide area after margins
CONTENT_W = SLIDE_W - (2 * MARGIN_H)
CONTENT_H = SLIDE_H - (2 * MARGIN_V)

# Typical element heights (inches)
TITLE_H = 0.8
FOOTER_H = 0.5
GUTTER = 0.15     # space between elements


def _hex_to_rgb(raw: str) -> RGBColor:
    """Convert hex color to RGBColor."""
    h = str(raw or "").strip().lstrip("#")
    if len(h) >= 6:
        try:
            return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        except ValueError:
            pass
    return RGBColor(0x86, 0xBC, 0x25)  # Deloitte green


class SlideComposer:
    """Composition-based slide builder using grid/row/column abstractions."""

    def __init__(self, prs: Presentation, branding: dict[str, Any]):
        self.prs = prs
        self.branding = branding
        self.colors = self._build_colors(branding)
        self.font = str(branding.get("font_family", "Calibri"))
        self.header_font = str(branding.get("font_family_header", self.font))
        self.footer_text = self._get_footer(branding)

    def _build_colors(self, b: dict[str, Any]) -> dict[str, RGBColor]:
        """Build color palette from branding."""
        return {
            "primary": _hex_to_rgb(b.get("primary_color", "#86BC25")),
            "secondary": _hex_to_rgb(b.get("secondary_color", "#E8007C")),
            "accent_light": _hex_to_rgb(b.get("accent_light", "#EBF5D3")),
            "accent_dark": _hex_to_rgb(b.get("accent_dark", "#5A8A00")),
            "text_primary": _hex_to_rgb(b.get("text_primary", "#1A1A1A")),
            "text_inverse": _hex_to_rgb(b.get("text_inverse", "#FFFFFF")),
            "neutral_light": _hex_to_rgb(b.get("neutral_light", "#AAAAAA")),
            "neutral_dark": _hex_to_rgb(b.get("neutral_dark", "#1A1A1A")),
        }

    def _get_footer(self, b: dict[str, Any]) -> str:
        """Extract footer text from branding."""
        ft = b.get("footer_text")
        if ft and str(ft).strip():
            return str(ft).strip()
        cn = str(b.get("company_name", "Company")).strip()
        return f"{cn}." if not cn.endswith(".") else cn

    def compose_title_slide(self, slide_dict: dict[str, Any]) -> None:
        """Compose a title/cover slide."""
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[6])  # blank layout
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = self.colors["primary"]

        # Title (centered, large)
        title_box = slide.shapes.add_textbox(
            Inches(MARGIN_H),
            Inches(2.0),
            Inches(CONTENT_W),
            Inches(1.2)
        )
        title_frame = title_box.text_frame
        title_frame.text = slide_dict.get("title", "Title Slide")
        title_frame.paragraphs[0].font.size = Pt(54)
        title_frame.paragraphs[0].font.bold = True
        title_frame.paragraphs[0].font.color.rgb = self.colors["text_inverse"]
        title_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
        title_frame.word_wrap = True

        # Subtitle (centered, smaller)
        subtitle = slide_dict.get("subtitle", "")
        if subtitle:
            subtitle_box = slide.shapes.add_textbox(
                Inches(MARGIN_H),
                Inches(3.3),
                Inches(CONTENT_W),
                Inches(0.8)
            )
            subtitle_frame = subtitle_box.text_frame
            subtitle_frame.text = subtitle
            subtitle_frame.paragraphs[0].font.size = Pt(28)
            subtitle_frame.paragraphs[0].font.color.rgb = self.colors["accent_light"]
            subtitle_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
            subtitle_frame.word_wrap = True

        # Footer
        footer_box = slide.shapes.add_textbox(
            Inches(MARGIN_H),
            Inches(SLIDE_H - MARGIN_V - 0.3),
            Inches(CONTENT_W),
            Inches(0.3)
        )
        footer_frame = footer_box.text_frame
        footer_frame.text = self.footer_text
        footer_frame.paragraphs[0].font.size = Pt(10)
        footer_frame.paragraphs[0].font.color.rgb = self.colors["text_inverse"]

    def compose_content_slide(
        self,
        slide_dict: dict[str, Any],
        slide_type: str,
        page_num: int,
        total_pages: int
    ) -> None:
        """Compose a content slide based on type."""
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[6])

        # Background
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        # Title bar
        self._add_title_bar(slide, slide_dict.get("title", ""))

        # Content area (below title)
        content_y = MARGIN_V + TITLE_H + GUTTER
        content_h = CONTENT_H - TITLE_H - GUTTER - 0.6  # leave room for footer

        # Dispatch to type-specific composer
        handlers = {
            "bullets": self._compose_bullets,
            "stat_cards": self._compose_stat_cards,
            "column_cards": self._compose_column_cards,
            "table": self._compose_table,
            "chart": self._compose_chart,
            "big_number": self._compose_big_number,
            "process_flow": self._compose_process_flow,
            "stack_layers": self._compose_stack_layers,
            "section_divider": self._compose_section_divider,
        }

        handler = handlers.get(slide_type, self._compose_bullets)
        handler(slide, slide_dict, content_y, content_h)

        # Footer
        self._add_footer(slide, page_num, total_pages)

    def _add_title_bar(self, slide: Any, title: str) -> None:
        """Add primary title bar at top of slide."""
        title_box = slide.shapes.add_textbox(
            Inches(MARGIN_H),
            Inches(MARGIN_V),
            Inches(CONTENT_W),
            Inches(TITLE_H)
        )
        title_frame = title_box.text_frame
        title_frame.text = title
        title_frame.paragraphs[0].font.size = Pt(40)
        title_frame.paragraphs[0].font.bold = True
        title_frame.paragraphs[0].font.color.rgb = self.colors["primary"]
        title_frame.paragraphs[0].alignment = PP_ALIGN.LEFT
        title_frame.word_wrap = True
        title_frame.vertical_anchor = 1  # top

    def _add_footer(self, slide: Any, page_num: int, total_pages: int) -> None:
        """Add footer with page number and company branding."""
        footer_box = slide.shapes.add_textbox(
            Inches(MARGIN_H),
            Inches(SLIDE_H - MARGIN_V - 0.25),
            Inches(CONTENT_W),
            Inches(0.25)
        )
        footer_frame = footer_box.text_frame
        footer_frame.text = f"{self.footer_text} | {page_num}/{total_pages}"
        footer_frame.paragraphs[0].font.size = Pt(9)
        footer_frame.paragraphs[0].font.color.rgb = self.colors["neutral_dark"]
        footer_frame.paragraphs[0].alignment = PP_ALIGN.RIGHT

    def _compose_bullets(self, slide: Any, slide_dict: dict[str, Any], y: float, h: float) -> None:
        """Compose bullet-point slide."""
        bullets = slide_dict.get("bullets", [])
        if not bullets:
            return

        bullet_box = slide.shapes.add_textbox(
            Inches(MARGIN_H + 0.2),
            Inches(y),
            Inches(CONTENT_W - 0.4),
            Inches(h)
        )
        text_frame = bullet_box.text_frame
        text_frame.word_wrap = True

        for i, bullet in enumerate(bullets[:8]):  # max 8 bullets
            if i == 0:
                p = text_frame.paragraphs[0]
            else:
                p = text_frame.add_paragraph()

            p.text = str(bullet)
            p.font.size = Pt(18)
            p.font.color.rgb = self.colors["text_primary"]
            p.level = 0
            p.space_before = Pt(6)
            p.space_after = Pt(6)

    def _compose_stat_cards(self, slide: Any, slide_dict: dict[str, Any], y: float, h: float) -> None:
        """Compose 3-column stat cards layout."""
        cards = slide_dict.get("stat_cards", [])
        if not cards:
            return

        cols = 3
        card_w = (CONTENT_W - (2 * (cols - 1) * GUTTER)) / cols
        card_h = min(h * 0.45, 1.8)

        for idx, card in enumerate(cards[:6]):
            col = idx % cols
            row = idx // cols
            x = MARGIN_H + col * (card_w + 2 * GUTTER)
            card_y = y + row * (card_h + GUTTER)

            # Card background
            shape = slide.shapes.add_shape(
                1,  # rectangle
                Inches(x),
                Inches(card_y),
                Inches(card_w),
                Inches(card_h)
            )
            shape.fill.solid()
            shape.fill.fore_color.rgb = self.colors["accent_light"]
            shape.line.color.rgb = self.colors["accent_dark"]

            # Stat value (large)
            stat = str(card.get("stat", ""))
            stat_box = slide.shapes.add_textbox(
                Inches(x + 0.1),
                Inches(card_y + 0.1),
                Inches(card_w - 0.2),
                Inches(card_h * 0.5)
            )
            stat_frame = stat_box.text_frame
            stat_frame.text = stat
            stat_frame.paragraphs[0].font.size = Pt(32)
            stat_frame.paragraphs[0].font.bold = True
            stat_frame.paragraphs[0].font.color.rgb = self.colors["primary"]
            stat_frame.word_wrap = True

            # Label
            label = str(card.get("label", ""))
            label_box = slide.shapes.add_textbox(
                Inches(x + 0.1),
                Inches(card_y + card_h * 0.55),
                Inches(card_w - 0.2),
                Inches(card_h * 0.25)
            )
            label_frame = label_box.text_frame
            label_frame.text = label
            label_frame.paragraphs[0].font.size = Pt(12)
            label_frame.paragraphs[0].font.bold = True
            label_frame.paragraphs[0].font.color.rgb = self.colors["text_primary"]
            label_frame.word_wrap = True

            # Description
            desc = str(card.get("description", ""))
            if desc:
                desc_box = slide.shapes.add_textbox(
                    Inches(x + 0.1),
                    Inches(card_y + card_h * 0.8),
                    Inches(card_w - 0.2),
                    Inches(card_h * 0.18)
                )
                desc_frame = desc_box.text_frame
                desc_frame.text = desc
                desc_frame.paragraphs[0].font.size = Pt(10)
                desc_frame.paragraphs[0].font.color.rgb = self.colors["neutral_dark"]
                desc_frame.word_wrap = True

    def _compose_column_cards(self, slide: Any, slide_dict: dict[str, Any], y: float, h: float) -> None:
        """Compose 3-column card layout."""
        cards = slide_dict.get("column_cards", [])
        if not cards:
            return

        cols = min(3, len(cards))
        card_w = (CONTENT_W - ((cols - 1) * GUTTER)) / cols
        card_h = h

        for idx, card in enumerate(cards[:3]):
            x = MARGIN_H + idx * (card_w + GUTTER)

            # Card background
            shape = slide.shapes.add_shape(
                1,  # rectangle
                Inches(x),
                Inches(y),
                Inches(card_w),
                Inches(card_h)
            )
            shape.fill.solid()
            shape.fill.fore_color.rgb = self.colors["accent_light"]
            shape.line.color.rgb = self.colors["accent_dark"]

            # Heading
            heading = str(card.get("heading", ""))
            heading_box = slide.shapes.add_textbox(
                Inches(x + 0.15),
                Inches(y + 0.15),
                Inches(card_w - 0.3),
                Inches(0.4)
            )
            heading_frame = heading_box.text_frame
            heading_frame.text = heading
            heading_frame.paragraphs[0].font.size = Pt(16)
            heading_frame.paragraphs[0].font.bold = True
            heading_frame.paragraphs[0].font.color.rgb = self.colors["primary"]
            heading_frame.word_wrap = True

            # Body
            body = str(card.get("body", ""))
            body_box = slide.shapes.add_textbox(
                Inches(x + 0.15),
                Inches(y + 0.6),
                Inches(card_w - 0.3),
                Inches(card_h - 0.75)
            )
            body_frame = body_box.text_frame
            body_frame.text = body
            body_frame.paragraphs[0].font.size = Pt(12)
            body_frame.paragraphs[0].font.color.rgb = self.colors["text_primary"]
            body_frame.word_wrap = True

    def _compose_table(self, slide: Any, slide_dict: dict[str, Any], y: float, h: float) -> None:
        """Compose table."""
        table_data = slide_dict.get("table", {})
        if not isinstance(table_data, dict):
            return

        rows = table_data.get("rows", [])
        headers = table_data.get("headers", [])
        if not rows and not headers:
            return

        all_rows = [headers] if headers else []
        all_rows.extend(rows[:10])  # max 11 rows

        cols = max(len(headers) if headers else 0, max(len(r) for r in rows) if rows else 0)
        if cols == 0:
            return

        # Use python-pptx table API
        table_shape = slide.shapes.add_table(
            len(all_rows),
            cols,
            Inches(MARGIN_H + 0.1),
            Inches(y),
            Inches(CONTENT_W - 0.2),
            Inches(h * 0.9)
        ).table

        for row_idx, row in enumerate(all_rows):
            for col_idx, cell_text in enumerate(row[:cols]):
                cell = table_shape.cell(row_idx, col_idx)
                cell.text = str(cell_text or "")
                # Style header row
                if row_idx == 0 and headers:
                    cell.text_frame.paragraphs[0].font.bold = True
                    cell.text_frame.paragraphs[0].font.color.rgb = self.colors["text_inverse"]
                    cell.fill.solid()
                    cell.fill.fore_color.rgb = self.colors["primary"]

    def _compose_chart(self, slide: Any, slide_dict: dict[str, Any], y: float, h: float) -> None:
        """Compose chart."""
        chart_data = slide_dict.get("chart", {})
        if not isinstance(chart_data, dict):
            return

        chart_type_str = chart_data.get("type", "column").lower()
        categories = chart_data.get("categories", [])
        series_data = chart_data.get("series", [])

        if not categories or not series_data:
            return

        # Map type string to XL_CHART_TYPE
        type_map = {
            "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
            "line": XL_CHART_TYPE.LINE,
            "bar": XL_CHART_TYPE.BAR_CLUSTERED,
            "pie": XL_CHART_TYPE.PIE,
            "area": XL_CHART_TYPE.AREA,
        }
        chart_type = type_map.get(chart_type_str, XL_CHART_TYPE.COLUMN_CLUSTERED)

        # Build chart data
        chart_data_obj = CategoryChartData()
        chart_data_obj.categories = categories

        for series in series_data:
            if isinstance(series, dict):
                name = series.get("name", "")
                values = series.get("values", [])
                if name and values:
                    chart_data_obj.add_series(str(name), (tuple(values)))

        # Add chart to slide
        x, cx = Inches(MARGIN_H + 0.2), Inches(CONTENT_W - 0.4)
        y_pos, cy = Inches(y), Inches(h * 0.85)

        try:
            chart_shape = slide.shapes.add_chart(
                chart_type,
                x, y_pos, cx, cy,
                chart_data_obj
            ).chart

            # Style chart
            if hasattr(chart_shape, "has_legend"):
                chart_shape.has_legend = True
        except Exception as e:
            logger.warning("Failed to add chart: %s", e)

    def _compose_big_number(self, slide: Any, slide_dict: dict[str, Any], y: float, h: float) -> None:
        """Compose big-number KPI display."""
        big_number = slide_dict.get("big_number", {})
        if not isinstance(big_number, dict):
            return

        stat = str(big_number.get("stat", ""))
        label = str(big_number.get("label", ""))

        if not stat:
            return

        # Large stat
        stat_box = slide.shapes.add_textbox(
            Inches(MARGIN_H + 0.5),
            Inches(y + 0.5),
            Inches(CONTENT_W - 1),
            Inches(h * 0.5)
        )
        stat_frame = stat_box.text_frame
        stat_frame.text = stat
        stat_frame.paragraphs[0].font.size = Pt(72)
        stat_frame.paragraphs[0].font.bold = True
        stat_frame.paragraphs[0].font.color.rgb = self.colors["primary"]
        stat_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
        stat_frame.word_wrap = True

        # Label
        if label:
            label_box = slide.shapes.add_textbox(
                Inches(MARGIN_H + 0.5),
                Inches(y + h * 0.6),
                Inches(CONTENT_W - 1),
                Inches(h * 0.3)
            )
            label_frame = label_box.text_frame
            label_frame.text = label
            label_frame.paragraphs[0].font.size = Pt(24)
            label_frame.paragraphs[0].font.color.rgb = self.colors["text_primary"]
            label_frame.paragraphs[0].alignment = PP_ALIGN.CENTER

    def _compose_process_flow(self, slide: Any, slide_dict: dict[str, Any], y: float, h: float) -> None:
        """Compose 5-step process flow."""
        steps = slide_dict.get("process_flow", [])
        if not steps:
            return

        steps = steps[:5]
        step_w = (CONTENT_W - ((len(steps) - 1) * GUTTER)) / len(steps)
        step_h = h * 0.6

        for idx, step in enumerate(steps):
            x = MARGIN_H + idx * (step_w + GUTTER)

            # Step box
            shape = slide.shapes.add_shape(
                1,  # rectangle
                Inches(x),
                Inches(y),
                Inches(step_w),
                Inches(step_h)
            )
            shape.fill.solid()
            shape.fill.fore_color.rgb = self.colors["accent_light"]
            shape.line.color.rgb = self.colors["primary"]

            # Step number
            num_box = slide.shapes.add_textbox(
                Inches(x + 0.1),
                Inches(y + 0.1),
                Inches(step_w - 0.2),
                Inches(0.3)
            )
            num_frame = num_box.text_frame
            num_frame.text = f"{idx + 1}"
            num_frame.paragraphs[0].font.size = Pt(18)
            num_frame.paragraphs[0].font.bold = True
            num_frame.paragraphs[0].font.color.rgb = self.colors["primary"]

            # Label
            label = str(step.get("label", ""))
            label_box = slide.shapes.add_textbox(
                Inches(x + 0.1),
                Inches(y + 0.5),
                Inches(step_w - 0.2),
                Inches(step_h - 0.6)
            )
            label_frame = label_box.text_frame
            label_frame.text = label
            label_frame.paragraphs[0].font.size = Pt(11)
            label_frame.paragraphs[0].font.color.rgb = self.colors["text_primary"]
            label_frame.word_wrap = True

            # Arrow connector (skip for last step)
            if idx < len(steps) - 1:
                arrow_x = x + step_w + GUTTER * 0.5
                arrow = slide.shapes.add_shape(
                    33,  # right arrow
                    Inches(arrow_x),
                    Inches(y + step_h * 0.35),
                    Inches(GUTTER * 0.5),
                    Inches(step_h * 0.3)
                )
                arrow.fill.solid()
                arrow.fill.fore_color.rgb = self.colors["primary"]
                arrow.line.color.rgb = self.colors["primary"]

    def _compose_stack_layers(self, slide: Any, slide_dict: dict[str, Any], y: float, h: float) -> None:
        """Compose stacked horizontal layers."""
        layers = slide_dict.get("stack_layers", [])
        if not layers:
            return

        layers = layers[:6]
        layer_h = (h - ((len(layers) - 1) * GUTTER)) / len(layers)

        for idx, layer in enumerate(layers):
            layer_y = y + idx * (layer_h + GUTTER)

            # Layer background
            shape = slide.shapes.add_shape(
                1,  # rectangle
                Inches(MARGIN_H),
                Inches(layer_y),
                Inches(CONTENT_W),
                Inches(layer_h)
            )
            shape.fill.solid()
            shape.fill.fore_color.rgb = self.colors["accent_light"]
            shape.line.color.rgb = self.colors["accent_dark"]

            # Label
            label = str(layer.get("label", ""))
            label_box = slide.shapes.add_textbox(
                Inches(MARGIN_H + 0.15),
                Inches(layer_y + 0.05),
                Inches(CONTENT_W * 0.2),
                Inches(layer_h - 0.1)
            )
            label_frame = label_box.text_frame
            label_frame.text = label
            label_frame.paragraphs[0].font.size = Pt(14)
            label_frame.paragraphs[0].font.bold = True
            label_frame.paragraphs[0].font.color.rgb = self.colors["primary"]
            label_frame.vertical_anchor = 1  # top

            # Description
            desc = str(layer.get("description", ""))
            if desc:
                desc_box = slide.shapes.add_textbox(
                    Inches(MARGIN_H + CONTENT_W * 0.22),
                    Inches(layer_y + 0.05),
                    Inches(CONTENT_W * 0.75),
                    Inches(layer_h - 0.1)
                )
                desc_frame = desc_box.text_frame
                desc_frame.text = desc
                desc_frame.paragraphs[0].font.size = Pt(12)
                desc_frame.paragraphs[0].font.color.rgb = self.colors["text_primary"]
                desc_frame.word_wrap = True

    def _compose_section_divider(self, slide: Any, slide_dict: dict[str, Any], y: float, h: float) -> None:
        """Compose section divider (title-only, dark background)."""
        # Override background
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = self.colors["neutral_dark"]

        # Large title
        title = slide_dict.get("title", "")
        title_box = slide.shapes.add_textbox(
            Inches(MARGIN_H),
            Inches(SLIDE_H * 0.35),
            Inches(CONTENT_W),
            Inches(SLIDE_H * 0.3)
        )
        title_frame = title_box.text_frame
        title_frame.text = title
        title_frame.paragraphs[0].font.size = Pt(48)
        title_frame.paragraphs[0].font.bold = True
        title_frame.paragraphs[0].font.color.rgb = self.colors["text_inverse"]
        title_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
        title_frame.word_wrap = True


def render_pptx_with_artifact_tool(
    payload: dict[str, Any],
    run_dir: Path,
    branding: Any | None = None
) -> dict[str, Any]:
    """Render PPTX using artifact-tool-style composition-based layouts.

    Returns: {
        "status": "success" | "failed",
        "output_path": Path to output.pptx,
        "qa_report": QA validation results,
        "errors": list of error messages,
    }
    """
    output_path = run_dir / "output.pptx"
    errors: list[str] = []

    try:
        # Prepare branding
        branding_dict = _merge_branding_dict(branding) if branding else {}

        # Create presentation
        prs = Presentation()
        prs.slide_width = Inches(SLIDE_W)
        prs.slide_height = Inches(SLIDE_H)

        # Initialize composer
        composer = SlideComposer(prs, branding_dict)

        # Get slides
        pptx_slides = payload.get("pptx_slides", [])
        if not (isinstance(pptx_slides, list) and pptx_slides):
            pptx_slides = [
                {"title": "Process Output", "slide_type": "title", "subtitle": "Generated by ProcessDoc"},
                {
                    "title": "Summary",
                    "slide_type": "bullets",
                    "bullets": ["No detailed slides provided"]
                },
            ]

        # Compose slides
        total_slides = len(pptx_slides)
        for idx, slide_dict in enumerate(pptx_slides[:20]):  # max 20 slides
            if not isinstance(slide_dict, dict):
                errors.append(f"Slide {idx + 1}: Invalid slide data structure")
                continue

            slide_type = str(slide_dict.get("slide_type", "bullets")).lower()

            try:
                if slide_type == "title":
                    composer.compose_title_slide(slide_dict)
                else:
                    composer.compose_content_slide(
                        slide_dict,
                        slide_type,
                        idx + 1,
                        total_slides
                    )
            except Exception as e:
                errors.append(f"Slide {idx + 1} ({slide_type}): {str(e)}")
                logger.warning("Failed to compose slide %d: %s", idx + 1, e)

        # Save PPTX
        prs.save(str(output_path))
        logger.info("PPTX rendered: %s", output_path)

        # Run QA validation
        qa_report = validate_pptx_against_slides(output_path, pptx_slides)

        # Run evidence validation (advisory only, does not block rendering)
        process_model = payload.get("process_model")
        evidence_report = validate_pptx_slides_evidence(pptx_slides, process_model)
        qa_report["evidence"] = evidence_report

        # Log unsupported claims as warnings (advisory)
        if evidence_report.get("unsupported_claims_count", 0) > 0:
            logger.warning(
                "Evidence validation: %d unsupported claims found (advisory only). %s",
                evidence_report["unsupported_claims_count"],
                evidence_report.get("summary", "")
            )

        # Store QA report
        qa_path = run_dir / "pptx_render_quality.json"
        qa_path.write_text(json.dumps(qa_report, indent=2), encoding="utf-8")

        return {
            "status": "success" if qa_report["status"] == "pass" else "failed",
            "output_path": output_path,
            "qa_report": qa_report,
            "errors": errors,
        }

    except Exception as e:
        logger.error("Fatal error rendering PPTX: %s", e, exc_info=True)
        errors.append(f"Fatal: {str(e)}")
        return {
            "status": "failed",
            "output_path": None,
            "qa_report": {
                "status": "fail",
                "summary": f"Renderer crashed: {str(e)}",
                "issues": [str(e)],
            },
            "errors": errors,
        }


def _merge_branding_dict(branding: Any) -> dict[str, Any]:
    """Normalize branding to flat dict (same as original renderer)."""
    if branding is None:
        return {}
    if isinstance(branding, dict):
        return {
            "primary_color": str(branding.get("primary_color", "#86BC25")),
            "secondary_color": str(
                branding.get("secondary_color", branding.get("complementary_color", "#E8007C"))
            ),
            "accent_light": str(branding.get("accent_light", "#EBF5D3")),
            "accent_dark": str(branding.get("accent_dark", "#5A8A00")),
            "font_family": str(branding.get("font_family", "Calibri")),
            "font_family_header": str(branding.get("font_family_header", "Calibri Light")),
            "company_name": str(branding.get("company_name", "Deloitte")),
            "footer_text": branding.get("footer_text", branding.get("custom_footer_text")),
            "neutral_light": str(branding.get("neutral_light", "#AAAAAA")),
            "neutral_dark": str(branding.get("neutral_dark", "#1A1A1A")),
            "text_primary": str(branding.get("text_primary", "#1A1A1A")),
            "text_inverse": str(branding.get("text_inverse", "#FFFFFF")),
        }
    # Fallback for dataclass-like objects
    return {}
