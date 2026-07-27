"""Pre-render PPTX slide schema validator.

Validates LLM-produced slide JSON before it reaches the renderer so violations
are caught cheaply (no soffice round-trip) and fed into the remediation loop.
"""

from __future__ import annotations

from typing import Any

from app.core.pptx_text_metrics import CHAR_BUDGETS

# All slide types the system can render (editorial or classic fallback).
SUPPORTED_SLIDE_TYPES = {
    "title", "bullets", "stat_cards", "column_cards", "stack_layers",
    "table", "chart", "section_divider", "big_number", "process_flow",
    # Phase-3 editorial types (classic composer degrades gracefully)
    "split_panel", "lanes", "workstream_cards", "tower_cards",
    "roadmap_matrix", "swimlane_timeline", "flagship_cards",
    # Pillar B figure slides (rendered by the shared raster figure engine)
    "figure", "two_by_two", "value_chain", "maturity_curve", "heat_map",
    "waterfall", "gantt", "harvey_balls", "benchmark_bars",
}

# Rich storyline visuals + the essential field(s) each needs to render as more
# than a bullet fallback. Keys mirror SUPPORTED_SLIDE_TYPES; values are the
# must-have top-level slide key(s). Shared source of truth for the storyline
# spine prompt and the design-review visual-fidelity check so the two can't drift.
RICH_VISUAL_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "two_by_two": ("quadrants",),       # + x_label / y_label recommended
    "value_chain": ("stages",),
    "maturity_curve": ("stages",),      # + current_index / target_index
    "heat_map": ("rows", "cols", "cells"),
    "roadmap_matrix": ("roadmap_matrix",),  # nested {periods, tracks}
    "process_flow": ("process_flow",),  # nested {steps}
    "waterfall": ("bars",),
    "gantt": ("tasks",),
    "harvey_balls": ("rows",),
    "benchmark_bars": ("series",),
}

_VALID_STATUSES = {"live", "in_build", "planned", "partner"}

_FILL_TOKENS = {"dark", "mid_dark", "green", "dark_green", "gray", "mid"}


