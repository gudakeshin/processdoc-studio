"""Topic-aware colour palette selection, shared across deliverable renderers.

A process name like "Carbon Tax Audit" or "Cloud Migration" carries a topic
signal. When branding is left at the default Deloitte chrome, that signal is used
to swap the *primary hue* (finance→burgundy, technology→blue, …) so the rendered
artifact reads on-topic instead of generic green. Custom-branded runs are left
untouched.

This logic previously lived (duplicated) inside ``deliverable_pptx.py`` and
``pptx_artifact_renderer.py``; it is now the single source consumed by PPTX, DOCX,
and XLSX renderers via ``doc_theme.resolve_doc_theme``.
"""

from __future__ import annotations

import re

# The Deloitte default primary; topic palettes only override this exact value so
# any custom brand colour is preserved verbatim.
DEFAULT_PRIMARY = "#86BC25"

_TOPIC_PALETTES: list[tuple[tuple[str, ...], dict[str, str]]] = [
    # (keyword triggers, palette overrides matching SKILL.md palette table)
    (("finance", "cfo", "audit", "tax", "treasury", "accounting", "close", "record"),
     {"primary_color": "#990011", "accent_light": "#FCF6F5", "accent_dark": "#7A0010"}),
    (("technology", "digital", "data", "ai", "cloud", "cyber", "it ", "iot", "platform"),
     {"primary_color": "#065A82", "accent_light": "#C6E2F0", "accent_dark": "#1C7293"}),
    (("people", "hr", "talent", "culture", "workforce", "learning", "change"),
     {"primary_color": "#6D2E46", "accent_light": "#ECE2D0", "accent_dark": "#A26769"}),
    (("sustainability", "esg", "environment", "climate", "green", "carbon", "energy"),
     {"primary_color": "#2C5F2D", "accent_light": "#D8EED8", "accent_dark": "#97BC62"}),
    # Default: operations / process / supply / procurement keep Deloitte chrome unchanged.
]


def pick_topic_palette(process_name: str) -> dict[str, str]:
    """Return palette overrides for a topic-matched process name, or {} to keep defaults.

    Uses word-boundary matching (avoids "ai" inside "sustainability"/"chain") and
    picks the palette with the highest keyword-hit count so that ambiguous names
    like "Carbon Tax Audit" resolve to the palette with the most evidence (finance:
    "tax"+"audit"=2 > ESG: "carbon"=1) rather than whichever palette comes first.
    """
    lowered = (process_name or "").lower()
    best_overrides: dict[str, str] = {}
    best_count = 0
    for keywords, overrides in _TOPIC_PALETTES:
        count = sum(
            1 for kw in keywords
            if re.search(r"\b" + re.escape(kw.strip()) + r"\b", lowered)
        )
        if count > best_count:
            best_count = count
            best_overrides = overrides
    return best_overrides


def apply_topic_palette(brand: dict, process_name: str) -> dict:
    """Merge topic-palette overrides into a flat branding dict, in place and returned.

    Only applies when ``primary_color`` is still the default Deloitte green — a
    custom brand colour signals the customer's identity and is never overridden.
    Mirrors the gate the PPTX renderer has always used.
    """
    if not isinstance(brand, dict):
        return brand
    primary = str(brand.get("primary_color") or "").strip().upper()
    if primary and primary != DEFAULT_PRIMARY.upper():
        return brand
    overrides = pick_topic_palette(process_name)
    if overrides:
        brand.update(overrides)
    return brand
