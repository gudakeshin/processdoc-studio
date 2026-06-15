"""Phase 2 — editorial composer + component library.

Renders a deck in the editorial theme and asserts the reference design language
(border frame, CONFIDENTIAL footer, two-tone headline, letterspaced eyebrow) is
present, and that the classic theme is byte-for-byte unchanged (green top bar).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from pptx import Presentation
from pptx.util import Emu, Inches

from app.core.pptx_artifact_renderer import render_pptx_with_artifact_tool

_SLIDES = [
    {
        "slide_type": "title", "title": "Agentic AI for Enterprise Finance",
        "emphasis": "Enterprise Finance", "eyebrow": "INDIA · FINANCE TRANSFORMATION",
        "subtitle": "A coordinated operating plan.",
        "metadata": {"PREPARED FOR": "MD & SP", "HORIZON": "5 quarters", "DATE": "Q2 2026"},
    },
    {
        "slide_type": "stat_cards", "title": "The asset portfolio.", "subtitle": "THE PRACTICE",
        "kicker": "Thirty-three agents across the value chain.",
        "stat_cards": [
            {"stat": "33", "label": "Use cases", "description": "Five towers", "fill": "green"},
            {"stat": "6", "label": "Workstreams", "description": "In parallel", "fill": "dark"},
            {"stat": "5", "label": "Quarters", "description": "By ROI", "fill": "gray"},
        ],
    },
    {
        "slide_type": "column_cards", "title": "Three modes.", "subtitle": "WHERE WE PLAY",
        "section_number": "02",
        "column_cards": [
            {"heading": "Build", "body": "Proprietary IP.", "accent": "green"},
            {"heading": "Deploy", "body": "Monetise assets.", "accent": "dark"},
            {"heading": "Partner", "body": "Protect margin.", "accent": "gray"},
        ],
    },
    {
        "slide_type": "bullets", "title": "Six workstreams. One build.", "subtitle": "THE PLAN",
        "bullets": ["Hiring starts now.", "Kit and GTM in parallel.", "Delivery sustains."],
    },
    {"slide_type": "section_divider", "title": "The build begins now.", "emphasis": "now.", "subtitle": "DELOITTE"},
]


def _render(theme: str, slides: list[dict[str, Any]] | None = None) -> Presentation:
    payload = {
        "requested_outputs": ["pptx"],
        "pptx_slides": slides or _SLIDES,
        "process_model": {"process_name": "Finance Transformation", "steps": [], "roles": []},
    }
    branding = {
        "primary_color": "#0E7C7B", "company_name": "Deloitte",
        "footer_text": "Finance Transformation", "deck_theme": theme,
    }
    d = Path(tempfile.mkdtemp())
    res = render_pptx_with_artifact_tool(payload, d, branding)
    assert res["status"] == "success", res.get("errors")
    assert not res["errors"], res["errors"]
    return Presentation(str(res["output_path"]))


def _all_text(slide: Any) -> str:
    out = []
    for sh in slide.shapes:
        if sh.has_text_frame:
            out.append(sh.text_frame.text)
    return "\n".join(out)


def _solid_fill_hex(shape: Any) -> str | None:
    try:
        if shape.fill.type is not None:
            return str(shape.fill.fore_color.rgb)
    except Exception:
        return None
    return None


def test_editorial_renders_every_type_without_errors() -> None:
    prs = _render("editorial")
    assert len(prs.slides) == len(_SLIDES)


def test_editorial_content_slide_has_no_green_topbar() -> None:
    prs = _render("editorial")
    content = prs.slides[1]  # stat_cards
    # Classic chrome = a full-width ~0.12in primary bar pinned at the very top.
    for sh in content.shapes:
        if sh.top is not None and sh.top <= Emu(Inches(0.05)) and sh.width and sh.width >= Emu(Inches(12)):
            h = sh.height or 0
            if h <= Emu(Inches(0.2)):
                # Must NOT be the green top bar; the editorial frame is an outline (no solid fill).
                assert _solid_fill_hex(sh) is None, "editorial slide should not paint a top bar"


def test_editorial_border_frame_present() -> None:
    prs = _render("editorial")
    content = prs.slides[1]
    # A near-full-bleed rectangle with no solid fill (the perimeter outline).
    found = False
    for sh in content.shapes:
        if (sh.width and sh.width >= Emu(Inches(12.5)) and sh.height and sh.height >= Emu(Inches(6.8))):
            found = True
    assert found, "expected an editorial border frame rectangle"


def test_editorial_footer_is_confidential_paged() -> None:
    prs = _render("editorial")
    text = _all_text(prs.slides[1])
    assert "CONFIDENTIAL" in text.upper()
    assert "/ 05" in text or "/ 5" in text  # nn / NN page cadence


def test_cover_headline_is_two_tone() -> None:
    prs = _render("editorial")
    cover = prs.slides[0]
    multi_run = False
    for sh in cover.shapes:
        if sh.has_text_frame and "Agentic AI for" in sh.text_frame.text:
            for p in sh.text_frame.paragraphs:
                if len([r for r in p.runs if r.text]) >= 2:
                    multi_run = True
    assert multi_run, "cover headline should split into >=2 runs for two-tone emphasis"


def test_eyebrow_has_letter_spacing() -> None:
    prs = _render("editorial")
    # At least one run carries the OOXML spc tracking attribute.
    spc_found = False
    for slide in prs.slides:
        for sh in slide.shapes:
            if not sh.has_text_frame:
                continue
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    rpr = r._r.find("{http://schemas.openxmlformats.org/drawingml/2006/main}rPr")
                    if rpr is not None and rpr.get("spc"):
                        spc_found = True
    assert spc_found, "expected letterspaced (spc) runs in editorial chrome"


_PHASE3_SLIDES = [
    {
        "slide_type": "split_panel", "title": "Six levers.", "subtitle": "THE APPROACH",
        "left_label": "Transform now.",
        "items": [
            {"label": "Talent", "body": "Hire senior AI engineers by Q2."},
            {"label": "Platform", "body": "Consolidate on a single inference endpoint."},
            {"label": "Governance", "body": "Establish a model risk committee."},
        ],
    },
    {
        "slide_type": "lanes", "title": "Three horizons.", "subtitle": "BUILD PLAN",
        "lanes": [
            {"label": "Horizon 1", "items": ["Define scope", "Secure budget", "Hire leads"]},
            {"label": "Horizon 2", "items": ["Pilot deployments", "Measure impact", "Scale winners"]},
            {"label": "Horizon 3", "items": ["Enterprise roll-out", "Partner ecosystem", "IP monetise"]},
        ],
    },
    {
        "slide_type": "workstream_cards", "title": "Six workstreams.", "subtitle": "DELIVERY",
        "status_legend": True,
        "workstream_cards": [
            {"heading": "AI Engineering", "owner": "CTO", "body": "Core platform build.", "status": "live"},
            {"heading": "Data", "owner": "CDO", "body": "Unified data layer.", "status": "in_build"},
            {"heading": "GTM", "owner": "CMO", "body": "Go-to-market motion.", "status": "planned"},
            {"heading": "Risk", "owner": "CRO", "body": "Model governance.", "status": "partner"},
        ],
    },
    {
        "slide_type": "tower_cards", "title": "Five towers.", "subtitle": "PORTFOLIO",
        "tower_cards": [
            {"heading": "Finance", "items": [{"text": "AP automation", "status": "live"}, {"text": "Close acceleration", "status": "in_build"}], "takeaway": "£1.2M identified."},
            {"heading": "Procurement", "items": ["Vendor scoring", "Contract mining"], "takeaway": "12% savings."},
            {"heading": "HR", "items": ["Resume screening", "Offer generation"], "takeaway": "40% faster."},
        ],
    },
    {
        "slide_type": "roadmap_matrix", "title": "Delivery roadmap.", "subtitle": "PLAN",
        "roadmap_matrix": {
            "periods": ["Q1 25", "Q2 25", "Q3 25", "Q4 25"],
            "tracks": [
                {"label": "AI Engineering", "cells": [{"label": "Setup", "status": "live"}, {"label": "v1", "status": "in_build"}, {"label": "v2", "status": "planned"}, {}]},
                {"label": "Data", "cells": [{}, {"label": "Audit", "status": "in_build"}, {"label": "Platform", "status": "planned"}, {}]},
            ],
        },
    },
    {
        "slide_type": "swimlane_timeline", "title": "Programme schedule.", "subtitle": "TIMELINE",
        "swimlane_timeline": {
            "periods": ["Q1", "Q2", "Q3", "Q4"],
            "lanes": [
                {"label": "Talent", "bars": [{"start": 0, "end": 1, "label": "Recruit", "status": "live"}, {"start": 2, "end": 3, "label": "Onboard", "status": "planned"}]},
                {"label": "Platform", "bars": [{"start": 1, "end": 3, "label": "Build", "status": "in_build"}]},
            ],
        },
    },
    {
        "slide_type": "flagship_cards", "title": "Flagship offers.", "subtitle": "MARKET",
        "flagship_cards": [
            {"heading": "AI Due Diligence", "body": "Rapid 3-week assessment.", "kpis": [{"label": "Engagements", "value": "24"}, {"label": "NPS", "value": "87"}], "client": "Private Equity"},
            {"heading": "Process AI", "body": "End-to-end process transformation.", "kpis": [{"label": "Savings", "value": "18%"}], "client": "Fortune 500"},
        ],
    },
]


def test_phase3_types_render_without_error() -> None:
    prs = _render("editorial", _PHASE3_SLIDES)
    assert len(prs.slides) == len(_PHASE3_SLIDES)


def test_phase3_classic_fallback_renders_without_error() -> None:
    """Classic theme must degrade all Phase-3 types without crashing."""
    prs = _render("classic", _PHASE3_SLIDES)
    assert len(prs.slides) == len(_PHASE3_SLIDES)


def test_classic_theme_unchanged_green_topbar() -> None:
    prs = _render("classic")
    content = prs.slides[1]
    # Classic must still paint the primary top bar at the top edge.
    bar = False
    for sh in content.shapes:
        if sh.top is not None and sh.top <= Emu(Inches(0.02)) and sh.width and sh.width >= Emu(Inches(13)):
            if _solid_fill_hex(sh) == "0E7C7B":
                bar = True
    assert bar, "classic theme should keep the solid primary top bar"
