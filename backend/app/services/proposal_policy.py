from __future__ import annotations

from typing import Any

PROPOSAL_SKILL_ID = "proposal_finance_transformation_v1"
PROPOSAL_OUTPUT_TYPES: tuple[str, ...] = ("docx", "pptx", "pdf")

_PROPOSAL_SIGNALS: tuple[str, ...] = (
    "proposal",
    "rfp",
    "pitch deck",
    "capability statement",
    "statement of work",
    "business case",
)

_FINANCE_TRANSFORMATION_SIGNALS: tuple[str, ...] = (
    "finance transformation",
    "finance operating model",
    "finance function",
    "fp&a",
    "close acceleration",
    "record to report",
    "order to cash",
    "procure to pay",
    "working capital",
    "treasury",
    "cfo",
    "controllership",
)


def _norm_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def has_proposal_intent(text: str) -> bool:
    lowered = _norm_text(text)
    return any(sig in lowered for sig in _PROPOSAL_SIGNALS)


def has_finance_transformation_intent(text: str) -> bool:
    lowered = _norm_text(text)
    return any(sig in lowered for sig in _FINANCE_TRANSFORMATION_SIGNALS)


def is_finance_proposal_intent(text: str) -> bool:
    lowered = _norm_text(text)
    return has_proposal_intent(lowered) and has_finance_transformation_intent(lowered)


# Map LLM domain labels → skill IDs.
# When adding a new domain-specific proposal skill, register it here.
_DOMAIN_TO_SKILL_ID: dict[str, str] = {
    "proposal_finance_transformation": PROPOSAL_SKILL_ID,
    # Future domain skills register here:
    # "proposal_operations": "proposal_operations_v1",
    # "proposal_product": "proposal_product_v1",
    # "proposal_generic": "proposal_generic_v1",
}


def derive_proposal_skill_targets(
    *,
    instruction: str,
    output_types: list[str],
    base_targets: dict[str, str] | None = None,
    llm_skill_hint: dict | None = None,
) -> dict[str, str]:
    """
    Determine which proposal skill to use for each output type.

    Uses a two-tier strategy:
      1. LLM classification hint (if available and confidence >= 0.6)
      2. Keyword matching fallback (original behaviour)

    The LLM hint is produced by _recommend_output_types() at zero extra cost
    (folded into the same API call). This handles edge cases where keyword
    detection misses intent (e.g., "pitch deck for our CFO-facing initiative"
    doesn't contain the exact phrase "finance transformation").
    """
    targets = {
        str(k).strip(): str(v).strip()
        for k, v in (base_targets or {}).items()
        if str(k).strip() and str(v).strip()
    }
    wanted = {str(x).strip().lower() for x in (output_types or []) if str(x).strip()}

    # Tier 1: LLM-based classification (higher accuracy, handles synonyms)
    if isinstance(llm_skill_hint, dict):
        domain = str(llm_skill_hint.get("domain") or "").strip()
        confidence = float(llm_skill_hint.get("confidence") or 0)
        skill_id = _DOMAIN_TO_SKILL_ID.get(domain)
        if skill_id and confidence >= 0.6:
            for out in PROPOSAL_OUTPUT_TYPES:
                if out in wanted:
                    targets[out] = skill_id
            return targets

    # Tier 2: Keyword matching fallback (original behaviour)
    if not is_finance_proposal_intent(instruction):
        return targets
    for out in PROPOSAL_OUTPUT_TYPES:
        if out in wanted:
            targets[out] = PROPOSAL_SKILL_ID
    return targets


