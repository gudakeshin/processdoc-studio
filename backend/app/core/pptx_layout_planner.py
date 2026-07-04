"""Pure layout planning for PPTX slides before render (Phase 2).

Estimates text density against ``CHAR_BUDGETS`` and emits reflow actions —
``demote`` (dense column_cards → bullets), ``split`` (long bullet lists or
tables → continuation slides), ``notes_overflow`` (prose moved to speaker
notes). No LLM; never raises.
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from app.core.pptx_text_metrics import CHAR_BUDGETS

logger = logging.getLogger(__name__)

BULLET_SPLIT_THRESHOLD = 8
TABLE_ROW_SPLIT_THRESHOLD = 12
DEMOTE_BODY_FACTOR = 1.4
NOTES_OVERFLOW_FACTOR = 1.5


def estimate_density(slide: dict[str, Any]) -> dict[str, Any]:
    """Return density signals for a single slide dict."""
    st = str(slide.get("slide_type") or "").lower()
    card_body = 0
    total_body = 0

    for b in slide.get("bullets") or []:
        total_body += len(str(b or ""))
    for c in slide.get("column_cards") or []:
        if isinstance(c, dict):
            card_body += len(str(c.get("body") or ""))
            total_body += len(str(c.get("body") or "")) + len(str(c.get("heading") or ""))
    for row in slide.get("table") or slide.get("rows") or []:
        if isinstance(row, (list, tuple)):
            total_body += sum(len(str(c or "")) for c in row)
    for field in ("takeaway", "synthesis_text", "kicker", "subtitle"):
        total_body += len(str(slide.get(field) or ""))

    card_budget = CHAR_BUDGETS.get("card_body", 220)
    bullet_count = len(slide.get("bullets") or [])
    table_rows = len(slide.get("table") or slide.get("rows") or [])

    return {
        "slide_type": st,
        "total_body_chars": total_body,
        "card_body_chars": card_body,
        "bullet_count": bullet_count,
        "table_rows": table_rows,
        "demote_candidate": st == "column_cards" and card_body > card_budget * DEMOTE_BODY_FACTOR,
        "split_bullets": st == "bullets" and bullet_count > BULLET_SPLIT_THRESHOLD,
        "split_table": st == "table" and table_rows > TABLE_ROW_SPLIT_THRESHOLD + 1,
    }


def _demote_column_cards(slide: dict[str, Any]) -> dict[str, Any]:
    cards = [c for c in (slide.get("column_cards") or []) if isinstance(c, dict)]
    bullets: list[str] = []
    for c in cards:
        heading = str(c.get("heading") or "").strip()
        body = str(c.get("body") or "").strip()
        if heading and body:
            bullets.append(f"**{heading}**: {body}")
        elif heading:
            bullets.append(heading)
        elif body:
            bullets.append(body)
    out = dict(slide)
    out["slide_type"] = "bullets"
    out.pop("column_cards", None)
    out["bullets"] = bullets or ["See prior context."]
    return out


def _split_bullets(
    slide: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    bullets = [str(b) for b in (slide.get("bullets") or []) if str(b).strip()]
    if len(bullets) <= BULLET_SPLIT_THRESHOLD:
        return slide, None
    primary = dict(slide)
    primary["bullets"] = bullets[:BULLET_SPLIT_THRESHOLD]
    cont = dict(slide)
    base_title = str(slide.get("title") or "Content")
    cont["title"] = base_title if base_title.endswith("(continued)") else f"{base_title} (continued)"
    cont["bullets"] = bullets[BULLET_SPLIT_THRESHOLD:]
    sid = str(slide.get("slide_id") or "").strip()
    if sid:
        cont["slide_id"] = f"{sid}_cont"
    cont["_continuation_of"] = sid or base_title
    return primary, cont


def _split_table(
    slide: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    rows = slide.get("table") or slide.get("rows") or []
    if not isinstance(rows, list) or len(rows) <= TABLE_ROW_SPLIT_THRESHOLD:
        return slide, None
    header = rows[0] if rows and isinstance(rows[0], (list, tuple)) else None
    data_rows = rows[1:] if header is not None else rows
    if len(data_rows) <= TABLE_ROW_SPLIT_THRESHOLD:
        return slide, None
    first_chunk = data_rows[:TABLE_ROW_SPLIT_THRESHOLD]
    rest_chunk = data_rows[TABLE_ROW_SPLIT_THRESHOLD:]
    primary = dict(slide)
    primary_rows = ([header] if header is not None else []) + first_chunk
    primary["table"] = primary_rows
    cont = dict(slide)
    base_title = str(slide.get("title") or "Table")
    cont["title"] = base_title if base_title.endswith("(continued)") else f"{base_title} (continued)"
    cont_rows = ([header] if header is not None else []) + rest_chunk
    cont["table"] = cont_rows
    sid = str(slide.get("slide_id") or "").strip()
    if sid:
        cont["slide_id"] = f"{sid}_cont"
    cont["_continuation_of"] = sid or base_title
    return primary, cont


def _notes_overflow(slide: dict[str, Any]) -> dict[str, Any]:
    """Move over-budget prose fields into speaker_notes instead of trimming."""
    out = dict(slide)
    notes_parts: list[str] = []
    for field, budget_key in (("takeaway", "takeaway"), ("synthesis_text", "synthesis_text")):
        val = str(out.get(field) or "").strip()
        if not val:
            continue
        budget = CHAR_BUDGETS.get(budget_key, 220)
        if len(val) > budget * NOTES_OVERFLOW_FACTOR:
            notes_parts.append(val)
            out[field] = val[:budget].rstrip() + "…"
    if notes_parts:
        existing = str(out.get("speaker_notes") or "").strip()
        merged = "\n\n".join(p for p in ([existing] if existing else []) + notes_parts if p)
        out["speaker_notes"] = merged
    return out


def _assign_identities(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for idx, s in enumerate(slides, start=1):
        if not str(s.get("slide_id") or "").strip():
            s["slide_id"] = f"slide_{idx:02d}"
        s["slide_index"] = idx
    return slides


def plan_layout(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply demote/split/notes_overflow; return expanded slide list with stable IDs."""
    if not slides:
        return []
    out: list[dict[str, Any]] = []
    for raw in slides:
        if not isinstance(raw, dict):
            continue
        slide = copy.deepcopy(raw)
        density = estimate_density(slide)

        if density["demote_candidate"]:
            slide = _demote_column_cards(slide)

        slide = _notes_overflow(slide)
        st = str(slide.get("slide_type") or "").lower()

        if st == "bullets" and density["split_bullets"]:
            primary, cont = _split_bullets(slide)
            out.append(primary)
            if cont:
                out.append(cont)
            continue

        if st == "table" and density["split_table"]:
            primary, cont = _split_table(slide)
            out.append(primary)
            if cont:
                out.append(cont)
            continue

        out.append(slide)

    return _assign_identities(out)


def apply_layout_planner_if_enabled(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flag-gated entry point; returns input unchanged on disable or error."""
    try:
        from app.core.config import settings

        if not getattr(settings, "pptx_layout_planner_enabled", False):
            return slides
        return plan_layout(slides)
    except Exception as exc:  # noqa: BLE001 — planner is best-effort
        logger.warning("pptx layout planner skipped: %s", exc)
        return slides
