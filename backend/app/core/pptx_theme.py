"""Deck design-token layer.

A ``DeckTheme`` is the single source of typography scale, spacing grid, chrome
spec, and semantic colour roles for a rendered deck. Two themes are registered:

* ``classic`` — values lifted verbatim from the original ``SlideComposer`` so the
  default render is byte-for-byte unchanged.
* ``editorial`` — the typography-led consulting language (eyebrow + assertion
  headline + italic kicker, thin border frame, ``CONFIDENTIAL · nn / NN`` footer,
  semantic status colours).

Colours are *resolved from branding* for both themes, so ``BrandingContext``,
the brand-level hierarchy, and ``_pick_topic_palette`` keep working: a topic
palette swaps the primary hue inside the theme rather than replacing the theme.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Semantic status colours (the reference deck's portfolio legend). ``live`` is
# intentionally absent — it maps to the brand primary so status reads on-brand.
_STATUS_IN_BUILD = "#E1610E"  # orange
_STATUS_PLANNED = "#1F6FEB"   # blue
_STATUS_PARTNER = "#B08D3F"   # gold

_EDITORIAL_PANEL = "#1F2426"  # near-black charcoal


def _norm_hex(raw: str, default: str) -> str:
    v = str(raw or "").strip()
    if not v:
        return default
    if not v.startswith("#"):
        v = f"#{v}"
    return v[:7]


def _mix(hex_a: str, hex_b: str, t: float) -> str:
    """Linear blend of two hex colours; t=0 -> a, t=1 -> b."""
    def comp(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    ar, ag, ab = comp(hex_a)
    br, bg, bb = comp(hex_b)
    r = round(ar + (br - ar) * t)
    g = round(ag + (bg - ag) * t)
    b = round(ab + (bb - ab) * t)
    return f"#{r:02X}{g:02X}{b:02X}"


@dataclass
class DeckTheme:
    name: str
    font_body: str
    font_header: str
    # role -> hex
    colors: dict[str, str]
    # role -> pt
    type_scale: dict[str, float]
    # inches unless noted
    spacing: dict[str, float]
    chrome: dict[str, Any] = field(default_factory=dict)

    def color(self, role: str, default: str = "#1A1A1A") -> str:
        return self.colors.get(role, default)

    def status_color(self, status: str) -> str:
        s = (status or "").strip().lower()
        if s in ("live", "done", "complete"):
            return self.colors["primary"]
        if s in ("in_build", "building", "wip"):
            return self.colors["status_in_build"]
        if s in ("planned", "todo", "next"):
            return self.colors["status_planned"]
        if s in ("partner", "external"):
            return self.colors["status_partner"]
        return self.colors["muted"]


# --- classic theme: verbatim port of SlideComposer constants ----------------

_CLASSIC_TYPE_SCALE = {
    "cover_title": 54.0,
    "cover_subtitle": 28.0,
    "cover_badges": 14.0,
    "title_plain": 40.0,
    "title_with_eyebrow": 28.0,
    "eyebrow": 11.0,
    "body": 14.0,
    "footer": 9.0,
}

_CLASSIC_SPACING = {
    "margin_h": 0.4,
    "margin_v": 0.3,
    "gutter": 0.15,
    "title_h": 0.8,
    "footer_h": 0.5,
}


# --- editorial theme: the reference design language -------------------------

_EDITORIAL_TYPE_SCALE = {
    "display": 50.0,       # cover / divider hero
    "cover_subtitle": 20.0,
    "headline": 34.0,      # assertion title (wraps to <= 2 lines)
    "kicker": 18.0,        # italic sub-headline
    "eyebrow": 11.0,       # ALL-CAPS section label
    "micro": 8.5,          # OWNER / TARGET CLIENT
    "body": 13.0,
    "card_title": 14.0,
    "stat_value": 40.0,
    "footer": 9.0,
}

_EDITORIAL_SPACING = {
    "margin_h": 0.62,
    "margin_v": 0.5,
    "gutter": 0.22,
    "title_h": 1.55,       # eyebrow + 2-line headline + kicker block
    "footer_h": 0.4,
    "hairline_pt": 0.75,
    "border_inset": 0.0,   # frame hugs the slide edge (thin top accent + footer rule)
    "border_pt": 3.0,      # top accent bar weight
    "letter_spacing": 2.2, # pt of tracking for eyebrow/micro labels
}


def _resolve_brand_colors(b: dict[str, Any]) -> dict[str, str]:
    """Map the flat branding dict into the colour roles both themes share."""
    primary = _norm_hex(b.get("primary_color"), "#86BC25")
    ink = _norm_hex(b.get("text_primary"), "#1A1A1A")
    inverse = _norm_hex(b.get("text_inverse"), "#FFFFFF")
    accent_light = _norm_hex(b.get("accent_light"), "#EBF5D3")
    accent_dark = _norm_hex(b.get("accent_dark"), "#5A8A00")
    neutral_light = _norm_hex(b.get("neutral_light"), "#AAAAAA")
    neutral_dark = _norm_hex(b.get("neutral_dark"), "#1A1A1A")
    return {
        "primary": primary,
        "accent": accent_dark,
        "ink": ink,
        "inverse": inverse,
        "tint": accent_light,
        "muted": neutral_light,
        "panel": neutral_dark,
        "hairline": _mix(ink, inverse, 0.82),  # very light grey rule
        "status_in_build": _STATUS_IN_BUILD,
        "status_planned": _STATUS_PLANNED,
        "status_partner": _STATUS_PARTNER,
    }


def _classic_theme(b: dict[str, Any]) -> DeckTheme:
    colors = _resolve_brand_colors(b)
    return DeckTheme(
        name="classic",
        font_body=str(b.get("font_family", "Calibri")),
        font_header=str(b.get("font_family_header", b.get("font_family", "Calibri"))),
        colors=colors,
        type_scale=dict(_CLASSIC_TYPE_SCALE),
        spacing=dict(_CLASSIC_SPACING),
        chrome={"top_bar": True, "border": False, "cover": "deloitte_strips"},
    )


def _editorial_theme(b: dict[str, Any]) -> DeckTheme:
    colors = _resolve_brand_colors(b)
    # Editorial uses a charcoal panel and a primary-tinted background wash.
    colors["panel"] = _EDITORIAL_PANEL
    colors["tint"] = _mix(colors["primary"], "#FFFFFF", 0.90)
    colors["hairline"] = _mix("#000000", "#FFFFFF", 0.86)
    return DeckTheme(
        name="editorial",
        font_body=str(b.get("font_family", "Calibri")),
        font_header=str(b.get("font_family_header", b.get("font_family", "Calibri"))),
        colors=colors,
        type_scale=dict(_EDITORIAL_TYPE_SCALE),
        spacing=dict(_EDITORIAL_SPACING),
        chrome={
            "top_bar": False,
            "border": True,
            "cover": "editorial_metadata_band",
            "footer_left_template": "{deck_label}",
            "footer_right_template": "CONFIDENTIAL · {nn} / {NN}",
        },
    )


_THEME_BUILDERS = {
    "classic": _classic_theme,
    "editorial": _editorial_theme,
}


def resolve_theme_name(branding_dict: dict[str, Any] | None, *, editorial_default: bool) -> str:
    """Pick the effective theme: explicit deck_theme wins, else the config default.

    ``editorial_default`` is the value of ``settings.pptx_editorial_theme_enabled``.
    An unset/blank deck_theme resolves to "editorial" when the flag is on, else
    "classic". Unknown names degrade to "classic".
    """
    explicit = str((branding_dict or {}).get("deck_theme") or "").strip().lower()
    if explicit in _THEME_BUILDERS:
        return explicit
    return "editorial" if editorial_default else "classic"


def resolve_theme(branding_dict: dict[str, Any] | None, theme_name: str | None) -> DeckTheme:
    """Build the named theme from a flat branding dict (defaults to ``classic``)."""
    name = (theme_name or "classic").strip().lower()
    builder = _THEME_BUILDERS.get(name, _classic_theme)
    return builder(branding_dict or {})
