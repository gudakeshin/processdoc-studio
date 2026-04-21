from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.services.claude import claude_generate_json

RouterIntent = Literal[
    "greeting",
    "ack",
    "smalltalk",
    "commit",
    "discovery_answer",
    "clarify",
    "refine",
    "out_of_scope",
]


@dataclass
class RouterDecision:
    intent: RouterIntent
    confidence: float
    extracted_slots: dict[str, Any]
    output_types: list[str]
    representations: dict[str, str]
    content_skill_hint: dict[str, Any] | None
    next_state: str
    missing_slots: list[str]
    reply_hint: str | None
    rationale: str


def _safe_state(raw: str) -> str:
    v = str(raw or "").strip().lower()
    if v in {"new", "exploring", "discovery", "ready_to_plan", "plan_proposed", "confirming", "done"}:
        return v
    return "exploring"


def _missing_slots(slots: dict[str, Any]) -> list[str]:
    client = slots.get("client") if isinstance(slots.get("client"), dict) else {}
    outcome = slots.get("outcome") if isinstance(slots.get("outcome"), dict) else {}
    win_themes = slots.get("win_themes") if isinstance(slots.get("win_themes"), list) else []
    missing: list[str] = []
    if not str(client.get("name") or "").strip():
        missing.append("client")
    if not str(outcome.get("primary") or "").strip():
        missing.append("outcome")
    if not [str(x).strip() for x in win_themes if str(x).strip()]:
        missing.append("win_themes")
    return missing


def fallback_decision(
    *,
    state: str,
    slots: dict[str, Any],
    reason: str,
) -> RouterDecision:
    missing = _missing_slots(slots)
    next_state = "discovery" if state == "discovery" or missing else _safe_state(state)
    intent: RouterIntent = "clarify"
    if state == "discovery" or missing:
        intent = "discovery_answer"
    return RouterDecision(
        intent=intent,
        confidence=0.0,
        extracted_slots={},
        output_types=[],
        representations={},
        content_skill_hint=None,
        next_state=next_state,
        missing_slots=missing,
        reply_hint="Continue current state and ask only for missing discovery slots.",
        rationale=reason,
    )


def route_turn(
    *,
    user_message: str,
    conv_state: str,
    conv_slots: dict[str, Any],
    recent_messages: list[dict[str, Any]],
    project_context: str,
    available_output_types: list[dict[str, Any]],
) -> RouterDecision:
    catalog = [
        {
            "output_type_id": str(item.get("output_type_id")),
            "display_name": str(item.get("display_name") or item.get("output_type_id") or ""),
            "description": str(item.get("description") or ""),
        }
        for item in available_output_types
        if isinstance(item, dict) and isinstance(item.get("output_type_id"), str)
    ]
    system = (
        "You are a deterministic conversation router for a consulting copilot.\n"
        "Return ONLY JSON with keys:\n"
        "intent, confidence, extracted_slots, output_types, representations, content_skill_hint, "
        "next_state, missing_slots, reply_hint, rationale.\n\n"
        "intent enum: greeting|ack|smalltalk|commit|discovery_answer|clarify|refine|out_of_scope.\n"
        "next_state enum: new|exploring|discovery|ready_to_plan|plan_proposed|confirming|done.\n"
        "Only include output_types from catalog.\n"
        "If current_state is discovery or there are missing proposal slots, prefer intent=discovery_answer/commit "
        "rather than out_of_scope.\n"
        "Use out_of_scope ONLY for clear unsupported asks with high certainty.\n"
        "extracted_slots JSON shape (optional fields): "
        "{client:{name,industry}, outcome:{primary,decision}, win_themes:[...], audience, narrative_arc, tone}.\n"
        "missing_slots values should come from: client, outcome, win_themes.\n"
    )
    user = (
        f"Current state: {conv_state}\n\n"
        f"Current slots: {conv_slots}\n\n"
        f"Recent messages: {recent_messages[-8:]}\n\n"
        f"Project context (wiki/memory excerpt):\n{project_context[:12000]}\n\n"
        f"Available output type catalog: {catalog}\n\n"
        f"Latest user message:\n{user_message}"
    )
    try:
        payload = claude_generate_json(system=system, user=user, temperature=0.1, max_tokens=900)
    except Exception:
        return fallback_decision(state=conv_state, slots=conv_slots, reason="router_llm_unavailable")
    if not isinstance(payload, dict):
        return fallback_decision(state=conv_state, slots=conv_slots, reason="router_invalid_payload")

    intent = str(payload.get("intent") or "").strip().lower()
    if intent not in {"greeting", "ack", "smalltalk", "commit", "discovery_answer", "clarify", "refine", "out_of_scope"}:
        return fallback_decision(state=conv_state, slots=conv_slots, reason="router_invalid_intent")
    confidence = float(payload.get("confidence") or 0.0)
    extracted_slots = payload.get("extracted_slots")
    output_types = payload.get("output_types")
    representations = payload.get("representations")
    content_skill_hint = payload.get("content_skill_hint")
    next_state = _safe_state(str(payload.get("next_state") or conv_state))
    missing_slots = payload.get("missing_slots")
    reply_hint = payload.get("reply_hint")
    rationale = str(payload.get("rationale") or "").strip()

    allowed = {str(item.get("output_type_id")) for item in catalog}
    normalized_types = [str(x) for x in (output_types if isinstance(output_types, list) else []) if str(x) in allowed]
    normalized_representations = {
        str(k): str(v)
        for k, v in (representations.items() if isinstance(representations, dict) else [])
        if str(k) in set(normalized_types)
    }
    if isinstance(missing_slots, list):
        normalized_missing = [str(x).strip() for x in missing_slots if str(x).strip() in {"client", "outcome", "win_themes"}]
    else:
        normalized_missing = _missing_slots(conv_slots if isinstance(conv_slots, dict) else {})

    if confidence < 0.45:
        return fallback_decision(state=conv_state, slots=conv_slots, reason="router_low_confidence")

    return RouterDecision(
        intent=intent,
        confidence=max(0.0, min(1.0, confidence)),
        extracted_slots=extracted_slots if isinstance(extracted_slots, dict) else {},
        output_types=normalized_types,
        representations=normalized_representations,
        content_skill_hint=content_skill_hint if isinstance(content_skill_hint, dict) else None,
        next_state=next_state,
        missing_slots=normalized_missing,
        reply_hint=str(reply_hint).strip() if reply_hint else None,
        rationale=rationale,
    )