def _discovery_brief(discovery: dict[str, Any] | None) -> dict[str, Any]:
    """Normalise discovery into a compact brief the outline generators can use."""
    discovery = discovery if isinstance(discovery, dict) else {}
    length_budget = discovery.get("length_budget") if isinstance(discovery.get("length_budget"), dict) else {}
    client = discovery.get("client") if isinstance(discovery.get("client"), dict) else {}
    outcome = discovery.get("outcome") if isinstance(discovery.get("outcome"), dict) else {}
    win_themes = discovery.get("win_themes") if isinstance(discovery.get("win_themes"), list) else []
    win_themes_text = ", ".join(str(x).strip() for x in win_themes if str(x).strip())[:300]
    return {
        "audience": str(discovery.get("audience") or "mixed").strip(),
        "narrative_arc": str(discovery.get("narrative_arc") or "pyramid").strip(),
        "tone": str(discovery.get("tone") or "consultative").strip(),
        "win_themes_text": win_themes_text or "N/A",
        "client_name": str(client.get("name") or "").strip() or "Unnamed client",
        "client_industry": str(client.get("industry") or "").strip() or "unspecified industry",
        "outcome_primary": str(outcome.get("primary") or "").strip(),
        "outcome_decision": str(outcome.get("decision") or "").strip(),
        "length_budget": length_budget,
    }


def generate_deck_outline_preview(
    *,
    instruction: str,
    output_type: str = "pptx",
    skill_id: str | None = None,
    discovery: dict[str, Any] | None = None,
    project_context: str | None = None,
) -> dict[str, Any] | None:
    """
    Generate a lightweight slide outline preview during plan creation.

    Returns a dict with 'slides' (list of {title, slide_type, purpose}) and
    'rationale' explaining the structure. Returns None if Claude is unavailable
    or the call fails — callers should treat this as optional enrichment.

    When ``project_context`` is provided (typically a planner excerpt built from
    wiki pages + project memory) the outline is grounded in that content.
    """
    try:
        from app.services.claude import claude_generate_json, is_claude_enabled
    except ImportError:
        return None
    if not is_claude_enabled():
        return None

    contract = proposal_prompt_contract(output_type, skill_id=skill_id)
    sections = contract.get("sections") or []

    brief = _discovery_brief(discovery)
    length_budget = brief["length_budget"]
    target_slides = int(length_budget.get("pptx")) if str(length_budget.get("pptx") or "").isdigit() else 10
    target_slides = max(6, min(target_slides, 20))

    system = (
        "You are a presentation strategist. Given a user instruction, required sections, "
        "and any project context (wiki excerpts, memory), produce a slide outline "
        "for a PowerPoint deck. Return JSON with keys:\n"
        "  slides: [{title: string, slide_type: string, purpose: string}]\n"
        "  rationale: string (1 sentence explaining the deck structure)\n"
        "slide_type must be one of: title, bullets, stat_cards, column_cards, stack_layers, table, chart, section_divider.\n"
        "purpose: 1 sentence (≤20 words) describing what the slide communicates.\n"
        "Titles must be specific and reference the client or their context when available — "
        "avoid generic headers like 'Introduction' or 'Our Approach'.\n"
        f"Produce exactly {target_slides} slides. Always start with a title slide and end with a next-steps slide."
    )
    ctx_block = ""
    if project_context:
        ctx_block = f"\n\nProject context (wiki + memory):\n{project_context[:4000]}\n"
    user = (
        f"Instruction: {instruction}\n\n"
        f"Required sections to cover: {', '.join(sections)}\n\n"
        f"Client: {brief['client_name']} ({brief['client_industry']})\n"
        f"Audience: {brief['audience']}\n"
        f"Narrative arc: {brief['narrative_arc']}\n"
        f"Tone: {brief['tone']}\n"
        f"Desired outcome: {brief['outcome_primary'] or 'N/A'}\n"
        f"Decision to drive: {brief['outcome_decision'] or 'N/A'}\n"
        f"Win themes: {brief['win_themes_text']}"
        f"{ctx_block}\n"
        "Generate the slide outline."
    )
    try:
        payload = claude_generate_json(system=system, user=user, temperature=0.3, max_tokens=1400)
        if not isinstance(payload, dict):
            return None
        slides = payload.get("slides")
        if not isinstance(slides, list) or not slides:
            return None
        outline_slides = []
        for s in slides:
            if not isinstance(s, dict):
                continue
            title = str(s.get("title") or "").strip()
            slide_type = str(s.get("slide_type") or "bullets").strip()
            purpose = str(s.get("purpose") or "").strip()
            if title:
                outline_slides.append({"title": title, "slide_type": slide_type, "purpose": purpose})
        if not outline_slides:
            return None
        return {
            "slides": outline_slides,
            "rationale": str(payload.get("rationale") or ""),
            "output_type": output_type,
            "skill_id": skill_id or PROPOSAL_SKILL_ID,
        }
    except Exception:
        return None


