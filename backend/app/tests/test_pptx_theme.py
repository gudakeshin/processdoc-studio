"""Phase 1 — deck theme tokens.

Pins that the ``classic`` theme reproduces the original SlideComposer constants
(so the default render is unchanged) and that the ``editorial`` theme exposes the
reference design language. Also covers brand/topic colour resolution and the
flag-aware theme-name resolver.
"""

from __future__ import annotations

from app.core.pptx_theme import resolve_theme, resolve_theme_name

_DELOITTE = {
    "primary_color": "#86BC25",
    "accent_light": "#EBF5D3",
    "accent_dark": "#5A8A00",
    "text_primary": "#1A1A1A",
    "text_inverse": "#FFFFFF",
    "neutral_light": "#AAAAAA",
    "neutral_dark": "#1A1A1A",
    "font_family": "Calibri",
}


def test_classic_theme_matches_original_constants() -> None:
    t = resolve_theme(_DELOITTE, "classic")
    assert t.name == "classic"
    # Type scale lifted verbatim from SlideComposer.
    assert t.type_scale["cover_title"] == 54.0
    assert t.type_scale["cover_subtitle"] == 28.0
    assert t.type_scale["title_plain"] == 40.0
    assert t.type_scale["title_with_eyebrow"] == 28.0
    assert t.type_scale["eyebrow"] == 11.0
    assert t.type_scale["footer"] == 9.0
    # Spacing grid verbatim.
    assert t.spacing["margin_h"] == 0.4
    assert t.spacing["margin_v"] == 0.3
    assert t.spacing["gutter"] == 0.15
    assert t.spacing["title_h"] == 0.8
    # Classic keeps the green top bar, no border frame.
    assert t.chrome["top_bar"] is True
    assert t.chrome["border"] is False


def test_classic_primary_is_brand_primary() -> None:
    t = resolve_theme(_DELOITTE, "classic")
    assert t.color("primary").upper() == "#86BC25"
    assert t.color("ink").upper() == "#1A1A1A"
    assert t.color("inverse").upper() == "#FFFFFF"


def test_editorial_theme_chrome_and_scale() -> None:
    t = resolve_theme(_DELOITTE, "editorial")
    assert t.name == "editorial"
    # Editorial swaps the green bar for a border frame + CONFIDENTIAL footer.
    assert t.chrome["border"] is True
    assert t.chrome["top_bar"] is False
    assert "CONFIDENTIAL" in t.chrome["footer_right_template"]
    # Editorial has an assertion headline + italic kicker scale.
    assert t.type_scale["headline"] >= 30.0
    assert "kicker" in t.type_scale
    assert "eyebrow" in t.type_scale
    # Charcoal panel + light primary tint wash.
    assert t.color("panel").upper() == "#1F2426"
    assert t.color("tint").upper() != "#1F2426"


def test_editorial_status_colors_are_semantic_and_distinct() -> None:
    t = resolve_theme(_DELOITTE, "editorial")
    live = t.status_color("live")
    in_build = t.status_color("in_build")
    planned = t.status_color("planned")
    partner = t.status_color("partner")
    # live reads on-brand; the others are the reference's orange/blue/gold.
    assert live.upper() == "#86BC25"
    assert in_build.upper() == "#E1610E"
    assert planned.upper() == "#1F6FEB"
    assert partner.upper() == "#B08D3F"
    assert len({live, in_build, planned, partner}) == 4


def test_topic_palette_swaps_primary_not_structure() -> None:
    # A finance topic palette override (maroon) flows into the editorial primary
    # while the editorial chrome/scale stay intact.
    finance = dict(_DELOITTE, primary_color="#990011", accent_light="#FCF6F5", accent_dark="#7A0010")
    t = resolve_theme(finance, "editorial")
    assert t.color("primary").upper() == "#990011"
    assert t.chrome["border"] is True  # structure unchanged


def test_resolve_theme_name_flag_and_override() -> None:
    # Unset deck_theme: follows the config flag.
    assert resolve_theme_name({}, editorial_default=False) == "classic"
    assert resolve_theme_name({}, editorial_default=True) == "editorial"
    # Explicit override always wins over the flag.
    assert resolve_theme_name({"deck_theme": "classic"}, editorial_default=True) == "classic"
    assert resolve_theme_name({"deck_theme": "editorial"}, editorial_default=False) == "editorial"
    # Unknown name degrades to the flag default.
    assert resolve_theme_name({"deck_theme": "bogus"}, editorial_default=False) == "classic"


def test_unknown_theme_name_degrades_to_classic() -> None:
    t = resolve_theme(_DELOITTE, "does-not-exist")
    assert t.name == "classic"
