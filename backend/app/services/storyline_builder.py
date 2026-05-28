"""StorylineBuilder — collaborative narrative arc proposal.

Given discovery slots and project context (LP library + wiki), proposes
2–3 narrative arc options with explicit reasoning. Saves the agreed arc
as a MemoryItem so it is available to the PPTX agent and any future run.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from app.core.tz import IST
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import MemoryItem
from app.services.claude import claude_generate_json
from app.services.leading_practices import leading_practice_library_service as _lp

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
