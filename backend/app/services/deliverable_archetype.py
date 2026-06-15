"""Deliverable archetype detection for intent-aware content generation."""

from __future__ import annotations

import re
from typing import Any, Literal

from app.services.proposal_policy import has_proposal_intent

Archetype = Literal["process_doc", "advisory_pov", "proposal"]

_ADVISORY_SIGNALS: tuple[str, ...] = (
    "point of view",
    "point-of-view",
    "pov note",
    "pov on",
    "advisory note",
    "whitepaper",
    "white paper",
    "perspective on",
    "interventions for",
    "thought leadership",
    "executive brief on",
    "position paper",
)

_META_STEP_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"\bdevelop\b.*\b(pov|point of view|document|deck|note)\b",
        r"\bdesign\b.*\b(workflow|document)\b",
        r"\breview\b.*\b(document|deck|note|findings)\b",
        r"\bcreate\b.*\b(presentation|deck|pptx|powerpoint)\b",
        r"\bwrite\b.*\b(document|note|report)\b",
        r"\bproduce\b.*\b(deliverable|deck|document)\b",
    )
)

_META_TOOLS: frozenset[str] = frozenset(
    {
        "powerpoint",
        "pptx",
        "word",
        "docx",
        "microsoft word",
        "microsoft powerpoint",
    }
)

_META_OUTPUTS: frozenset[str] = frozenset(
    {
        "point of view note",
        "point of view document",
        "pov note",
        "executive deck",
        "presentation deck",
    }
)


def detect_deliverable_archetype(
    instruction: str,
    *,
    plan_payload: dict[str, Any] | None = None,
    skill_card: dict[str, Any] | None = None,
) -> Archetype:
    """Classify the deliverable intent from instruction and plan metadata."""
    plan = plan_payload if isinstance(plan_payload, dict) else {}
    override = str(plan.get("deliverable_archetype") or "").strip().lower()
    if override in {"process_doc", "advisory_pov", "proposal"}:
        return override  # type: ignore[return-value]

    skill = skill_card if isinstance(skill_card, dict) else {}
    skill_archetype = str(skill.get("deliverable_archetype") or "").strip().lower()
    if skill_archetype in {"process_doc", "advisory_pov", "proposal"}:
        return skill_archetype  # type: ignore[return-value]

    lowered = " ".join((instruction or "").lower().split())
    if any(sig in lowered for sig in _ADVISORY_SIGNALS):
        return "advisory_pov"
    if has_proposal_intent(lowered):
        return "proposal"
    return "process_doc"


def is_meta_process_model(pm: dict[str, Any] | None) -> bool:
    """True when steps describe document production rather than a business process."""
    if not isinstance(pm, dict):
        return False
    steps = pm.get("steps") if isinstance(pm.get("steps"), list) else []
    if not steps:
        return False

    meta_hits = 0
    for step in steps:
        if not isinstance(step, dict):
            continue
        name = str(step.get("name") or "")
        notes = str(step.get("notes") or "")
        blob = f"{name} {notes}".lower()
        if any(pat.search(blob) for pat in _META_STEP_PATTERNS):
            meta_hits += 1
        tools = [str(t).lower() for t in (step.get("tools") or []) if str(t).strip()]
        if any(t in _META_TOOLS for t in tools):
            meta_hits += 1
        outputs = [str(o).lower() for o in (step.get("outputs") or []) if str(o).strip()]
        if any(o in _META_OUTPUTS or "point of view" in o for o in outputs):
            meta_hits += 1

    roles = [str(r).lower() for r in (pm.get("roles") or []) if str(r).strip()]
    has_doc_role = any(r in {"ai agent", "content author", "document author"} for r in roles)
    return meta_hits >= 2 or (meta_hits >= 1 and has_doc_role)


def archetype_prompt_block(archetype: Archetype, output_type: str) -> str:
    """Appendable prompt guidance keyed by archetype and output channel."""
    out = output_type.strip().lower()
    if archetype == "advisory_pov":
        if out == "pptx":
            return (
                "\n\nDELIVERABLE ARCHETYPE: advisory point-of-view deck.\n"
                "Content MUST describe the client's subject-domain process (e.g. Record-to-Report: "
                "journals → intercompany → reconciliation → close → consolidation → reporting), "
                "NOT the meta-workflow of writing or producing this deck.\n"
                "Required storyline: why-now; client process landscape; per-stage agentic intervention map; "
                "value hypothesis; risks and controls; 90-day path.\n"
                "Inline source labels on factual claims, e.g. '(source: internal estimate; illustrative)' "
                "when ungrounded. Close with a 'Sources and assumptions' slide."
            )
        if out == "docx":
            return (
                "\n\nDELIVERABLE ARCHETYPE: advisory point-of-view note.\n"
                "Write about the client's domain process and AI intervention opportunities — "
                "never about creating documents, decks, or POV production steps.\n"
                "Include: executive summary, domain process landscape, intervention map by stage, "
                "value hypothesis, risks, and recommended path.\n"
                "Add inline '(source: ...)' markers on key claims and end with an H2 "
                "'## Sources and assumptions'."
            )
        return (
            "\n\nDELIVERABLE ARCHETYPE: advisory point-of-view. "
            "Focus on subject-domain content, not document-production workflow."
        )
    if archetype == "proposal":
        return (
            "\n\nDELIVERABLE ARCHETYPE: client proposal. "
            "Emphasize client outcomes, approach, and evidence-backed recommendations."
        )
    return ""
