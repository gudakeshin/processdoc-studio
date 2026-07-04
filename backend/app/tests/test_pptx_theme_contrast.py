"""Contrast invariants for the resolved themes.

Regression guard for the editorial-deck defect where body/supporting text rendered
in the near-white brand ``neutral_light`` (#E5E5E5) on a white slide and was
effectively invisible. The ``muted`` role (used for all secondary text) must clear
WCAG AA against the page, regardless of what light neutral the brand supplies.
"""
from __future__ import annotations

import pytest

from app.core.doc_theme import resolve_doc_theme
from app.core.pptx_theme import contrast_ratio, resolve_theme

# The Deloitte palette that triggered the bug: neutral_light is near-white.
_BRAND = {
    "primary_color": "#86BC24",
    "text_primary": "#1A1A1A",
    "text_inverse": "#FFFFFF",
    "neutral_light": "#E5E5E5",
    "neutral_dark": "#1F2426",
    "accent_light": "#EBF5D3",
    "accent_dark": "#5A8A00",
    "font_family": "Calibri",
    "company_name": "Deloitte",
}

_AA = 4.5  # WCAG AA for normal text


@pytest.mark.parametrize("theme_name", ["editorial", "classic"])
def test_deck_muted_is_readable_on_white(theme_name: str) -> None:
    t = resolve_theme(_BRAND, theme_name)
    assert contrast_ratio(t.color("muted"), t.color("inverse")) >= _AA
    # The near-white brand neutral is preserved for fills/dividers, not used as text.
    assert t.color("neutral_light").upper() == "#E5E5E5"
    assert t.color("muted").upper() != "#E5E5E5"


def test_doc_muted_is_readable_on_white() -> None:
    dt = resolve_doc_theme(_BRAND)
    assert contrast_ratio(dt.color("muted"), dt.color("inverse")) >= _AA


def test_readable_floor_snaps_low_contrast_role() -> None:
    t = resolve_theme(_BRAND, "editorial")
    # A deliberately illegible role (light on white) is snapped to ink/inverse.
    t.colors["bogus"] = "#F2F2F2"
    snapped = t.readable("bogus", on="#FFFFFF")
    assert contrast_ratio(snapped, "#FFFFFF") >= _AA
    # A role that already passes is returned unchanged.
    assert t.readable("ink", on="#FFFFFF") == t.color("ink")