def generate_document_outline_preview(
    *,
    instruction: str,
    skill_id: str | None = None,
    discovery: dict[str, Any] | None = None,
    project_context: str | None = None,
) -> dict[str, Any] | None:
    """
    Generate a lightweight document (DOCX) outline preview during plan creation.

    Returns a dict with ``sections`` (list of
    ``{heading, purpose, key_points, evidence_pointer}``), a ``rationale`` string
    and a suggested ``target_pages``. Returns ``None`` if Claude is unavailable or
    the call fails — callers should treat this as optional enrichment.
    """
    try:
        from app.services.claude import claude_generate_json, is_claude_enabled
    except ImportError:
        return None
    if not is_claude_enabled():
        return None

    contract = proposal_prompt_contract("docx", skill_id=skill_id)
    sections_hint = contract.get("sections") or []

    brief = _discovery_brief(discovery)
    length_budget = brief["length_budget"]
    target_pages = int(length_budget.get("docx_pages")) if str(length_budget.get("docx_pages") or "").isdigit() else 8
    target_pages = max(4, min(target_pages, 20))

    system = (
        "You are a consulting-grade document strategist. Given a user instruction, the required "
        "section scaffold, and any project context (wiki + memory excerpts), produce a DOCX "
        "storyline outline. Return JSON with keys:\n"
        "  sections: [{heading: string, purpose: string, key_points: [string], evidence_pointer: string}]\n"
        "  rationale: string (1 sentence explaining how the arc lands the decision)\n"
        "  target_pages: number (integer, your recommended page count)\n"
        "Guidelines:\n"
        "- Headings must be specific to the client and their context — no generic 'Introduction'.\n"
        "- purpose: 1 sentence describing what this section persuades or informs.\n"
        "- key_points: 2–4 short phrases (≤12 words each) capturing the concrete substance.\n"
        "- evidence_pointer: short reference to what grounds this section "
        "(e.g. 'Wiki: Finance Ops Baseline', 'Client interview notes', 'Benchmark data').\n"
        "- Start with an executive summary section and end with recommended next steps.\n"
        f"- Aim for roughly {target_pages} pages overall, with 5–9 sections."
    )
    ctx_block = ""
    if project_context:
        ctx_block = f"\n\nProject context (wiki + memory):\n{project_context[:4000]}\n"
    user = (
        f"Instruction: {instruction}\n\n"
        f"Required section scaffold: {', '.join(sections_hint) if sections_hint else 'N/A'}\n\n"
        f"Client: {brief['client_name']} ({brief['client_industry']})\n"
        f"Audience: {brief['audience']}\n"
        f"Narrative arc: {brief['narrative_arc']}\n"
        f"Tone: {brief['tone']}\n"
        f"Desired outcome: {brief['outcome_primary'] or 'N/A'}\n"
        f"Decision to drive: {brief['outcome_decision'] or 'N/A'}\n"
        f"Win themes: {brief['win_themes_text']}"
        f"{ctx_block}\n"
        "Generate the document outline."
    )
    try:
        payload = claude_generate_json(system=system, user=user, temperature=0.3, max_tokens=1500)
        if not isinstance(payload, dict):
            return None
        raw_sections = payload.get("sections")
        if not isinstance(raw_sections, list) or not raw_sections:
            return None
        sections_out: list[dict[str, Any]] = []
        for section in raw_sections:
            if not isinstance(section, dict):
                continue
            heading = str(section.get("heading") or "").strip()
            if not heading:
                continue
            purpose = str(section.get("purpose") or "").strip()
            raw_points = section.get("key_points")
            key_points: list[str] = []
            if isinstance(raw_points, list):
                for kp in raw_points:
                    text = str(kp or "").strip()
                    if text:
                        key_points.append(text[:200])
                    if len(key_points) >= 6:
                        break
            evidence_pointer = str(section.get("evidence_pointer") or "").strip()
            sections_out.append(
                {
                    "heading": heading[:240],
                    "purpose": purpose[:280],
                    "key_points": key_points,
                    "evidence_pointer": evidence_pointer[:240],
                }
            )
        if not sections_out:
            return None
        resolved_pages = payload.get("target_pages")
        try:
            resolved_pages_int = int(resolved_pages)
        except (TypeError, ValueError):
            resolved_pages_int = target_pages
        resolved_pages_int = max(3, min(resolved_pages_int, 30))
        return {
            "sections": sections_out,
            "rationale": str(payload.get("rationale") or ""),
            "target_pages": resolved_pages_int,
            "output_type": "docx",
            "skill_id": skill_id or PROPOSAL_SKILL_ID,
        }
    except Exception:
        return None


