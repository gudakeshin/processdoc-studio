"""Document design-token layer for DOCX and XLSX renderers.

``DocTheme`` is the DOCX/XLSX analogue of ``pptx_theme.DeckTheme``: a single
source of typography scale and semantic colour roles, resolved from branding and
the topic palette. Both the DOCX and XLSX composers consume a ``DocTheme`` so the
two formats stay on-brand and on-topic in lockstep with PPTX.

Colours are resolved from the flat branding dict (via the shared
``_merge_branding_dict``) and then topic-adjusted (via ``apply_topic_palette``),
exactly like the deck themes — a topic palette swaps the primary hue rather than
replacing the theme.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.pptx_theme import _mix, _norm_hex, _readable_secondary
from app.core.topic_palette import apply_topic_palette


# Type scale in points — covers the headings and body text both formats render.
_TYPE_SCALE = {
    "cover_title": 28.0,
    "cover_subtitle": 14.0,
    "h1": 18.0,
    "h2": 15.0,
    "h3": 13.0,
    "h4": 11.0,
    "body": 10.0,
    "caption": 8.0,
}


@dataclass
class DocTheme:
    name: str
    font_body: str
    font_header: str
    # role -> hex (with leading '#')
    colors: dict[str, str]
    # role -> pt
    type_scale: dict[str, float]
    company_name: str = "Deloitte"

    def color(self, role: str, default: str = "#1A1A1A") -> str:
        return self.colors.get(role, default)

    def rgb(self, role: str, default: str = "#1A1A1A") -> tuple[int, int, int]:
        """Return an (r, g, b) tuple for a colour role — handy for python-docx RGBColor."""
        h = self.color(role, default).lstrip("#")
        if len(h) != 6:
            h = default.lstrip("#")
        try:
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except ValueError:
            return 0x1A, 0x1A, 0x1A

    def hex6(self, role: str, default: str = "#1A1A1A") -> str:
        """Return a 6-char uppercase hex (no '#') — the form openpyxl fills expect."""
        h = self.color(role, default).lstrip("#").upper()
        return h if len(h) == 6 else default.lstrip("#").upper()

    def pt(self, role: str, default: float = 10.0) -> float:
        return float(self.type_scale.get(role, default))


def _resolve_colors(b: dict) -> dict[str, str]:
    """Map a flat branding dict into the colour roles DOCX/XLSX share."""
    primary = _norm_hex(b.get("primary_color"), "#86BC25")
    secondary = _norm_hex(b.get("secondary_color"), "#E8007C")
    accent_light = _norm_hex(b.get("accent_light"), "#EBF5D3")
    accent_dark = _norm_hex(b.get("accent_dark"), "#5A8A00")
    ink = _norm_hex(b.get("text_primary"), "#1A1A1A")
    inverse = _norm_hex(b.get("text_inverse"), "#FFFFFF")
    neutral_light = _norm_hex(b.get("neutral_light"), "#AAAAAA")
    neutral_dark = _norm_hex(b.get("neutral_dark"), "#1A1A1A")
    return {
        "primary": primary,
        "secondary": secondary,
        "accent": accent_dark,
        "accent_dark": accent_dark,
        "accent_light": accent_light,
        "tint": _mix(primary, "#FFFFFF", 0.90),  # very light primary wash for banded rows
        "ink": ink,
        "inverse": inverse,
        # Readable secondary-text grey, not the near-white brand neutral (which is
        # illegible on a white page); keep neutral_light for fills/dividers.
        "muted": _readable_secondary(ink, inverse),
        "neutral_light": neutral_light,
        "panel": neutral_dark,
        "hairline": _mix(ink, inverse, 0.82),
    }


def resolve_doc_theme(branding, process_name: str | None = None) -> DocTheme:
    """Build a ``DocTheme`` from branding (object/dict/None) and an optional topic name."""
    # Imported lazily to avoid a circular import (deliverable_pptx imports topic_palette).
    from app.core.deliverable_pptx import _merge_branding_dict

    brand = _merge_branding_dict(branding)
    brand = apply_topic_palette(brand, process_name or "")
    return DocTheme(
        name="doc",
        font_body=str(brand.get("font_family") or "Calibri"),
        font_header=str(brand.get("font_family_header") or brand.get("font_family") or "Calibri"),
        colors=_resolve_colors(brand),
        type_scale=dict(_TYPE_SCALE),
        company_name=str(brand.get("company_name") or "Deloitte"),
    )
