"""Typed per-agent inputs/outputs (Cowork Phase 3 isolation)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.core.state import ProcessDocState


@dataclass
class AgentContext:
    """Immutable inputs for a single output-type worker (read-only snapshot fields)."""

    output_type: str
    project_id: str | None
    run_id: str | None
    user_id: str | None
    raw_text: str
    user_instruction: str
    user_intent_original: str  # Immutable clean user intent; never contains run-time annotations
    process_model: dict[str, Any]
    assembled_context: str
    output_type_representations: dict[str, Any]
    skill_instructions_by_output: dict[str, str]
    skill_card: dict[str, Any]
    plan_payload: dict[str, Any]
    prior_artifacts_excerpt: str = ""
    conversation_digest: str = ""
    enrichment: Any | None = None
    branding: Any | None = None
    deliverable_metadata: Any | None = None
    emit_event: Callable[[str, dict[str, Any]], None] | None = None
    swarm_teammate_id: str | None = None

    def get_intent_for_narrative(self) -> str:
        intent = getattr(self.enrichment, "user_intent", None)
        return str(getattr(intent, "value", intent or "general"))

    def get_audience_hints(self) -> str:
        audience = str(getattr(self.enrichment, "audience_type", "general") or "general")
        if audience == "executive":
            return "Your audience is senior executives prioritizing strategic impact and ROI."
        if audience == "operational":
            return "Your audience is operations teams prioritizing clarity, roles, and execution details."
        return "Your audience is mixed; balance strategic framing and practical details."

    def get_risk_focus(self) -> str:
        rp = getattr(self.enrichment, "risk_profile", None)
        risks = getattr(rp, "risks", []) if rp is not None else []
        if isinstance(risks, list) and risks:
            names = [str((r or {}).get("name") or r) for r in risks[:3]]
            return "Key risks to address: " + ", ".join(n for n in names if n)
        return ""

    def get_value_emphasis(self) -> str:
        drivers = getattr(self.enrichment, "value_drivers", [])
        if isinstance(drivers, list) and drivers:
            names = [str((d or {}).get("name") or d) for d in drivers[:3]]
            return "Value drivers to emphasize: " + ", ".join(n for n in names if n)
        return ""


@dataclass
class AgentOutput:
    """Partial state updates from one sub-agent plus optional tool provenance."""

    updates: dict[str, Any]
    tool_trace: list[dict[str, Any]] = field(default_factory=list)


def build_agent_context(state: ProcessDocState, output_type: str) -> AgentContext:
    sc = state.get("skill_card") if isinstance(state.get("skill_card"), dict) else {}
    otr = state.get("output_type_representations") if isinstance(state.get("output_type_representations"), dict) else {}
    si = state.get("skill_instructions_by_output") if isinstance(state.get("skill_instructions_by_output"), dict) else {}
    pm = state.get("process_model") if isinstance(state.get("process_model"), dict) else {}
    pp = state.get("plan_payload")
    plan_payload = pp if isinstance(pp, dict) else {}
    prior_parts: list[str] = []
    nm = state.get("narrative_md")
    if isinstance(nm, str) and nm.strip():
        prior_parts.append("## Narrative or executive briefing (markdown excerpt)\n" + nm.strip()[:2800])
    dm = state.get("docx_markdown")
    if isinstance(dm, str) and dm.strip():
        prior_parts.append("## Related Word document draft (markdown excerpt)\n" + dm.strip()[:2800])
    pdf_md = state.get("pdf_markdown")
    if isinstance(pdf_md, str) and pdf_md.strip():
        prior_parts.append("## Related PDF draft (markdown excerpt)\n" + pdf_md.strip()[:2000])
    prior_artifacts_excerpt = "\n\n".join(prior_parts)[:7000]
    swarm_teammate_id: str | None = None
    s_map = state.get("swarm_teammate_by_output")
    if isinstance(s_map, dict):
        raw_tm = s_map.get(output_type)
        if raw_tm is not None and str(raw_tm).strip():
            swarm_teammate_id = str(raw_tm).strip()
    return AgentContext(
        output_type=output_type,
        project_id=state.get("project_id"),
        run_id=state.get("run_id"),
        user_id=state.get("user_id"),
        raw_text=str(state.get("raw_text") or ""),
        user_instruction=str(state.get("user_instruction") or ""),
        user_intent_original=str(state.get("user_intent_original") or state.get("user_instruction") or ""),
        process_model=pm,
        assembled_context=str(state.get("assembled_context") or ""),
        output_type_representations=otr,
        skill_instructions_by_output={str(k): str(v) for k, v in si.items()},
        skill_card=sc,
        plan_payload=plan_payload,
        prior_artifacts_excerpt=prior_artifacts_excerpt,
        conversation_digest=str(state.get("conversation_digest") or ""),
        enrichment=state.get("content_enrichment"),
        branding=state.get("branding_context"),
        deliverable_metadata=state.get("deliverable_metadata_by_output_type", {}).get(output_type)
        if isinstance(state.get("deliverable_metadata_by_output_type"), dict)
        else None,
        emit_event=state.get("_emit_run_event"),
        swarm_teammate_id=swarm_teammate_id,
    )


def merge_agent_output(state: ProcessDocState, out: AgentOutput) -> None:
    state.update(out.updates)
