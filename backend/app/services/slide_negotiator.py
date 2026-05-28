"""SlideNegotiator — collaborative slide-by-slide deck construction.

Proposes one slide at a time based on the agreed narrative arc and
discovery slots. Each agreed slide is saved as a MemoryItem so the
final deck_outline_preview can be assembled from real decisions rather
than re-generated from scratch.
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

# Slide type display labels
SLIDE_TYPE_LABELS: dict[str, str] = {
    "title": "Title slide",
    "bullets": "Bullet points",
    "stat_cards": "Stat / metric cards",
    "column_cards": "Column cards",
    "stack_layers": "Stacked layers / journey",
    "table": "Comparison table",
    "chart": "Chart / graph",
    "big_number": "Big-number highlight",
    "process_flow": "Process flow",
    "section_divider": "Section divider",
}

# Narrative arc → default slide blueprints (title + purpose, filled in by LLM).
ARC_BLUEPRINTS: dict[str, list[dict[str, str]]] = {
    "scqa": [
        {"purpose": "Set the scene — stable context the audience already accepts"},
        {"purpose": "The disruption or complication that makes change necessary"},
        {"purpose": "The key question decision-makers must answer"},
        {"purpose": "The recommended answer / governing idea"},
        {"purpose": "Evidence supporting the answer — data, benchmarks, proof"},
        {"purpose": "Delivery roadmap — phases and milestones"},
        {"purpose": "Risks and mitigation"},
        {"purpose": "Next actions and decision required"},
    ],
    "pyramid": [
        {"purpose": "Governing thought — the single headline recommendation"},
        {"purpose": "Pillar 1 — first supporting argument"},
        {"purpose": "Pillar 2 — second supporting argument"},
        {"purpose": "Pillar 3 — third supporting argument"},
        {"purpose": "Evidence and data supporting the pillars"},
        {"purpose": "Implementation roadmap"},
        {"purpose": "Investment and commercial terms"},
        {"purpose": "Decision / call to action"},
    ],
    "case_led": [
        {"purpose": "Context — where are we starting from"},
        {"purpose": "Case for change — why the status quo is unsustainable"},
        {"purpose": "Desired outcomes — what success looks like"},
        {"purpose": "Our approach — the methodology and phases"},
        {"purpose": "Proof points — evidence we can deliver"},
        {"purpose": "Commercial proposal / investment"},
        {"purpose": "Next actions"},
    ],
}


def _word_overlap(a: str, b: str) -> float:
    """Jaccard word overlap between two strings. Returns 0.0–1.0."""
    stop = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "with", "is", "are", "this", "that", "by", "on"}
    wa = {w.lower().strip(".,;:") for w in a.split() if w.lower() not in stop and len(w) > 3}
    wb = {w.lower().strip(".,;:") for w in b.split() if w.lower() not in stop and len(w) > 3}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _lp_snippet_for_slide(purpose: str, domain_hint: str) -> str:
    query = f"{purpose} {domain_hint} consulting slide best practice"
    try:
        results = _lp.search(query, max_results=2)
        snippets = [str(r.get("text") or "").strip()[:250] for r in results if r.get("text")]
        return "\n".join(snippets)
    except Exception:
        return ""


def propose_slide(
    *,
    slide_index: int,
    total_slides: int,
    arc_key: str,
    discovery_slots: dict[str, Any],
    project_context: str,
    prior_slide_decisions: list[dict[str, Any]],
    user_feedback: str = "",
) -> dict[str, Any]:
    """Generate a proposal for slide N of the deck.

    Returns:
      slide: {slide_num, title, slide_type, key_message, evidence_source, sheldon_view}
      message: Sheldon chat message
      metadata: {"kind": "slide_proposal", "slide": {...}}
    """
    client = discovery_slots.get("client") if isinstance(discovery_slots.get("client"), dict) else {}
    client_name = str(client.get("name") or "the client").strip()
    outcome = discovery_slots.get("outcome") if isinstance(discovery_slots.get("outcome"), dict) else {}
    primary_outcome = str(outcome.get("primary") or "").strip()
    win_themes = discovery_slots.get("win_themes") if isinstance(discovery_slots.get("win_themes"), list) else []
    audience = str(discovery_slots.get("audience") or "senior executives").strip()

    blueprints = ARC_BLUEPRINTS.get(arc_key, ARC_BLUEPRINTS["scqa"])
    blueprint_index = min(slide_index, len(blueprints) - 1)
    purpose_hint = blueprints[blueprint_index]["purpose"]

    domain_hint = f"{client.get('industry', '')} {primary_outcome}".strip()
    lp_evidence = _lp_snippet_for_slide(purpose_hint, domain_hint)

    prior_titles = [str(d.get("title") or "") for d in prior_slide_decisions if d.get("title")]
    prior_summary = "\n".join(f"Slide {i+1}: {t}" for i, t in enumerate(prior_titles)) if prior_titles else "(none yet)"

    system = (
        "You are a strategic consulting copilot designing a deck slide-by-slide.\n"
        "Propose EXACTLY one slide that fits the purpose hint and is grounded in the client context.\n"
        "Be specific — name the client, reference win themes, suggest concrete content.\n"
        "If user_feedback is non-empty, incorporate it into the proposal.\n"
        "Return JSON: {\"title\": \"...\", \"slide_type\": \"...\", \"key_message\": \"...\", "
        "\"evidence_source\": \"...\", \"sheldon_view\": \"...\"}\n"
        f"slide_type must be one of: {', '.join(SLIDE_TYPE_LABELS.keys())}"
    )
    user = (
        f"Client: {client_name}" + (f" ({client.get('industry', '')})" if client.get("industry") else "") + "\n"
        f"Primary outcome: {primary_outcome}\n"
        f"Win themes: {', '.join(str(t) for t in win_themes)}\n"
        f"Audience: {audience}\n"
        f"Arc: {arc_key}\n"
        f"Slide {slide_index + 1} of {total_slides} — purpose: {purpose_hint}\n\n"
        f"Slides agreed so far:\n{prior_summary}\n\n"
        f"LP library excerpt:\n{lp_evidence[:500] if lp_evidence else '(none)'}\n\n"
        f"Project context:\n{project_context[:2000]}\n\n"
        + (f"User feedback to incorporate: {user_feedback}\n" if user_feedback.strip() else "")
    )

    try:
        payload = claude_generate_json(system=system, user=user, temperature=0.3, max_tokens=400)
    except Exception:
        payload = {}

    slide_type = str((payload or {}).get("slide_type") or "bullets").strip()
    if slide_type not in SLIDE_TYPE_LABELS:
        slide_type = "bullets"

    slide: dict[str, Any] = {
        "slide_num": slide_index + 1,
        "title": str((payload or {}).get("title") or f"Slide {slide_index + 1}").strip(),
        "slide_type": slide_type,
        "slide_type_label": SLIDE_TYPE_LABELS[slide_type],
        "key_message": str((payload or {}).get("key_message") or purpose_hint).strip(),
        "evidence_source": str((payload or {}).get("evidence_source") or "").strip(),
        "sheldon_view": str((payload or {}).get("sheldon_view") or "").strip(),
        "agreed": False,
    }

    # Build the Sheldon message.
    progress = f"Slide {slide_index + 1} of {total_slides}"
    lines = [f"**{progress}** — {slide['title']}"]
    lines.append(f"_Format: {slide['slide_type_label']}_")
    lines.append(f"**Key message:** {slide['key_message']}")
    if slide["evidence_source"]:
        lines.append(f"**Evidence / source:** {slide['evidence_source']}")
    if slide["sheldon_view"]:
        lines.append(f"**My view:** {slide['sheldon_view']}")
    if lp_evidence:
        lines.append(f"_LP library reference: {lp_evidence[:120].strip()}..._")

    # Warn if this slide's key_message overlaps heavily with a prior agreed slide.
    overlap_warning = ""
    new_km = slide["key_message"]
    for prior in prior_slide_decisions:
        prior_km = str(prior.get("key_message") or prior.get("title") or "")
        if prior_km and _word_overlap(new_km, prior_km) >= 0.5:
            prior_title = str(prior.get("title") or f"Slide {prior.get('slide_num', '?')}")
            overlap_warning = (
                f"\n⚠️ **Possible overlap** with **{prior_title}** — both slides cover similar ground. "
                "Should we merge them or give this one a distinct angle?"
            )
            break

    lines.append("\nDoes this work for you, or would you like to change anything?" + overlap_warning)
    message = "\n".join(lines).strip()

    return {
        "slide": slide,
        "message": message,
        "metadata": {"kind": "slide_proposal", "slide": slide},
    }


def save_agreed_slide(
    db: Session,
    *,
    project_id: str,
    slide: dict[str, Any],
) -> None:
    """Persist an agreed slide as a MemoryItem (type=decision, key=slide_N)."""
    slide_num = int(slide.get("slide_num") or 1)
    key = f"slide_{slide_num}"
    # strip display-only fields before persisting so they don't leak into the render payload
    _render_fields = {k: v for k, v in slide.items() if k not in ("slide_type_label", "sheldon_view")}
    value = json.dumps({**_render_fields, "agreed": True, "agreed_at": datetime.now(IST).isoformat()})

    existing = (
        db.query(MemoryItem)
        .filter(
            MemoryItem.project_id == project_id,
            MemoryItem.memory_type == "decision",
            MemoryItem.key == key,
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
                key=key,
                value=value,
                confidence="high",
                source="chat",
                consent_state="allowed",
            )
        )
    db.flush()


def load_agreed_slides(db: Session, *, project_id: str) -> list[dict[str, Any]]:
    """Load all agreed slide decisions for this project, ordered by slide_num."""
    rows = (
        db.query(MemoryItem)
        .filter(
            MemoryItem.project_id == project_id,
            MemoryItem.memory_type == "decision",
            MemoryItem.key.like("slide_%"),
            MemoryItem.is_archived.is_(False),
        )
        .all()
    )
    slides: list[dict[str, Any]] = []
    for row in rows:
        try:
            data = json.loads(row.value)
            if isinstance(data, dict):
                slides.append(data)
        except Exception:
            pass
    slides.sort(key=lambda s: int(s.get("slide_num") or 0))
    return slides


def assemble_outline_from_decisions(db: Session, *, project_id: str) -> list[dict[str, str]]:
    """Convert agreed slide MemoryItems into the deck_outline_preview format expected by the PPTX agent."""
    agreed = load_agreed_slides(db, project_id=project_id)
    return [
        {
            "title": str(s.get("title") or f"Slide {s.get('slide_num', i + 1)}"),
            "slide_type": str(s.get("slide_type") or "bullets"),
            "purpose": str(s.get("key_message") or ""),
            "evidence_source": str(s.get("evidence_source") or ""),
        }
        for i, s in enumerate(agreed)
    ]


def parse_slide_feedback(user_message: str) -> str:
    """Return 'agree', 'modify', or 'unclear' based on the user message."""
    lowered = user_message.lower()
    agree_signals = ("yes", "agree", "that works", "looks good", "perfect", "go with", "let's go", "sounds good", "approved", "✓", "👍")
    modify_signals = ("change", "modify", "instead", "rather", "not quite", "tweak", "update", "rename", "different", "adjust")
    if any(s in lowered for s in agree_signals):
        return "agree"
    if any(s in lowered for s in modify_signals):
        return "modify"
    return "agree"  # default optimistic: treat unrecognised short responses as agree
