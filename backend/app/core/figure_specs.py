"""Grounded figure-spec derivation (Deloitte-quality program, Pillar B).

Turns a process model into figure specs the figure engine can render. Every spec
is derived from data that actually exists in the model — we never fabricate a
maturity curve or risk grid from nothing (that would violate the evidence
discipline enforced in Pillar C). Shared by the DOCX renderer and available to the
PPTX renderer.
"""
from __future__ import annotations

from typing import Any

# Map common qualitative words to a 0..1 heat value.
_LEVEL = {
    "very low": 0.1, "low": 0.25, "minor": 0.25, "moderate": 0.55, "medium": 0.55,
    "med": 0.55, "high": 0.85, "severe": 0.9, "critical": 1.0, "very high": 1.0,
}


def _level(raw: Any) -> float | str:
    if isinstance(raw, (int, float)):
        v = float(raw)
        return max(0.0, min(1.0, v / 100.0 if v > 1.0 else v))
    s = str(raw or "").strip().lower()
    return _LEVEL.get(s, s or 0.0)


def _value_chain(pm: dict) -> dict | None:
    from app.core.deliverable_utils import humanize_wiki_links

    steps = [s for s in (pm.get("steps") or []) if isinstance(s, dict)]
    if len(steps) < 2:
        return None
    stages = []
    for s in steps[:6]:
        label = humanize_wiki_links(s.get("name") or s.get("label") or s.get("activity") or "")
        if not label:
            continue
        # Keep chevron labels short so they read cleanly inside the shape.
        if len(label) > 42:
            label = label[:41].rstrip() + "…"
        sub = humanize_wiki_links(s.get("role") or s.get("owner") or "")
        stages.append({"label": label, "sub": sub})
    if len(stages) < 2:
        return None
    return {"type": "value_chain", "stages": stages}


def _risk_heat_map(pm: dict) -> dict | None:
    risks = [r for r in (pm.get("risks") or []) if isinstance(r, dict)]
    rows, cells = [], []
    for r in risks[:6]:
        name = str(r.get("name") or r.get("title") or r.get("risk") or "").strip()
        if not name:
            continue
        likelihood = r.get("likelihood") if r.get("likelihood") is not None else r.get("probability")
        impact = r.get("impact") if r.get("impact") is not None else r.get("severity")
        if likelihood is None and impact is None:
            continue
        rows.append(name)
        cells.append([_level(likelihood), _level(impact)])
    if len(rows) < 2:
        return None
    return {"type": "heat_map", "rows": rows, "cols": ["Likelihood", "Impact"], "cells": cells}


def _roadmap(pm: dict) -> dict | None:
    phases = [p for p in (pm.get("phases") or pm.get("roadmap") or []) if isinstance(p, dict)]
    if len(phases) < 2:
        return None
    periods = [str(p.get("name") or p.get("label") or f"Phase {i+1}").strip() for i, p in enumerate(phases)]
    tracks: list[str] = []
    bars: list[dict] = []
    for i, p in enumerate(phases):
        for wk in (p.get("workstreams") or p.get("activities") or []):
            name = str((wk or {}).get("track") if isinstance(wk, dict) else wk or "").strip()
            label = str((wk or {}).get("label") if isinstance(wk, dict) else "").strip() or name
            if not name:
                continue
            if name not in tracks:
                tracks.append(name)
            bars.append({"track": name, "start": i, "span": 1, "label": label,
                         "status": str((wk or {}).get("status") if isinstance(wk, dict) else "") or "in_build"})
    if len(tracks) < 2 or not bars:
        return None
    return {"type": "roadmap_matrix", "tracks": tracks[:6], "periods": periods[:6], "bars": bars}


def _gantt_from_phases(pm: dict) -> dict | None:
    phases = [p for p in (pm.get("phases") or pm.get("roadmap") or []) if isinstance(p, dict)]
    if len(phases) < 2:
        return None
    tasks: list[dict[str, Any]] = []
    n = len(phases)
    for i, p in enumerate(phases):
        lane = str(p.get("name") or p.get("label") or f"Phase {i + 1}").strip()
        start = i / max(1, n)
        end = min(1.0, (i + 1) / max(1, n))
        tasks.append({"label": lane, "start": start, "end": end, "lane": "Delivery"})
    return {"type": "gantt", "tasks": tasks}


def _harvey_from_maturity(pm: dict) -> dict | None:
    """Harvey-ball rows from *measured* maturity scores only.

    Roles carry no maturity signal in the process model, so they are not
    emitted — assigning them a score would fabricate the very assessment the
    figure claims to present. Dimensions without a numeric score are skipped
    for the same reason.
    """
    maturity = pm.get("maturity") if isinstance(pm.get("maturity"), dict) else {}
    rows: list[dict[str, Any]] = []
    for dim, score in list(maturity.items())[:6]:
        if not isinstance(dim, str) or isinstance(score, bool):
            continue
        if not isinstance(score, (int, float)):
            continue
        rows.append({
            "label": dim.replace("_", " ").title(),
            "scores": [max(0, min(4, int(score)))],
        })
    if len(rows) < 2:
        return None
    return {"type": "harvey_balls", "rows": rows}


def derive_figures_from_process_model(pm: dict | None, *, max_figures: int = 3) -> list[dict[str, Any]]:
    """Return up to ``max_figures`` grounded figure *blocks* (``{type:'figure', figure, caption}``).

    Only figures whose underlying data exists in the model are produced, so the
    count varies by how rich the model is.
    """
    if not isinstance(pm, dict):
        return []
    from app.core.deliverable_utils import humanize_wiki_links

    proc = humanize_wiki_links(pm.get("process_name") or pm.get("name") or "the process") or "the process"
    out: list[dict[str, Any]] = []
    vc = _value_chain(pm)
    if vc:
        out.append({"type": "figure", "figure": vc,
                    "caption": f"End-to-end value chain for {proc}."})
    rm = _roadmap(pm)
    if rm:
        out.append({"type": "figure", "figure": rm,
                    "caption": "Phased delivery roadmap by workstream."})
    hm = _risk_heat_map(pm)
    if hm:
        out.append({"type": "figure", "figure": hm,
                    "caption": "Risk exposure by likelihood and impact."})
    try:
        from app.core.config import settings

        if getattr(settings, "figure_vocab_v2_enabled", False):
            gt = _gantt_from_phases(pm)
            if gt:
                out.append({"type": "figure", "figure": gt, "caption": "Phased delivery timeline."})
            hb = _harvey_from_maturity(pm)
            if hb:
                out.append({"type": "figure", "figure": hb, "caption": "Capability maturity by dimension."})
    except Exception:  # noqa: BLE001, S110 — v2 figure vocab is additive/optional
        pass
    return out[:max_figures]


def splice_figure_blocks(blocks: list[dict[str, Any]], figure_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert figure blocks after section headings, spacing them through the document.

    The first figure lands after the first level-1/2 heading; remaining figures
    follow subsequent headings. Any leftover figures are appended at the end.
    """
    if not figure_blocks:
        return blocks
    queue = list(figure_blocks)
    result: list[dict[str, Any]] = []
    seen_first = False
    for b in blocks:
        result.append(b)
        if not queue:
            continue
        if b.get("type") == "heading" and int(b.get("level", 1) or 1) <= 2:
            # Skip the very first heading if it's the document title; place after the next.
            if not seen_first:
                seen_first = True
                continue
            result.append(queue.pop(0))
    result.extend(queue)
    return result
