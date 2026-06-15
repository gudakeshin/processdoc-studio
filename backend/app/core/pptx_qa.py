"""Post-render PPTX quality assurance: verify saved artifacts against expected slide JSON.

Checks for truncation, missing text, placeholder strings, empty tables/charts,
off-slide objects, and low text density. Returns detailed QA report with pass/fail
status and remediation hints.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pptx import Presentation

logger = logging.getLogger(__name__)

# Patterns that indicate unfulfilled placeholders or low-quality content
PLACEHOLDER_PATTERNS = {
    "Content pending",
    "TBC",
    "[placeholder]",
    "[todo]",
    "Coming soon",
    "To be completed",
    "To be confirmed",
    "{{",
    "}}",
    "[",  # catches any bracketed placeholder
    "]",
}

# Common truncation signatures from previous renders
TRUNCATION_SIGNATURES = {
    "across ide",  # "across ideas"
    "spanning spe",  # "spanning specific"
    "datase",  # "database"
    "continuou",  # "continuous"
    "manageme",  # "management"
    "processin",  # "processing"
    "performan",  # "performance"
}


_SLIDE_W_IN = 13.333
_SLIDE_H_IN = 7.5
_FOOTER_TOP_IN = 6.9  # shapes below this overlap the footer band
_OVERLAP_THRESHOLD = 0.08  # 8% overlap fraction to count as a real collision


def check_pptx_geometry(pptx_path: Path) -> list[dict[str, Any]]:
    """Deterministic geometry pass — no LLM, no soffice.

    Reads shape bounding boxes from the saved PPTX and returns a list of issues:
      {"slide": int (1-based), "shape": str, "issue": str, "severity": "low"|"medium"|"high"}

    Catches off-canvas shapes, shapes that collide with the footer band, and
    significant bbox overlaps between text shapes on the same slide.
    """
    issues: list[dict[str, Any]] = []
    try:
        from pptx.util import Emu
        prs = Presentation(str(pptx_path))
        emu_per_in = 914400.0

        for si, slide in enumerate(prs.slides):
            shapes = list(slide.shapes)
            # Collect shape bboxes in inches [left, top, right, bottom]
            bboxes: list[tuple[float, float, float, float, str, bool]] = []
            for sh in shapes:
                try:
                    l = (sh.left or 0) / emu_per_in
                    t = (sh.top or 0) / emu_per_in
                    w = (sh.width or 0) / emu_per_in
                    h = (sh.height or 0) / emu_per_in
                    name = str(sh.name or "")
                    has_text = sh.has_text_frame
                    bboxes.append((l, t, l + w, t + h, name, has_text))
                except Exception:
                    continue

            for l, t, r, b, name, has_text in bboxes:
                # Off-canvas (with 0.05" tolerance)
                if r < -0.05 or l > _SLIDE_W_IN + 0.05 or b < -0.05 or t > _SLIDE_H_IN + 0.05:
                    issues.append({"slide": si + 1, "shape": name,
                                   "issue": f"shape off-canvas ({l:.2f},{t:.2f})–({r:.2f},{b:.2f})",
                                   "severity": "high"})
                # Footer collision (non-footer shapes extending below 6.9in)
                if has_text and t < _FOOTER_TOP_IN - 0.05 and b > _FOOTER_TOP_IN + 0.05:
                    issues.append({"slide": si + 1, "shape": name,
                                   "issue": f"text shape crosses footer band (bottom={b:.2f}in)",
                                   "severity": "medium"})

            # Text–text overlap check
            text_shapes = [(l, t, r, b, name) for l, t, r, b, name, ht in bboxes if ht]
            for i in range(len(text_shapes)):
                for j in range(i + 1, len(text_shapes)):
                    l1, t1, r1, b1, n1 = text_shapes[i]
                    l2, t2, r2, b2, n2 = text_shapes[j]
                    ix = max(0.0, min(r1, r2) - max(l1, l2))
                    iy = max(0.0, min(b1, b2) - max(t1, t2))
                    if ix <= 0 or iy <= 0:
                        continue
                    overlap_area = ix * iy
                    a1 = max((r1 - l1) * (b1 - t1), 0.001)
                    a2 = max((r2 - l2) * (b2 - t2), 0.001)
                    frac = overlap_area / min(a1, a2)
                    if frac > _OVERLAP_THRESHOLD:
                        issues.append({"slide": si + 1, "shape": f"{n1}×{n2}",
                                       "issue": f"text shapes overlap {frac:.0%}",
                                       "severity": "high" if frac > 0.3 else "medium"})
    except Exception as exc:
        logger.debug("pptx geometry check failed: %s", exc)
    return issues


def _extract_pptx_text(pptx_path: Path) -> dict[int, list[str]]:
    """Extract all text blocks from each slide in the PPTX.

    Returns: {slide_index: [text_blocks]}
    """
    text_by_slide: dict[int, list[str]] = {}
    try:
        prs = Presentation(str(pptx_path))
        for slide_idx, slide in enumerate(prs.slides):
            text_blocks = []
            for shape in slide.shapes:
                # Table shapes: shape.text is empty; extract cell text directly.
                # Use the safe has_table boolean — accessing `.table` on a non-table
                # GraphicFrame (e.g. a chart) raises ValueError, which hasattr() would not swallow.
                if getattr(shape, "has_table", False):
                    for row in shape.table.rows:
                        for cell in row.cells:
                            t = cell.text_frame.text.strip()
                            if t:
                                text_blocks.append(t)
                elif hasattr(shape, "text") and shape.text:
                    text_blocks.append(shape.text.strip())
            text_by_slide[slide_idx] = text_blocks
    except Exception as e:
        logger.error("Failed to extract text from PPTX: %s", e)
    return text_by_slide


def _find_truncations(text: str) -> list[str]:
    """Find likely truncation signatures in text blocks."""
    found = []
    for sig in TRUNCATION_SIGNATURES:
        if sig.lower() in text.lower():
            found.append(sig)
    return found


def _check_for_placeholders(text: str) -> list[str]:
    """Find placeholder markers indicating incomplete content."""
    found = []
    lower = text.lower()
    for pattern in PLACEHOLDER_PATTERNS:
        pattern_lower = pattern.lower()
        # Check exact match or substring
        if len(pattern) > 1:  # For multi-char patterns, do substring match
            if pattern_lower in lower:
                found.append(pattern)
        else:  # For single chars like [ ], check more carefully
            if pattern in text:  # case-sensitive for brackets
                found.append(pattern)
    return found


def _storytelling_metrics(pptx_slides: list[dict[str, Any]], text_by_slide: dict[int, list[str]]) -> dict[str, Any]:
    """Compute deterministic storytelling/readability signals from expected+rendered slides."""
    total_slides = max(len(pptx_slides), len(text_by_slide))
    if total_slides <= 0:
        return {
            "visual_to_text_balance": 0.0,
            "clutter_risk_slides": [],
            "weak_slides": [],
            "transition_issues": [],
        }

    clutter_risk_slides: list[int] = []
    weak_slides: list[int] = []
    transition_issues: list[int] = []
    slides_with_visual_primitives = 0

    prev_section = ""
    for idx, slide in enumerate(pptx_slides, start=1):
        if not isinstance(slide, dict):
            continue
        slide_type = str(slide.get("slide_type") or "").strip().lower()
        title = str(slide.get("title") or "").strip()
        rendered_blocks = text_by_slide.get(idx - 1, [])
        rendered_chars = sum(len(t.strip()) for t in rendered_blocks if t and t.strip())
        bullet_count = len(slide.get("bullets", [])) if isinstance(slide.get("bullets"), list) else 0
        visual_payload = 0
        for field in ("stat_cards", "column_cards", "stack_layers"):
            value = slide.get(field)
            if isinstance(value, list):
                visual_payload += len(value)
        flow = slide.get("process_flow")
        if isinstance(flow, list):
            visual_payload += len(flow)
        elif isinstance(flow, dict):
            steps = flow.get("steps")
            if isinstance(steps, list):
                visual_payload += len(steps)
        if isinstance(slide.get("table"), dict):
            visual_payload += len(slide["table"].get("rows", [])) if isinstance(slide["table"].get("rows"), list) else 0
        if isinstance(slide.get("chart"), dict):
            visual_payload += 1
        if isinstance(slide.get("big_number"), dict):
            visual_payload += 1
        if visual_payload > 0:
            slides_with_visual_primitives += 1

        if bullet_count >= 5 or rendered_chars > 600:
            clutter_risk_slides.append(idx)
        _FILLER_TITLES = {
            "overview", "summary", "insights", "introduction", "background",
            "next steps", "agenda", "takeaways", "appendix", "context",
        }
        if (not title or title.lower() in _FILLER_TITLES) and rendered_chars < 80 and visual_payload == 0 and bullet_count <= 2:
            weak_slides.append(idx)

        current_section = str(slide.get("subtitle") or "").strip().lower()
        if idx > 1 and not current_section and not prev_section and title and len(title.split()) <= 2:
            transition_issues.append(idx)
        prev_section = current_section

        if slide_type == "bullets" and bullet_count <= 2 and rendered_chars < 120:
            weak_slides.append(idx)

    visual_to_text_balance = round(slides_with_visual_primitives / max(1, len(pptx_slides)), 3)
    return {
        "visual_to_text_balance": visual_to_text_balance,
        "clutter_risk_slides": sorted(set(clutter_risk_slides)),
        "weak_slides": sorted(set(weak_slides)),
        "transition_issues": sorted(set(transition_issues)),
    }


def validate_pptx_against_slides(
    pptx_path: Path,
    pptx_slides: list[dict[str, Any]]
) -> dict[str, Any]:
    """Validate saved PPTX against expected slide JSON.

    Returns QA report with:
    - status: "pass" | "fail"
    - summary: human-readable summary
    - slide_count: number of slides in PPTX
    - expected_count: expected slide count
    - missing_text: list of expected text not found
    - truncations: suspected truncation signatures found
    - placeholders: placeholder patterns found
    - empty_content: slides with no text or very low text density
    - unsupported_claims: numeric metrics without visible evidence
    - remediation: list of suggested fixes
    """

    if not pptx_path.exists():
        return {
            "status": "fail",
            "summary": f"PPTX file not found: {pptx_path}",
            "slide_count": 0,
            "expected_count": len(pptx_slides),
            "issues": ["PPTX artifact missing"],
            "remediation": ["Renderer failed to produce output.pptx"],
        }

    # Extract text from saved PPTX
    text_by_slide = _extract_pptx_text(pptx_path)
    prs = None
    try:
        prs = Presentation(str(pptx_path))
        slide_count = len(prs.slides)
    except Exception:
        slide_count = 0

    expected_count = len(pptx_slides)
    issues: list[str] = []
    missing_text: list[str] = []
    truncations: list[str] = []
    placeholders: list[str] = []
    empty_slides: list[int] = []
    remediation: list[str] = []

    # Check slide count
    if slide_count != expected_count:
        issues.append(f"Slide count mismatch: expected {expected_count}, found {slide_count}")
        remediation.append(f"Verify slide JSON includes all {expected_count} expected slides")

    # Check each expected slide
    for slide_idx, expected_slide in enumerate(pptx_slides[:slide_count] if slide_count > 0 else []):
        if slide_idx >= slide_count:
            issues.append(f"Slide {slide_idx + 1} missing from PPTX")
            remediation.append(f"Check that all {expected_count} slides were rendered")
            continue

        # Extract expected text from slide JSON
        expected_texts = _extract_expected_text_from_slide(expected_slide)
        actual_texts = " ".join(text_by_slide.get(slide_idx, []))

        # Check for missing text
        for exp_text in expected_texts:
            if exp_text and len(exp_text) > 3 and exp_text not in actual_texts:
                missing_text.append(f"Slide {slide_idx + 1}: Missing '{exp_text[:50]}'")

        # Check for truncations and placeholders
        for text_block in text_by_slide.get(slide_idx, []):
            trunc = _find_truncations(text_block)
            if trunc:
                truncations.extend(trunc)
                issues.append(f"Slide {slide_idx + 1}: Likely truncation: {trunc}")

            placeh = _check_for_placeholders(text_block)
            if placeh:
                placeholders.extend(placeh)
                issues.append(f"Slide {slide_idx + 1}: Placeholder found: {placeh}")

        # Check for empty slides (stricter: if expected content but rendered text is empty/minimal)
        expected_has_content = len(expected_texts) > 0
        actual_text_len = len(actual_texts.strip())

        if expected_has_content and actual_text_len < 5:
            empty_slides.append(slide_idx + 1)
            issues.append(f"Slide {slide_idx + 1}: Expected content but rendered text is empty/minimal")
        elif not expected_has_content and actual_text_len < 5:
            empty_slides.append(slide_idx + 1)
            issues.append(f"Slide {slide_idx + 1}: Very low text content")

    # Storytelling heuristics are advisory only — they enrich the report and remediation hints
    # but must NOT gate the render (mirrors the advisory-only evidence-validation invariant).
    advisories: list[str] = []
    storytelling = _storytelling_metrics(pptx_slides, text_by_slide)
    if storytelling["clutter_risk_slides"]:
        advisories.append(f"Clutter/readability risk on slides {storytelling['clutter_risk_slides']}")
        remediation.append(
            f"Reduce text density on slides {storytelling['clutter_risk_slides']}; split dense bullets into visual cards."
        )
    if storytelling["weak_slides"]:
        advisories.append(f"Weak storytelling signal on slides {storytelling['weak_slides']}")
        remediation.append(
            f"Strengthen slide intent on slides {storytelling['weak_slides']} with concrete insight titles and evidence."
        )
    if storytelling["transition_issues"]:
        advisories.append(f"Section-transition continuity risk on slides {storytelling['transition_issues']}")
        remediation.append(
            "Add explicit section breadcrumbs/subtitles to improve narrative flow between adjacent slides."
        )

    # Overall status — only hard structural issues fail the gate; advisories never do.
    status = "pass" if not issues else "fail"

    summary = f"PPTX QA: {status.upper()}"
    if issues:
        summary += f" — {len(issues)} issue(s) found"

    if missing_text:
        remediation.append("Re-render with complete slide text from source data")
    if truncations:
        remediation.append("Rewrite long text to fit available space; use abbreviated labels")
    if placeholders:
        remediation.append("Replace placeholder text with actual content; ensure all metrics are substantiated")
    if empty_slides:
        remediation.append(f"Add content to slides {empty_slides} or remove them")

    # Deterministic geometry pass (no LLM, no soffice) — advisory only.
    # Results inform the operator and the pixel critic rubric but do not gate the pipeline.
    geometry_issues: list[dict[str, Any]] = []
    try:
        geometry_issues = check_pptx_geometry(pptx_path)
        off_canvas = [g for g in geometry_issues if "off-canvas" in g.get("issue", "")]
        if off_canvas:
            advisories.append(f"{len(off_canvas)} shape(s) detected off-canvas — check slide content geometry")
    except Exception as exc:
        logger.debug("geometry check failed: %s", exc)

    return {
        "status": status,
        "summary": summary,
        "slide_count": slide_count,
        "expected_count": expected_count,
        "issues": issues,
        "missing_text": missing_text,
        "truncations": list(set(truncations)),
        "placeholders": list(set(placeholders)),
        "empty_slides": empty_slides,
        "advisories": advisories,
        "storytelling_metrics": storytelling,
        "remediation": remediation,
        "geometry_issues": geometry_issues,
        "pptx_path": str(pptx_path),
    }


def _extract_expected_text_from_slide(slide: dict[str, Any]) -> list[str]:
    """Extract expected text blocks from slide JSON."""
    expected = []

    if "title" in slide and slide["title"]:
        expected.append(str(slide["title"]))

    if "subtitle" in slide and slide["subtitle"]:
        expected.append(str(slide["subtitle"]))

    if "bullets" in slide and isinstance(slide["bullets"], list):
        expected.extend(str(b) for b in slide["bullets"] if b)

    if "stat_cards" in slide and isinstance(slide["stat_cards"], list):
        for card in slide["stat_cards"]:
            if isinstance(card, dict):
                expected.extend(
                    str(card.get(k))
                    for k in ("stat", "label", "description")
                    if card.get(k)
                )

    if "column_cards" in slide and isinstance(slide["column_cards"], list):
        for card in slide["column_cards"]:
            if isinstance(card, dict):
                expected.extend(
                    str(card.get(k))
                    for k in ("heading", "body")
                    if card.get(k)
                )

    if "stack_layers" in slide and isinstance(slide["stack_layers"], list):
        for layer in slide["stack_layers"]:
            if isinstance(layer, dict):
                expected.extend(
                    str(layer.get(k))
                    for k in ("label", "description")
                    if layer.get(k)
                )

    if "table" in slide and isinstance(slide["table"], dict):
        table = slide["table"]
        if "headers" in table and isinstance(table["headers"], list):
            expected.extend(str(h) for h in table["headers"] if h)
        if "rows" in table and isinstance(table["rows"], list):
            for row in table["rows"]:
                if isinstance(row, list):
                    expected.extend(str(cell) for cell in row if cell)

    if "chart" in slide and isinstance(slide["chart"], dict):
        chart = slide["chart"]
        if "title" in chart and chart["title"]:
            expected.append(str(chart["title"]))
        if "series" in chart and isinstance(chart["series"], list):
            for s in chart["series"]:
                if isinstance(s, dict) and "name" in s and s["name"]:
                    expected.append(str(s["name"]))

    if "big_number" in slide and isinstance(slide["big_number"], dict):
        bn = slide["big_number"]
        expected.extend(
            str(bn.get(k))
            for k in ("stat", "label", "context")
            if bn.get(k)
        )

    if "process_flow" in slide:
        flow = slide["process_flow"]
        steps = flow.get("steps", []) if isinstance(flow, dict) else flow
        if isinstance(steps, list):
            for step in steps:
                if isinstance(step, dict):
                    expected.extend(
                        str(step.get(k))
                        for k in ("label", "description")
                        if step.get(k)
                    )

    if "footer" in slide and slide["footer"]:
        expected.append(str(slide["footer"]))

    # Phase-3 editorial types
    if "items" in slide and isinstance(slide["items"], list):  # split_panel
        for item in slide["items"]:
            if isinstance(item, dict):
                expected.extend(str(item.get(k)) for k in ("label", "body") if item.get(k))

    if "lanes" in slide and isinstance(slide["lanes"], list):
        for lane in slide["lanes"]:
            if isinstance(lane, dict):
                if lane.get("label"):
                    expected.append(str(lane["label"]))
                expected.extend(str(i) for i in lane.get("items", []) if i)

    if "workstream_cards" in slide and isinstance(slide["workstream_cards"], list):
        for card in slide["workstream_cards"]:
            if isinstance(card, dict):
                expected.extend(str(card.get(k)) for k in ("heading", "owner", "body") if card.get(k))

    if "tower_cards" in slide and isinstance(slide["tower_cards"], list):
        for tower in slide["tower_cards"]:
            if isinstance(tower, dict):
                if tower.get("heading"):
                    expected.append(str(tower["heading"]))
                for item in tower.get("items", []):
                    text = str(item.get("text", item.get("label", item))) if isinstance(item, dict) else str(item)
                    if text:
                        expected.append(text)
                if tower.get("takeaway"):
                    expected.append(str(tower["takeaway"]))

    if "roadmap_matrix" in slide and isinstance(slide["roadmap_matrix"], dict):
        data = slide["roadmap_matrix"]
        expected.extend(str(p) for p in data.get("periods", []) if p)
        for tr in data.get("tracks", []):
            if isinstance(tr, dict):
                if tr.get("label"):
                    expected.append(str(tr["label"]))
                for cell in tr.get("cells", []):
                    if isinstance(cell, dict) and cell.get("label"):
                        expected.append(str(cell["label"]))

    if "swimlane_timeline" in slide and isinstance(slide["swimlane_timeline"], dict):
        data = slide["swimlane_timeline"]
        expected.extend(str(p) for p in data.get("periods", []) if p)
        for lane in data.get("lanes", []):
            if isinstance(lane, dict):
                if lane.get("label"):
                    expected.append(str(lane["label"]))
                for bar in lane.get("bars", []):
                    if isinstance(bar, dict) and bar.get("label"):
                        expected.append(str(bar["label"]))

    if "flagship_cards" in slide and isinstance(slide["flagship_cards"], list):
        for card in slide["flagship_cards"]:
            if isinstance(card, dict):
                expected.extend(str(card.get(k)) for k in ("heading", "body", "client") if card.get(k))
                for kpi in card.get("kpis", []):
                    if isinstance(kpi, dict):
                        expected.extend(str(kpi.get(k)) for k in ("label", "value") if kpi.get(k))

    # Filter out empty strings and very short fragments
    return [t for t in expected if t and len(t) > 2]