def validate_slide_schema(slides: list[dict[str, Any]]) -> list[str]:
    """Return a list of violation strings; empty list means schema is clean.

    Called pre-render; violations are advisory by default — the caller decides
    whether to gate or pass them to the remediation loop as soft hints.
    """
    violations: list[str] = []

    for idx, slide in enumerate(slides):
        if not isinstance(slide, dict):
            violations.append(f"Slide {idx+1}: not a dict")
            continue
        sn = f"Slide {idx+1} ({slide.get('slide_type', '?')})"
        st = str(slide.get("slide_type", "")).lower().strip()

        if not st:
            violations.append(f"{sn}: missing slide_type")
            continue
        if st not in SUPPORTED_SLIDE_TYPES:
            violations.append(f"{sn}: unknown slide_type '{st}'")
            continue

        # --- common text budget checks ---
        title = str(slide.get("title", ""))
        if title and len(title) > CHAR_BUDGETS.get("headline", 90):
            violations.append(f"{sn}: title too long ({len(title)} chars, budget {CHAR_BUDGETS.get('headline', 90)})")

        kicker = str(slide.get("kicker", ""))
        if kicker and len(kicker) > CHAR_BUDGETS.get("kicker", 130):
            violations.append(f"{sn}: kicker too long ({len(kicker)} chars)")

        eyebrow = str(slide.get("eyebrow", slide.get("subtitle", "")))
        if eyebrow and len(eyebrow) > CHAR_BUDGETS.get("eyebrow", 38):
            violations.append(f"{sn}: eyebrow/subtitle too long ({len(eyebrow)} chars)")

        # --- type-specific checks ---
        if st == "bullets":
            bullets = slide.get("bullets", [])
            if not isinstance(bullets, list) or not bullets:
                violations.append(f"{sn}: bullets must be a non-empty list")
            else:
                for bi, b in enumerate(bullets[:10]):
                    if len(str(b)) > CHAR_BUDGETS.get("bullet", 160):
                        violations.append(f"{sn}: bullet[{bi}] too long ({len(str(b))} chars)")

        elif st == "stat_cards":
            cards = slide.get("stat_cards", [])
            if not isinstance(cards, list) or not cards:
                violations.append(f"{sn}: stat_cards must be non-empty")
            else:
                for ci, c in enumerate(cards):
                    if not isinstance(c, dict):
                        continue
                    if not c.get("stat"):
                        violations.append(f"{sn}: stat_cards[{ci}] missing 'stat'")
                    if not c.get("label"):
                        violations.append(f"{sn}: stat_cards[{ci}] missing 'label'")

        elif st == "column_cards":
            cards = slide.get("column_cards", [])
            if not isinstance(cards, list) or len(cards) < 2:
                violations.append(f"{sn}: column_cards needs ≥2 items")
            elif len(cards) > 4:
                violations.append(f"{sn}: column_cards has {len(cards)} items; max 4")

        elif st == "stack_layers":
            layers = slide.get("stack_layers", [])
            if not isinstance(layers, list) or len(layers) < 2:
                violations.append(f"{sn}: stack_layers needs ≥2 layers")

        elif st == "process_flow":
            flow = slide.get("process_flow", {})
            steps = flow.get("steps", flow) if isinstance(flow, dict) else flow
            if not isinstance(steps, list) or len(steps) < 2:
                violations.append(f"{sn}: process_flow needs ≥2 steps")
            elif len(steps) > 5:
                violations.append(f"{sn}: process_flow has {len(steps)} steps; max 5")

        elif st == "workstream_cards":
            cards = slide.get("workstream_cards", [])
            if not isinstance(cards, list) or not cards:
                violations.append(f"{sn}: workstream_cards must be non-empty")
            else:
                if len(cards) > 6:
                    violations.append(f"{sn}: workstream_cards has {len(cards)} items; max 6")
                for ci, c in enumerate(cards):
                    if not isinstance(c, dict):
                        continue
                    status = str(c.get("status", "")).lower()
                    if status and status not in _VALID_STATUSES:
                        violations.append(f"{sn}: workstream_cards[{ci}].status '{status}' invalid; must be one of {sorted(_VALID_STATUSES)}")

        elif st == "tower_cards":
            towers = slide.get("tower_cards", [])
            if not isinstance(towers, list) or not towers:
                violations.append(f"{sn}: tower_cards must be non-empty")
            elif len(towers) > 5:
                violations.append(f"{sn}: tower_cards has {len(towers)} items; max 5")

        elif st == "lanes":
            lanes = slide.get("lanes", [])
            if not isinstance(lanes, list) or len(lanes) < 2:
                violations.append(f"{sn}: lanes needs ≥2 lanes")
            elif len(lanes) > 4:
                violations.append(f"{sn}: lanes has {len(lanes)} items; max 4")

        elif st == "split_panel":
            items = slide.get("items", [])
            if not isinstance(items, list) or not items:
                violations.append(f"{sn}: split_panel needs at least 1 item")
            elif len(items) > 5:
                violations.append(f"{sn}: split_panel has {len(items)} items; max 5")

        elif st == "roadmap_matrix":
            data = slide.get("roadmap_matrix", {})
            if not isinstance(data, dict):
                violations.append(f"{sn}: roadmap_matrix must be an object")
            else:
                if not data.get("periods"):
                    violations.append(f"{sn}: roadmap_matrix missing periods")
                if not data.get("tracks"):
                    violations.append(f"{sn}: roadmap_matrix missing tracks")
                else:
                    for ti, tr in enumerate(data.get("tracks", [])):
                        if isinstance(tr, dict):
                            for ci, cell in enumerate(tr.get("cells", [])):
                                if isinstance(cell, dict):
                                    status = str(cell.get("status", "")).lower()
                                    if status and status not in _VALID_STATUSES:
                                        violations.append(f"{sn}: roadmap_matrix.tracks[{ti}].cells[{ci}].status invalid")

        elif st == "swimlane_timeline":
            data = slide.get("swimlane_timeline", {})
            if not isinstance(data, dict):
                violations.append(f"{sn}: swimlane_timeline must be an object")
            else:
                if not data.get("periods"):
                    violations.append(f"{sn}: swimlane_timeline missing periods")
                if not data.get("lanes"):
                    violations.append(f"{sn}: swimlane_timeline missing lanes")

        elif st == "flagship_cards":
            cards = slide.get("flagship_cards", [])
            if not isinstance(cards, list) or not cards:
                violations.append(f"{sn}: flagship_cards must be non-empty")
            elif len(cards) > 3:
                violations.append(f"{sn}: flagship_cards has {len(cards)} items; max 3")

    return violations
