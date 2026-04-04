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


def derive_proposal_skill_targets(
    *,
    instruction: str,
    output_types: list[str],
    base_targets: dict[str, str] | None = None,
) -> dict[str, str]:
    targets = {
        str(k).strip(): str(v).strip()
        for k, v in (base_targets or {}).items()
        if str(k).strip() and str(v).strip()
    }
    if not is_finance_proposal_intent(instruction):
        return targets
    wanted = {str(x).strip().lower() for x in (output_types or []) if str(x).strip()}
    for out in PROPOSAL_OUTPUT_TYPES:
        if out in wanted:
            targets[out] = PROPOSAL_SKILL_ID
    return targets


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
