"""StorylineBuilder — collaborative narrative arc proposal.

Given discovery slots and project context (LP library + wiki), proposes
2–3 narrative arc options with explicit reasoning. Saves the agreed arc
as a MemoryItem so it is available to the PPTX agent and any future run.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from app.core.tz import IST
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import MemoryItem
from app.core.config import settings
from app.core.model_tiers import planning_model
from app.services.claude import (
    _extract_first_json_object,
    claude_generate_json,
    claude_generate_with_thinking,
    is_claude_enabled,
)
from app.services.leading_practices import leading_practice_library_service as _lp

logger = logging.getLogger(__name__)

# Visual vocabulary the storyline planner may assign to a slide. Kept in sync with
# the renderer's supported slide types (pptx_schema / pptx_artifact_renderer). The
# planner picks per slide so the deck is diagram-led, not a bullet wall.
STORYLINE_VISUAL_VOCAB: tuple[str, ...] = (
    "big_number",       # one hero metric — impact / headline proof
    "stat_cards",       # 2-6 KPIs side by side
    "column_cards",     # 2-4 parallel concepts (MECE pillars)
    "stack_layers",     # layered model / maturity stack
    "process_flow",     # sequential steps with connectors
    "table",            # structured comparison / RACI
    "chart",            # quantitative trend or breakdown
    "bullets",          # use sparingly — only when no visual fits
    "section_divider",  # arc transition
    "two_by_two",       # 2x2 positioning matrix (Phase B figure)
    "value_chain",      # linked value-chain stages (Phase B figure)
    "maturity_curve",   # current vs target maturity (Phase B figure)
    "heat_map",         # risk / priority heat map (Phase B figure)
    "roadmap_matrix",   # phased roadmap by track (Phase B figure)
    "waterfall",        # bridge / variance waterfall (Phase 3)
    "gantt",            # phased timeline by lane (Phase 3)
    "harvey_balls",     # maturity / RACI score grid (Phase 3)
    "benchmark_bars",   # actual vs benchmark bars (Phase 3)
)

# Visuals that can carry a quantitative claim. Numeric required_evidence must
# map to one of these — bullets/topic layouts are not acceptable for a number.
NUMERIC_VISUALS: frozenset[str] = frozenset({
    "chart",
    "big_number",
    "stat_cards",
    "waterfall",
    "benchmark_bars",
    "harvey_balls",
    "table",
})

_NUMERIC_EVIDENCE_RE = re.compile(
    r"(?:\d|\$|%|\b(?:kpi|roi|fte|saving|cost|revenue|margin|cycle.?time|headcount)\b)",
    re.I,
)

_ASSUMPTION_EVIDENCE_RE = re.compile(r"assumption|to validate|tbd|n/?a", re.I)


def evidence_requires_numeric_visual(required_evidence: str) -> bool:
    """True when required_evidence cites a concrete metric (not a pure assumption)."""
    ev = (required_evidence or "").strip()
    if not ev or _ASSUMPTION_EVIDENCE_RE.search(ev):
        return False
    return bool(_NUMERIC_EVIDENCE_RE.search(ev))


def coerce_numeric_visual(suggested_visual: str, required_evidence: str) -> str:
    """Force a quantitative layout when evidence is numeric and the visual is weak."""
    vis = (suggested_visual or "").strip()
    if not evidence_requires_numeric_visual(required_evidence):
        return vis if vis in STORYLINE_VISUAL_VOCAB else "column_cards"
    if vis in NUMERIC_VISUALS:
        return vis
    # Prefer chart when the claim looks like a trend/breakdown; else big_number.
    if re.search(r"%|trend|vs\.?|year|quarter|breakdown", required_evidence or "", re.I):
        return "chart"
    return "big_number"


# Human-readable inline-field hints for the rich visuals, surfaced in the spine
# prompt so the drafting model emits the fields each layout needs. Keys are the
# subset of STORYLINE_VISUAL_VOCAB enforced by the visual-fidelity gate (mirrors
# pptx_schema.RICH_VISUAL_REQUIRED_FIELDS).
_VISUAL_FIELD_HINTS: dict[str, str] = {
    "two_by_two": "fields: quadrants[{label, items}], x_label, y_label",
    "value_chain": "fields: stages[{label, sub}]",
    "maturity_curve": "fields: stages[labels], current_index, target_index",
    "heat_map": "fields: rows[], cols[], cells[[...]]",
    "roadmap_matrix": "field: roadmap_matrix{periods[], tracks[{label, cells[{status}]}]}",
    "process_flow": "field: process_flow{steps[2-5]}",
    "waterfall": "fields: bars[{label, delta, kind}]",
    "gantt": "fields: tasks[{label, start, end, lane}]",
    "harvey_balls": "fields: rows[{label, scores[]}]",
    "benchmark_bars": "fields: series[{label, value, benchmark}]",
}

# Canonical arc definitions — used as both prompting context and fallback copy.
ARC_LIBRARY: dict[str, dict[str, str]] = {
    "scqa": {
        "name": "SCQA (Situation → Complication → Key Question → Answer)",
        "best_for": "Finance transformation, regulatory/compliance change, risk-heavy contexts",
        "structure": "Open with the stable Situation, then the Complication that disrupts it, the Key Question decision-makers are wrestling with, and the Answer (your recommended path).",
    },
    "pyramid": {
        "name": "Pyramid (Governing Thought → Supporting Arguments → Evidence)",
        "best_for": "Executive audiences who want the bottom line first; board-level presentations",
        "structure": "Lead with the single governing recommendation, support it with 3 pillars, back each pillar with evidence and data.",
    },
    "case_led": {
        "name": "Case for Change (Context → Case → Outcomes → Approach → Proof)",
        "best_for": "Transformation proposals where you need to build momentum before the 'ask'",
        "structure": "Set the context, make the case for why the status quo is unsustainable, show desired outcomes, lay out the approach, close with proof points and commercial terms.",
    },
}


def _lp_snippet_for_arc(arc_key: str, domain_hint: str) -> str:
    """Return a short LP library excerpt relevant to this arc and domain."""
    query = f"{arc_key} narrative structure {domain_hint} consulting presentation"
    try:
        results = _lp.search(query, max_results=2)
        snippets = [str(r.get("text") or "").strip()[:300] for r in results if r.get("text")]
        return "\n".join(snippets) if snippets else ""
    except Exception:
        return ""


def propose_arcs(
    *,
    discovery_slots: dict[str, Any],
    project_context: str,
    conversation_history: str = "",
) -> dict[str, Any]:
    """Generate arc proposals grounded in discovery and LP library.

    Returns a dict with:
      arcs: list of {arc_key, name, reasoning, structure, lp_evidence}
      message: the Sheldon chat message to display
      metadata: {"kind": "arc_proposal", "arcs": [...]}
    """
    client = discovery_slots.get("client") if isinstance(discovery_slots.get("client"), dict) else {}
    client_name = str(client.get("name") or "the client").strip()
    client_industry = str(client.get("industry") or "").strip()
    outcome = discovery_slots.get("outcome") if isinstance(discovery_slots.get("outcome"), dict) else {}
    primary_outcome = str(outcome.get("primary") or "").strip()
    win_themes = discovery_slots.get("win_themes") if isinstance(discovery_slots.get("win_themes"), list) else []
    audience = str(discovery_slots.get("audience") or "").strip()

    domain_hint = f"{client_industry} {primary_outcome}".strip()

    # Fetch LP snippets for all three arcs upfront.
    lp_by_arc = {k: _lp_snippet_for_arc(k, domain_hint) for k in ARC_LIBRARY}

    arc_descriptions = "\n".join(
        f"{k}: {v['name']} — best for: {v['best_for']}"
        for k, v in ARC_LIBRARY.items()
    )

    system = (
        "You are Sheldon, a strategic consulting copilot helping to design a presentation narrative.\n"
        "Given the project context, recommend which 2 narrative arcs from the provided list are most appropriate.\n"
        "For each arc, give a 1-2 sentence reasoning that is SPECIFIC to this client and outcome — "
        "reference the client name, industry, audience, and win themes.\n"
        "Also give a 1-sentence personal recommendation for which arc to start with and why.\n"
        "Return JSON: {\"recommended_arcs\": [\"arc_key1\", \"arc_key2\"], "
        "\"reasoning\": {\"arc_key\": \"...\", ...}, "
        "\"recommendation\": \"arc_key\", "
        "\"recommendation_rationale\": \"...\"}"
    )
    user = (
        f"Client: {client_name}" + (f" ({client_industry})" if client_industry else "") + "\n"
        f"Primary outcome: {primary_outcome}\n"
        f"Win themes: {', '.join(str(t) for t in win_themes)}\n"
        f"Audience: {audience or 'not yet specified'}\n\n"
        f"Available arc options:\n{arc_descriptions}\n\n"
        f"Project context (LP / wiki):\n{project_context[:3000]}\n\n"
        f"Recent conversation:\n{conversation_history[-1500:]}"
    )

    try:
        payload = claude_generate_json(system=system, user=user, temperature=0.3, max_tokens=600)
    except Exception:
        payload = {}

    recommended_arcs: list[str] = []
    if isinstance(payload, dict):
        ra = payload.get("recommended_arcs")
        if isinstance(ra, list):
            recommended_arcs = [k for k in ra if k in ARC_LIBRARY]
    # Fallback: always offer SCQA + pyramid
    if not recommended_arcs:
        recommended_arcs = ["scqa", "pyramid"]

    reasoning_map = payload.get("reasoning") if isinstance(payload, dict) and isinstance(payload.get("reasoning"), dict) else {}
    recommendation = str((payload or {}).get("recommendation") or recommended_arcs[0]).strip()
    if recommendation not in ARC_LIBRARY:
        recommendation = recommended_arcs[0]
    recommendation_rationale = str((payload or {}).get("recommendation_rationale") or "").strip()

    arcs_out: list[dict[str, str]] = []
    for arc_key in recommended_arcs:
        arc_def = ARC_LIBRARY[arc_key]
        reasoning = str(reasoning_map.get(arc_key) or "").strip()
        if not reasoning:
            reasoning = f"Works well for {arc_def['best_for'].lower()}."
        arcs_out.append(
            {
                "arc_key": arc_key,
                "name": arc_def["name"],
                "structure": arc_def["structure"],
                "reasoning": reasoning,
                "lp_evidence": lp_by_arc.get(arc_key, ""),
                "is_recommended": arc_key == recommendation,
            }
        )

    # Build the Sheldon message.
    lines = [
        f"Good stuff — {client_name} on {primary_outcome} is a meaty brief. "
        "Before we lock in the slide structure, let's agree on the narrative spine. "
        "Here are the approaches I'd consider:\n"
    ]
    for arc in arcs_out:
        star = " ⭐ (my pick)" if arc["is_recommended"] else ""
        lines.append(f"**{arc['name']}**{star}")
        lines.append(arc["reasoning"])
        if arc["lp_evidence"]:
            lines.append(f"_(LP library: {arc['lp_evidence'][:120]}...)_")
        lines.append("")

    if recommendation_rationale:
        lines.append(f"My recommendation: **{ARC_LIBRARY[recommendation]['name']}** — {recommendation_rationale}")
    lines.append("\nWhich arc resonates with you, or would you like to adjust the framing?")

    message = "\n".join(lines).strip()

    return {
        "arcs": arcs_out,
        "message": message,
        "recommendation": recommendation,
        "metadata": {
            "kind": "arc_proposal",
            "arcs": arcs_out,
            "recommendation": recommendation,
        },
    }


def save_agreed_arc(
    db: Session,
    *,
    project_id: str,
    arc_key: str,
    arc_rationale: str = "",
) -> None:
    """Persist the agreed narrative arc as a MemoryItem (type=decision)."""
    value = json.dumps({"arc": arc_key, "rationale": arc_rationale, "agreed_at": datetime.now(IST).isoformat()})
    existing = (
        db.query(MemoryItem)
        .filter(
            MemoryItem.project_id == project_id,
            MemoryItem.memory_type == "decision",
            MemoryItem.key == "storyline_arc",
            MemoryItem.is_archived.is_(False),
        )
        .first()
    )
    if existing:
        existing.value = value
        existing.updated_at = datetime.now(IST).replace(tzinfo=None)
    else:
        db.add(
            MemoryItem(
                id=str(uuid.uuid4()),
                project_id=project_id,
                memory_type="decision",
                key="storyline_arc",
                value=value,
                confidence="high",
                source="chat",
                consent_state="allowed",
            )
        )
    db.flush()


def _fallback_contract(arc_key: str, target_slides: int) -> dict[str, Any]:
    """Minimal valid contract used when planning is disabled or the LLM fails."""
    arc_key = arc_key if arc_key in ARC_LIBRARY else "pyramid"
    return {
        "arc": arc_key,
        "governing_thought": "",
        "slides": [],
        "degraded": True,
    }


def validate_storyline_contract(contract: Any) -> tuple[bool, list[str]]:
    """Structural validation of a storyline contract. Returns (ok, issues)."""
    issues: list[str] = []
    if not isinstance(contract, dict):
        return False, ["contract is not an object"]
    if contract.get("arc") not in ARC_LIBRARY:
        issues.append(f"unknown arc: {contract.get('arc')!r}")
    slides = contract.get("slides")
    if not isinstance(slides, list) or not slides:
        issues.append("slides must be a non-empty list")
        return False, issues
    for i, s in enumerate(slides):
        if not isinstance(s, dict):
            issues.append(f"slide {i} is not an object")
            continue
        if not str(s.get("action_title") or "").strip():
            issues.append(f"slide {i} missing action_title")
        vis = str(s.get("suggested_visual") or "").strip()
        if vis and vis not in STORYLINE_VISUAL_VOCAB:
            issues.append(f"slide {i} suggested_visual {vis!r} not in vocabulary")
        ev = str(s.get("required_evidence") or "").strip()
        if evidence_requires_numeric_visual(ev) and vis and vis not in NUMERIC_VISUALS:
            issues.append(
                f"slide {i} has numeric required_evidence but suggested_visual "
                f"{vis!r} is not a quantitative layout"
            )
    return (not issues), issues


def build_storyline_contract(
    *,
    arc_key: str,
    discovery_slots: dict[str, Any],
    process_summary: str,
    enrichment: dict[str, Any] | None = None,
    target_slides: int = 10,
) -> dict[str, Any]:
    """Author a slide-by-slide narrative spine for the deck (Pillar A).

    Uses the planning-tier model with extended thinking. Each slide is assigned an
    action title (an assertion, not a topic label), its role in the chosen arc, the
    single key message, the evidence it must cite, and the visual it should use.

    Fail-open: returns a minimal contract (``degraded=True``) if planning is
    disabled or the LLM call fails, so callers never hard-fail on the spine.
    """
    arc_key = arc_key if arc_key in ARC_LIBRARY else "pyramid"
    if not getattr(settings, "storyline_contract_enabled", True) or not is_claude_enabled():
        return _fallback_contract(arc_key, target_slides)

    arc_def = ARC_LIBRARY[arc_key]
    client = discovery_slots.get("client") if isinstance(discovery_slots.get("client"), dict) else {}
    client_name = str(client.get("name") or "the client").strip()
    client_industry = str(client.get("industry") or "").strip()
    outcome = discovery_slots.get("outcome") if isinstance(discovery_slots.get("outcome"), dict) else {}
    primary_outcome = str(outcome.get("primary") or "").strip()
    win_themes = discovery_slots.get("win_themes") if isinstance(discovery_slots.get("win_themes"), list) else []
    audience = str(discovery_slots.get("audience") or "").strip()
    enrich_str = json.dumps(enrichment or {}, ensure_ascii=False)[:1200]

    system = (
        "You are a partner-level consulting storyliner building the narrative spine of a "
        "board-grade deck BEFORE any slide is drawn. Apply the Minto pyramid principle and the "
        "chosen arc rigorously.\n\n"
        f"Chosen arc: {arc_def['name']}\n"
        f"Arc structure: {arc_def['structure']}\n\n"
        "Rules (non-negotiable):\n"
        "1. Every action_title is a full ASSERTION that carries the argument (subject + verb + "
        "specific claim), never a topic label. BAD: 'Current State'. GOOD: 'Manual hand-offs add "
        "11 days and $2.4M of rework to every close'.\n"
        "2. One idea per slide. Supporting slides must be MECE and must ladder up to the "
        "governing_thought.\n"
        "3. Assign each slide a role_in_arc drawn from the chosen arc's stages.\n"
        "4. required_evidence must reference a metric/fact present in the process summary or "
        "enrichment data; if none exists, write 'assumption — to validate'. Never invent numbers.\n"
        "5. suggested_visual MUST be one of: " + ", ".join(STORYLINE_VISUAL_VOCAB) + ". Favour "
        "diagrams/data over bullets; use 'bullets' at most once. When required_evidence is a "
        "numeric claim ($, %, KPI, FTE, cycle time), suggested_visual MUST be one of: "
        + ", ".join(sorted(NUMERIC_VISUALS)) + ".\n\n"
        "Return ONLY JSON: {\"governing_thought\": \"...\", \"slides\": [{\"slide_number\": 1, "
        "\"action_title\": \"...\", \"role_in_arc\": \"...\", \"key_message\": \"...\", "
        "\"required_evidence\": \"...\", \"suggested_visual\": \"...\"}, ...]}"
    )
    user = (
        f"Client: {client_name}" + (f" ({client_industry})" if client_industry else "") + "\n"
        f"Primary outcome: {primary_outcome}\n"
        f"Audience: {audience or 'executive sponsors'}\n"
        f"Win themes: {', '.join(str(t) for t in win_themes) or 'n/a'}\n"
        f"Target slide count: ~{target_slides} content slides (title/divider slides extra).\n\n"
        f"Process summary:\n{process_summary[:3500]}\n\n"
        f"Enrichment / metrics:\n{enrich_str}"
    )

    try:
        res = claude_generate_with_thinking(
            system=system,
            user=user,
            model=planning_model(),
            budget_tokens=int(getattr(settings, "anthropic_planning_thinking_budget_tokens", 6000)),
            max_tokens=4096,
        )
        payload = _extract_first_json_object(str(res.get("text") or ""))
    except Exception as exc:  # noqa: BLE001 — fail-open onto the fallback spine
        logger.warning("storyline contract planning failed: %s", exc)
        return _fallback_contract(arc_key, target_slides)

    if not isinstance(payload, dict):
        return _fallback_contract(arc_key, target_slides)

    slides_raw = payload.get("slides") if isinstance(payload.get("slides"), list) else []
    slides: list[dict[str, Any]] = []
    for i, s in enumerate(slides_raw):
        if not isinstance(s, dict):
            continue
        vis = str(s.get("suggested_visual") or "").strip()
        ev = str(s.get("required_evidence") or "").strip()
        vis = coerce_numeric_visual(vis, ev)
        slides.append(
            {
                "slide_number": int(s.get("slide_number") or (i + 1)),
                "action_title": str(s.get("action_title") or "").strip(),
                "role_in_arc": str(s.get("role_in_arc") or "").strip(),
                "key_message": str(s.get("key_message") or "").strip(),
                "required_evidence": ev,
                "suggested_visual": vis,
            }
        )

    contract = {
        "arc": arc_key,
        "governing_thought": str(payload.get("governing_thought") or "").strip(),
        "slides": slides,
        "degraded": not bool(slides),
    }
    return contract


def persist_storyline_contract(run_dir: str | Path, contract: dict[str, Any]) -> str | None:
    """Write the contract to ``<run_dir>/storyline.json``. Fail-open; returns path or None."""
    try:
        p = Path(run_dir)
        p.mkdir(parents=True, exist_ok=True)
        out = p / "storyline.json"
        out.write_text(json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(out)
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not persist storyline contract: %s", exc)
        return None


def load_storyline_contract(run_dir: str | Path) -> dict[str, Any] | None:
    """Load ``<run_dir>/storyline.json`` if present. Fail-open; returns None on any error."""
    try:
        out = Path(run_dir) / "storyline.json"
        if not out.exists():
            return None
        data = json.loads(out.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("%s: suppressed error: %s", 'load_storyline_contract', exc)
        return None


def render_contract_for_prompt(contract: dict[str, Any], mode: str = "deck") -> str:
    """Format a contract as a compact, mandatory spine block for subagent prompts.

    ``mode="deck"`` renders the slide-oriented spine (visual vocab, slide types).
    ``mode="document"`` renders the same beats as prose-section guidance for the
    DOCX agent: beat → H2 section intent, key message → topic sentence, plus
    transition guidance — no visual vocab or slide-count language.

    Returns "" if the contract is empty/degraded so callers can skip injection.
    """
    if not isinstance(contract, dict):
        return ""
    slides = contract.get("slides") if isinstance(contract.get("slides"), list) else []
    if not slides:
        return ""
    arc = contract.get("arc") or ""
    gt = str(contract.get("governing_thought") or "").strip()
    if mode == "document":
        lines = [
            "APPROVED STORYLINE — this is the document's narrative spine, shared with the "
            "deck built from the same run. Structure the body so each beat below maps to one "
            "H2 section in this order. The beat's assertion is the section's argument: open "
            "the section with a topic sentence that states it, then support it with the "
            "required evidence. End each section with a one-sentence bridge into the next "
            "beat. Do not reorder, merge, or drop beats.",
        ]
        if arc:
            lines.append(f"Arc: {arc}")
        if gt:
            lines.append(f"Governing thought (the document must argue this): {gt}")
        lines.append("")
        for s in slides:
            if not isinstance(s, dict):
                continue
            n = s.get("slide_number")
            title = str(s.get("action_title") or "").strip()
            role = str(s.get("role_in_arc") or "").strip()
            msg = str(s.get("key_message") or "").strip()
            ev = str(s.get("required_evidence") or "").strip()
            lines.append(f"Beat {n}" + (f" [{role}]" if role else "") + f": {title}")
            if msg:
                lines.append(f"    topic sentence: {msg}")
            if ev:
                lines.append(f"    evidence: {ev}")
        return "\n".join(lines).strip()
    lines = [
        "APPROVED STORYLINE — this is the deck's spine. Honour it exactly: one slide per row, "
        "use the action_title verbatim as the slide title, and cite the required_evidence. "
        "Set each slide's slide_type to the value in [brackets] exactly — do not substitute an "
        "easier layout (no bullets/table when a richer visual is named). Do not reorder, merge, "
        "drop, or re-theme slides.",
    ]
    if arc:
        lines.append(f"Arc: {arc}")
    if gt:
        lines.append(f"Governing thought: {gt}")
    lines.append("")
    present_visuals: set[str] = set()
    for s in slides:
        if not isinstance(s, dict):
            continue
        n = s.get("slide_number")
        title = str(s.get("action_title") or "").strip()
        role = str(s.get("role_in_arc") or "").strip()
        vis = str(s.get("suggested_visual") or "").strip()
        ev = str(s.get("required_evidence") or "").strip()
        if vis:
            present_visuals.add(vis)
        lines.append(f"S{n} [{role} · {vis}] {title}")
        if ev:
            lines.append(f"    evidence: {ev}")

    # Field cheat-sheet for any rich visuals in this spine, so the drafting model
    # emits the inline fields each one needs (otherwise the figure silently falls
    # back to a bullet list). Only show the types that actually appear.
    rich_present = [v for v in _VISUAL_FIELD_HINTS if v in present_visuals]
    if rich_present:
        lines.append("")
        lines.append("Required fields for the named visuals:")
        for v in rich_present:
            lines.append(f"  {v} → {_VISUAL_FIELD_HINTS[v]}")
    return "\n".join(lines).strip()


_TONE_PACKS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("compliance", "audit", "regulat", "control", "governance", "risk", "bfsi",
         "bank", "insurance", "kyc", "aml", "sox"),
        "TONE: regulated-domain register. Be precise and control-oriented — name the "
        "control, owner, and evidence behind every assertion; prefer 'must' and 'is "
        "required' over aspirational language; quantify exposure before benefit; never "
        "celebrate the removal of checks, approvals, or decision gates.",
    ),
    (
        ("transformation", "growth", "automation", "efficiency", "digital", "modernis",
         "moderniz", "innovation", "savings", "productivity"),
        "TONE: change-narrative register. Lead with outcomes — state the size of the "
        "prize early, contrast current versus future state concretely, and make every "
        "recommendation an action with an owner and a horizon. Confident, not "
        "breathless: the numbers carry the argument.",
    ),
)


def tone_directive(domain_hint: str) -> str:
    """Pick a tone pack from domain keywords in the hint; "" when nothing matches.

    Word-prefix matching over the lowercased hint; the pack with the most keyword
    hits wins so mixed hints (e.g. 'risk automation') resolve deterministically.
    """
    hint = str(domain_hint or "").lower()
    if not hint.strip():
        return ""
    best_text, best_hits = "", 0
    for keywords, text in _TONE_PACKS:
        hits = sum(1 for k in keywords if k in hint)
        if hits > best_hits:
            best_text, best_hits = text, hits
    return best_text


def parse_arc_from_user_message(user_message: str) -> str | None:
    """Best-effort extraction of an arc key from the user's response.

    Returns the arc key if detected, None otherwise.
    """
    lowered = user_message.lower()
    if "scqa" in lowered or "situation" in lowered or "complication" in lowered:
        return "scqa"
    if "pyramid" in lowered or "governing thought" in lowered or "bottom line first" in lowered:
        return "pyramid"
    if "case for change" in lowered or "case-led" in lowered or "case led" in lowered or "momentum" in lowered:
        return "case_led"
    # Generic agreement — caller should use the recommended arc
    positives = ("sounds good", "go with that", "let's do that", "that works", "agree", "yes", "perfect", "great pick")
    if any(p in lowered for p in positives):
        return "__agree_with_recommendation__"
    return None