def proposal_quality_policy(plan_payload: dict[str, Any] | None, requested_outputs: list[str] | None) -> dict[str, Any]:
    requested = {str(x).strip().lower() for x in (requested_outputs or []) if str(x).strip()}
    raw_targets = (plan_payload or {}).get("content_skill_targets") if isinstance(plan_payload, dict) else {}
    targets = raw_targets if isinstance(raw_targets, dict) else {}
    targeted_outputs = {
        str(k).strip().lower()
        for k, v in targets.items()
        if str(v).strip() == PROPOSAL_SKILL_ID and str(k).strip()
    }
    applicable_outputs = (requested & set(PROPOSAL_OUTPUT_TYPES)) | targeted_outputs
    return {
        "active": bool(applicable_outputs),
        "required_outputs": sorted(applicable_outputs),
        "qa_required": True,
        "guardrail_required": True,
        "visual_pass_statuses": ["pass", "warn", "skip"],
    }


def proposal_prompt_contract(
    output_type: str,
    *,
    skill_id: str | None = None,
    skill_card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Sections and constraints for proposal generation prompts.

    Prefers config/quality_contracts (registry + contract JSON). Falls back to
    built-in defaults only when no contract is registered for the skill/output pair.
    """
    from app.services.quality_contract_registry import build_prompt_bundle

    sid = str(skill_id or PROPOSAL_SKILL_ID).strip() or PROPOSAL_SKILL_ID
    bundle = build_prompt_bundle(skill_id=sid, output_type=output_type, skill_card=skill_card)
    if bundle and bundle.get("sections"):
        return {
            "output_type": bundle["output_type"],
            "sections": bundle["sections"],
            "constraints": bundle.get("constraints") or [],
            "contract_id": bundle.get("contract_id"),
        }
    common_sections = [
        "Executive Summary",
        "Current State and Problem Statement",
        "Target Operating Model",
        "Workstreams and Timeline",
        "Value Case",
        "Risks and Mitigations",
        "Governance and Team Structure",
        "Next Steps",
    ]
    return {
        "output_type": str(output_type or "").strip().lower(),
        "sections": common_sections,
        "constraints": [
            "Use quantified value levers where available; mark unknowns as [TBC] instead of inventing numbers.",
            "Ground recommendations in finance-transformation context and executive decision-making needs.",
            "Avoid generic consulting boilerplate and duplicate statements across sections.",
        ],
    }
