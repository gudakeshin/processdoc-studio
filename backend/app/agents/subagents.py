"""Specialist sub-agents: Claude-backed generation (with deterministic fallbacks)."""

from __future__ import annotations

import hashlib
import html
import json
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.agents.agent_types import AgentContext, AgentOutput
from app.agents.prompt_hygiene import (
    UNTRUSTED_SKILL_SYSTEM_NOTE,
    context_excerpt_block,
    process_model_json_block,
    wrap_untrusted,
    wrap_untrusted_bundle,
)
from app.core.config import settings
from app.core.state import ProcessDocState, ProcessModel
from app.services.claude import (
    _extract_first_json_object,
    claude_generate,
    claude_generate_json,
    claude_generate_with_thinking,
    is_claude_enabled,
)
from app.services.claude_tools import run_subagent_tool_loop
from app.services.drawio_builder import process_model_to_drawio_xml
from app.services.observability import increment
from app.services.process_extraction import extract_process_model
from app.services.proposal_policy import PROPOSAL_SKILL_ID, proposal_prompt_contract
from app.services.tool_registry import (
    anthropic_tool_definitions,
    default_tools_for_output_type,
    tool_names_for_skill,
)

_SWARM_TOOL_NAMES: tuple[str, ...] = (
    "swarm_list_tasks",
    "swarm_create_task",
    "swarm_update_task",
    "swarm_list_messages",
    "swarm_send_message",
    "swarm_broadcast",
)

_DEBUG_LOG_PATH = Path("/Users/pallavchaturvedi/Agentic Projects/Process Doc v2/.cursor/debug-a9841a.log")
_DEBUG_SESSION_ID = "a9841a"


def _append_conversation_digest_block(user: str, ctx: AgentContext) -> str:
    extra_parts: list[str] = []
    d = (ctx.conversation_digest or "").strip()
    if d:
        cap = max(0, int(settings.subagent_conversation_digest_max_chars))
        if cap > 0:
            extra_parts.append(f"## Confirmed conversation (digest)\n{d[:cap]}")

    # Shared enrichment is now passed via AgentContext; include compact hints for all agents.
    if ctx.enrichment is not None:
        audience = ctx.get_audience_hints().strip()
        risk = ctx.get_risk_focus().strip()
        value = ctx.get_value_emphasis().strip()
        analytics = getattr(ctx.enrichment, "process_analytics", None)
        metrics: list[str] = []
        if analytics is not None:
            metrics.append(f"steps={getattr(analytics, 'steps_count', 0)}")
            metrics.append(f"roles={getattr(analytics, 'roles_count', 0)}")
            metrics.append(f"decisions={getattr(analytics, 'decision_points', 0)}")
        lines = [x for x in [audience, risk, value, ("Process analytics: " + ", ".join(metrics)) if metrics else ""] if x]
        if lines:
            extra_parts.append("## Shared enrichment\n" + "\n".join(f"- {ln}" for ln in lines))

    if not extra_parts:
        return user
    cap = max(0, int(settings.subagent_conversation_digest_max_chars))
    if cap <= 0 and d:
        return user
    bundle = "\n\n".join(extra_parts).strip()
    wrapped = wrap_untrusted("conversation_digest_and_enrichment", bundle)
    return f"{user}\n\n{wrapped}\n" if wrapped else user


def _session_debug_log(*, run_id: str | None, hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    try:
        payload = {
            "sessionId": _DEBUG_SESSION_ID,
            "runId": str(run_id or ""),
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:  # noqa: S110 — best-effort, non-fatal
        pass


def _normalize_drawio_xml(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    if text.startswith("&lt;"):
        text = html.unescape(text)
    if "<mxGraphModel" not in text and "<mxfile" not in text:
        return None
    start = text.find("<mxfile")
    if start == -1:
        start = text.find("<mxGraphModel")
    if start > 0:
        text = text[start:].strip()
    return text


def run_process_extraction(state: ProcessDocState) -> ProcessDocState:
    # Use the immutable original intent to avoid contamination from QA/guardrail annotations
    raw = state.get("user_intent_original") or state.get("raw_text") or ""
    ctx = state.get("assembled_context") or ""

    if is_claude_enabled():
        system = (
            "You are a process extraction engine. "
            "Your sole output is a single JSON object — no preamble, no explanation, no markdown fences. "
            "If any field has no data, use an empty array [] or empty string \"\", never null or omit the key. "
            "Step IDs must follow the pattern 's1', 's2', ..., 'sN' in order of appearance. "
            "Decision IDs must follow the pattern 'd1', 'd2', ..., 'dN'. "
            "Every step referenced in decisions.true_path or decisions.false_path must exist in steps[*].id. "
            "Every step referenced in swimlanes[role] must exist in steps[*].id."
        )
        user = (
            "Extract a structured process model from the instruction and context below.\n\n"
            "Return a JSON object with EXACTLY these top-level keys (no others):\n\n"
            "  process_name   string — the process title; infer from heading, first sentence, or topic if not explicit\n"
            "  roles          string[] — every distinct human role that performs a step; omit system names and tools\n"
            "  steps          ProcessStep[] — one entry per discrete action in execution order\n"
            "  decisions      DecisionBranch[] — one entry per conditional fork; empty [] if none\n"
            "  swimlanes      { [role: string]: string[] } — maps each role to its step IDs in order\n"
            "  metrics        MetricFact[] — every quantified fact in the text (time, count, %, currency, volume); "
            "empty [] if no numeric data present\n"
            "  metadata       { [key: string]: string } — any named attributes (e.g. 'frequency', 'owner', 'SLA') "
            "found in the text; empty {} if none\n\n"
            "ProcessStep schema:\n"
            "  id               string — 's1', 's2', ..., 'sN'\n"
            "  name             string — imperative verb phrase, ≤10 words (e.g. 'Collect KYC documents')\n"
            "  role             string — role from roles[]; 'TBD' if not specified\n"
            "  inputs           string[] — named artifacts or data consumed by this step; [] if none\n"
            "  outputs          string[] — named artifacts or data produced by this step; [] if none\n"
            "  tools            string[] — systems, apps, or tools used in this step; [] if none\n"
            "  duration_estimate string — e.g. '2 hours', '1 day'; \"\" if not specified\n"
            "  notes            string — any caveats, exceptions, or extra detail; \"\" if none\n\n"
            "DecisionBranch schema:\n"
            "  id         string — 'd1', 'd2', ...\n"
            "  condition  string — the yes/no question at the fork (e.g. 'Documents complete?')\n"
            "  true_path  string[] — step IDs taken when condition is true\n"
            "  false_path string[] — step IDs taken when condition is false\n\n"
            "MetricFact schema:\n"
            "  stat    string — the value/number (e.g. '12 days', '94%', 'INR 50,000', '3')\n"
            "  label   string — what it measures in 2–5 words (e.g. 'Invoice Cycle Time', 'Error Rate')\n"
            "  source  string — one of: 'client-provided data' | 'benchmark assumptions' | 'inferred from context'\n\n"
            "Edge-case rules:\n"
            "  - If no numbered or bulleted steps exist, infer steps from verbs in the text (minimum 1 step).\n"
            "  - If no roles are named, use ['Process Owner'] as the sole role and assign all steps to it.\n"
            "  - Do not invent steps that are not implied by the source text.\n\n"
            f"Instruction:\n{wrap_untrusted('user_instruction', str(raw))}\n\n"
            f"Context:\n{wrap_untrusted('assembled_context', str(ctx))}\n"
        )
        try:
            pm = claude_generate_json(system=system, user=user, temperature=0.2, max_tokens=2500)
            if isinstance(pm, dict) and isinstance(pm.get("steps"), list):
                state["process_model"] = pm  # type: ignore[assignment]
                return state
        except Exception:  # noqa: BLE001, S110 — fallback
            pass

    state["process_model"] = extract_process_model(raw, ctx)
    return state


def _model(ctx: AgentContext) -> ProcessModel:
    return ctx.process_model or extract_process_model(ctx.raw_text, ctx.assembled_context)


def _pref(ctx: AgentContext, key: str, default: str) -> str:
    prefs = ctx.output_type_representations or {}
    if not isinstance(prefs, dict):
        return default
    value = str(prefs.get(key) or "").strip().lower()
    return value or default


def _skill_instruction(ctx: AgentContext, output_type: str) -> str:
    all_instr = ctx.skill_instructions_by_output or {}
    if not isinstance(all_instr, dict):
        return ""
    text = str(all_instr.get(output_type) or "").strip()
    return text


def _drawio_context_hints(ctx: AgentContext, limit: int = 800) -> str:
    """Extract section headings + first content line from assembled_context for DrawIO hints."""
    ctx_text = ctx.assembled_context or ""
    if not ctx_text:
        return ""
    lines = ctx_text.split("\n")
    hints: list[str] = []
    for i, line in enumerate(lines):
        if line.startswith("## "):
            hints.append(line)
            # Include the next non-empty line as a brief summary of that section.
            for j in range(i + 1, min(i + 4, len(lines))):
                if lines[j].strip():
                    hints.append(lines[j].strip())
                    break
    return "\n".join(hints)[:limit]


def _primary_skill(ctx: AgentContext) -> dict | None:
    sc = ctx.skill_card if isinstance(ctx.skill_card, dict) else {}
    primary = sc.get("primary_skill_by_output_type") if isinstance(sc, dict) else None
    if not isinstance(primary, dict):
        return None
    card = primary.get(ctx.output_type)
    return card if isinstance(card, dict) else None


# ---------------------------------------------------------------------------
# Skill-driven system prompt construction  (Cowork pattern)
# ---------------------------------------------------------------------------

# Map skill freedom_level to Claude temperature.
_FREEDOM_TEMPERATURE: dict[str, float] = {
    "low": 0.1,   # deterministic, policy-bound output
    "medium": 0.3,  # balanced creativity/accuracy
    "high": 0.7,   # exploratory, narrative-rich output
}


def _render_zoned_system_prompt(
    *,
    zone1_stable: list[str],
    zone2_run_specific: list[str],
    zone3_dynamic: list[str],
) -> str:
    """
    Enforce deterministic prompt ordering for cache efficiency:
    Zone 1 (stable) -> Zone 2 (run metadata) -> Zone 3 (dynamic directives).
    """
    z1 = "\n".join([p for p in zone1_stable if p and str(p).strip()]).strip()
    z2 = "\n".join([p for p in zone2_run_specific if p and str(p).strip()]).strip()
    z3 = "\n".join([p for p in zone3_dynamic if p and str(p).strip()]).strip()
    blocks = [
        "### Zone1_StableSkillInstructions",
        z1,
        "",
        "### Zone2_RunMetadata",
        z2,
        "",
        "### Zone3_DynamicDirectives",
        z3,
    ]
    return "\n".join(blocks).strip()


@dataclass
class _SkillBuild:
    """Result of _build_system_from_skill — groups all skill-derived call parameters."""
    system: str
    temperature: float
    max_rounds: int | None  # None → use global settings.subagent_tool_max_rounds


def _build_system_from_skill(
    ctx: AgentContext,
    output_type: str,
    *,
    fallback_system: str,
    fallback_temperature: float = 0.3,
) -> _SkillBuild:
    """
    Build a rich system prompt from the skill card rather than hard-coding
    agent identity in sub-agent functions.

    In Cowork, the skill card IS the agent's identity — its display_name,
    prompt_instructions, workflow_steps, and acceptance_checks together
    form the complete system prompt.  Editing a SKILL.md file changes agent
    behaviour without touching Python code.

    Gap implementations:
      - Gap 1: prompt_instructions injected into SYSTEM (not USER) turn
      - Gap 3: feedback_loop length drives per-skill max_rounds cap
      - Acceptance criteria included as explicit quality gate in system prompt
      - freedom_level drives temperature
    """
    primary = _primary_skill(ctx)
    if not primary:
        # Even in fallback mode, append the tool usage policy so agents know
        # to call retrieve_context and validators before returning output.
        system_with_policy = _render_zoned_system_prompt(
            zone1_stable=[fallback_system.strip()],
            zone2_run_specific=[],
            zone3_dynamic=[_TOOL_USAGE_POLICY.strip()],
        )
        return _SkillBuild(system=system_with_policy, temperature=fallback_temperature, max_rounds=None)

    zone1_parts: list[str] = []
    zone2_parts: list[str] = []
    zone3_parts: list[str] = []

    # 1. Agent identity from skill metadata
    display_name = str(primary.get("display_name") or primary.get("id") or "Specialist")
    description = str(primary.get("description") or "").strip()
    zone1_parts.append(f"You are {display_name}.")
    if description:
        desc_wrapped = wrap_untrusted("skill_description", description, max_chars=4000)
        zone1_parts.append(desc_wrapped if desc_wrapped else description)

    # 2. Core craft instructions — the SKILL.md body (prompt_instructions).
    #    These go into the SYSTEM prompt so they define the agent's persona
    #    and mandate, not just a user-side hint.
    prompt_instructions = _skill_instruction(ctx, output_type)
    if prompt_instructions:
        zone1_parts.append("")
        instr_wrapped = wrap_untrusted("skill_prompt_instructions", prompt_instructions, max_chars=48_000)
        zone1_parts.append(instr_wrapped if instr_wrapped else prompt_instructions)

    # 3. Structured reasoning sequence from workflow_steps
    workflow_steps = primary.get("workflow_steps")
    if isinstance(workflow_steps, list) and workflow_steps:
        zone1_parts.append("")
        zone1_parts.append("Follow this reasoning sequence:")
        seq_lines = "\n".join(f"  {i}. {step}" for i, step in enumerate(workflow_steps, 1))
        seq_wrapped = wrap_untrusted("skill_workflow_steps", seq_lines, max_chars=16_000)
        zone1_parts.append(seq_wrapped if seq_wrapped else seq_lines)

    # 4. Gap 3 — feedback_loop drives max_rounds and self-correction guidance.
    #    Each feedback_loop entry = one tool-use round budget.
    feedback_loop = primary.get("feedback_loop")
    max_rounds: int | None = None
    if isinstance(feedback_loop, list) and len(feedback_loop) >= 2:
        max_rounds = max(len(feedback_loop), 2)
        zone3_parts.append("")
        zone3_parts.append("Self-correction loop — use your available tools across these rounds:")
        fb_lines = "\n".join(f"  Round {i}: {step}" for i, step in enumerate(feedback_loop, 1))
        fb_wrapped = wrap_untrusted("skill_feedback_loop", fb_lines, max_chars=8000)
        zone3_parts.append(fb_wrapped if fb_wrapped else fb_lines)
        zone3_parts.append(
            "Use qa_validator and style_enforcer tools where available to complete checking rounds. "
            "Produce the final output only after the loop is complete."
        )

    # 5. Quality gate from acceptance_checks
    acceptance_checks = primary.get("acceptance_checks")
    if isinstance(acceptance_checks, list) and acceptance_checks:
        zone3_parts.append("")
        zone3_parts.append("Your output MUST satisfy ALL of the following acceptance criteria:")
        chk_lines = "\n".join(f"  - {check}" for check in acceptance_checks)
        chk_wrapped = wrap_untrusted("skill_acceptance_checks", chk_lines, max_chars=8000)
        zone3_parts.append(chk_wrapped if chk_wrapped else chk_lines)
        zone3_parts.append(
            "After drafting, re-read your output and verify each criterion is met. "
            "Fix anything that fails before returning."
        )

    # 5.5 Companion files — domain reference material co-located with the skill.
    #     These are loaded from disk and injected into the system prompt so that
    #     leading practices, templates, and checklists are always available to the
    #     agent without requiring a separate tool call.
    companion_files_list = primary.get("companion_files")
    skill_md_path = primary.get("_skill_md_path")
    if isinstance(companion_files_list, list) and companion_files_list and skill_md_path:
        skill_dir = Path(skill_md_path).parent
        loaded_companions: list[str] = []
        for cf in companion_files_list:
            if not isinstance(cf, str) or not cf.strip():
                continue
            try:
                cf_path = (skill_dir / cf.strip()).resolve()
                content = cf_path.read_text(encoding="utf-8").strip()
                if content:
                    safe_name = ("".join(c if c.isalnum() or c in ".-_" else "_" for c in cf_path.name))[:120] or "companion"
                    cw = wrap_untrusted(f"skill_companion_{safe_name}", content, max_chars=48_000)
                    loaded_companions.append(f"### Reference: {cf_path.name}\n\n{cw if cw else content}")
            except OSError:
                pass
        if loaded_companions:
            zone1_parts.append("")
            zone1_parts.append(
                "Domain reference material (use this knowledge when generating — "
                "it contains leading practices, quality checklists, and conventions "
                "specific to this skill):"
            )
            for companion in loaded_companions:
                zone1_parts.append("")
                zone1_parts.append(companion)

    # 5.6 Inline post-processor rules — merge brand/tone guidelines from
    #     post_processor skills into the primary generation prompt instead of
    #     running a separate Claude call.  The post-processor instructions are
    #     generic guardrails (tighten titles, brand compliance) that don't need
    #     to see "naive" output first.  Inlining them saves a full API round-trip.
    sc_for_pp = ctx.skill_card if isinstance(ctx.skill_card, dict) else {}
    post_processors: list[dict] = (
        (sc_for_pp.get("post_processor_skills_by_output_type") or {}).get(output_type) or []
    )
    if post_processors:
        zone3_parts.append("")
        zone3_parts.append(
            "Brand & tone rules (apply during generation — do NOT wait for a second pass):"
        )
        zone3_parts.append(
            "Preserve facts, numbers, and process names accurately. "
            "Tighten titles, bullets, descriptions, and table cells for clarity and conciseness."
        )
        for pp_skill in post_processors:
            pp_name = str(pp_skill.get("display_name") or pp_skill.get("id") or "Brand")
            pp_instr = str(pp_skill.get("prompt_instructions") or "").strip()
            if pp_instr:
                pp_label = "".join(c if c.isalnum() or c in ".-_" else "_" for c in pp_name)[:64] or "post_processor"
                pp_wrapped = wrap_untrusted(f"post_processor_{pp_label}", pp_instr, max_chars=16_000)
                zone3_parts.append(f"  ## {pp_name}")
                zone3_parts.append(f"  {pp_wrapped}" if pp_wrapped else f"  {pp_instr}")

    # 6. Tool invocation policy — agents must be told when to call tools vs. generate
    #    directly. Without this guidance agents skip retrieve_context and generate
    #    from the ProcessModel JSON alone, missing all project-specific context.
    zone3_parts.append("")
    zone3_parts.append("Tool usage policy (follow in order):")
    zone3_parts.append(
        "  1. BEFORE generating: call retrieve_context with a query describing the process "
        "domain (e.g. 'client onboarding compliance KYC'). Use returned chunks to ground "
        "your output in project-specific facts rather than generic content."
    )
    zone3_parts.append(
        "  2. BEFORE generating: if search_leading_practices is available, call it with "
        "the process name to retrieve industry reference material."
    )
    zone3_parts.append(
        "  3. BEFORE generating: if process_model_query is available, call it with "
        "filter_type='summary' first to confirm step/role counts, then use specific "
        "filter types (e.g. 'steps_by_role', 'all_decisions') to fetch only the data "
        "you need rather than re-reading the full ProcessModel JSON."
    )
    zone3_parts.append(
        "  4. AFTER first draft: save the draft with save_draft(key='v1', content=...) "
        "before running validators. This way you can load and revise rather than "
        "regenerate from scratch if validation finds issues."
    )
    zone3_parts.append(
        "  5. AFTER first draft: call the structural validator for your output type — "
        "document_builder, table_builder, diagram_builder, or outline_validator. "
        "Fix every CRITICAL and HIGH issue, then call qa_validator to get a quality score."
    )
    zone3_parts.append(
        "  6. AFTER revision: if cross_reference_checker is available, call it to verify "
        "that all role names and step names in the output match the ProcessModel."
    )
    zone3_parts.append(
        "  7. If format_table is available and your output includes a tabular section, "
        "call format_table to build the table deterministically rather than manually."
    )
    zone3_parts.append(
        "  8. Reserve web_search for regulatory standards, external benchmarks, or "
        "terminology definitions not in the project context. Do NOT search for facts "
        "already present in retrieve_context results or the ProcessModel."
    )
    plan = ctx.plan_payload if isinstance(ctx.plan_payload, dict) else {}
    strategy = plan.get("selected_strategy") if isinstance(plan.get("selected_strategy"), dict) else {}
    option_id = str(strategy.get("option_id") or "").strip()
    if option_id:
        zone2_parts.append(f"SelectedStrategyOption: {option_id}")
    regen = str(plan.get("regeneration_directive") or "").strip()
    if regen:
        regen_wrapped = wrap_untrusted("regeneration_directive", regen, max_chars=800)
        zone2_parts.append(f"RegenerationDirective:\n{regen_wrapped}" if regen_wrapped else f"RegenerationDirective: {regen[:800]}")
    zone1_fingerprint = hashlib.sha256("\n".join(zone1_parts).encode("utf-8")).hexdigest()[:16]
    zone2_parts.append(f"Zone1Fingerprint: {zone1_fingerprint}")

    # 7. Temperature from freedom_level
    freedom = str(primary.get("freedom_level") or "medium").strip().lower()
    temperature = _FREEDOM_TEMPERATURE.get(freedom, fallback_temperature)

    rendered = _render_zoned_system_prompt(
        zone1_stable=zone1_parts,
        zone2_run_specific=zone2_parts,
        zone3_dynamic=zone3_parts,
    )
    return _SkillBuild(
        system=f"{UNTRUSTED_SKILL_SYSTEM_NOTE}{rendered}",
        temperature=temperature,
        max_rounds=max_rounds,
    )


def _run_subagent_tool_loop_text(
    ctx: AgentContext,
    *,
    agent_id: str,
    system: str,
    user: str,
    temperature: float = 0.3,
    max_rounds: int | None = None,
) -> str | None:
    """Run iterative tool loop; return final assistant text or None on failure / missing project."""
    try:
        primary = _primary_skill(ctx)
        names = tool_names_for_skill(primary) if primary else []
        defaults = default_tools_for_output_type(ctx.output_type)
        if not names:
            # No skill active or skill declared no tools → use output-type defaults.
            names = defaults
        else:
            # Merge: add any default tools not already in the skill-declared list.
            # This ensures that phantom tool slots (e.g. document_builder declared in
            # skill but not yet in registry) are filled by equivalent registry tools,
            # rather than leaving the agent with a narrower-than-intended tool set.
            for t in defaults:
                if t not in names:
                    names = list(names) + [t]
        if getattr(settings, "swarm_orchestration_enabled", False):
            for n in _SWARM_TOOL_NAMES:
                if n not in names:
                    names.append(n)
        tool_defs = anthropic_tool_definitions(names)
        if not tool_defs:
            return None
        pid = str(ctx.project_id or "").strip()
        if not pid:
            return None
        from app.services.swarm import SWARM_WORKER_PREAMBLE

        sys_prompt = system
        if getattr(settings, "swarm_orchestration_enabled", False):
            sys_prompt = f"{SWARM_WORKER_PREAMBLE}\n\n{system}"
        nc: dict[str, Any] = {
            "project_id": pid,
            "user_id": ctx.user_id,
            "process_model": ctx.process_model,
            "run_id": str(ctx.run_id or ""),
            "agent_id": agent_id,
        }
        if ctx.swarm_teammate_id:
            nc["swarm_teammate_id"] = ctx.swarm_teammate_id
        out = run_subagent_tool_loop(
            system=sys_prompt,
            user=user,
            project_id=pid,
            tool_defs=tool_defs,
            native_context=nc,
            emit_event=ctx.emit_event,
            agent_id=agent_id,
            run_id=str(ctx.run_id or ""),
            temperature=temperature,
            max_rounds=max_rounds,  # None → global default from settings
        )
        text = (out.get("text") or "").strip()
        return text if text else None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Gap 4 — Quality threshold gating
# ---------------------------------------------------------------------------

def _apply_quality_gate(
    ctx: AgentContext,
    output_type: str,
    content: str,
    *,
    system: str,
    temperature: float,
) -> str:
    """
    Compare output quality against the skill's quality_thresholds[output_type].

    If the qa_validator score falls below the declared threshold, one remediation
    pass is requested from Claude with the list of issues injected into the prompt.
    Returns the (possibly improved) content; never raises.
    """
    if not content.strip() or not is_claude_enabled():
        return content

    primary = _primary_skill(ctx)
    if not primary:
        return content

    thresholds = primary.get("quality_thresholds") or {}
    threshold = float((thresholds or {}).get(output_type) or 0)
    if threshold <= 0:
        return content

    # In-process qa_validator call (no tool-loop overhead for the gate check)
    try:
        from app.services.tool_registry import qa_validator as _qa_validator
        qa_result = _qa_validator(text=content, output_type=output_type)
    except Exception:  # noqa: BLE001
        return content

    score = float(qa_result.get("score") or 1.0)
    issues: list[str] = qa_result.get("issues") or []

    if score >= threshold or not issues:
        return content  # ✅ passes gate

    # Emit a quality gate event if an emitter is available
    emit = ctx.emit_event
    if emit:
        try:
            emit("quality_gate", {
                "output_type": output_type,
                "score": score,
                "threshold": threshold,
                "issues": issues,
                "action": "remediation_pass",
            })
        except Exception:  # noqa: BLE001, S110, SIM105
            pass

    remediation_prompt = (
        f"Your output did not meet the quality threshold "
        f"(score {score:.2f} < required {threshold:.2f}).\n\n"
        "Issues to fix:\n"
        + "\n".join(f"  - {issue}" for issue in issues)
        + "\n\nPlease revise to address ALL issues listed above. "
        "Return the complete corrected output only — no explanations."
        f"\n\nPrevious output:\n{content}"
    )
    try:
        if output_type == "pptx":
            improved_obj = claude_generate_json(
                system=(
                    system
                    + "\n\nThe revision MUST be one JSON object: {\"slides\": [...]} matching the prior schema. "
                    "No markdown fences, no commentary."
                ),
                user=remediation_prompt,
                temperature=temperature,
                max_tokens=8192,
            )
            if isinstance(improved_obj, dict) and isinstance(improved_obj.get("slides"), list):
                return json.dumps({"slides": improved_obj["slides"]}, ensure_ascii=False)
        else:
            improved = claude_generate(
                system=system,
                user=remediation_prompt,
                temperature=temperature,
                max_tokens=2500,
            )
            if isinstance(improved, str) and improved.strip():
                return improved
    except Exception:  # noqa: BLE001, S110
        pass
    return content


# ---------------------------------------------------------------------------
# Gap 1 (composition) — Post-processor pass
# ---------------------------------------------------------------------------

def _run_post_processor(ctx: AgentContext, content: str) -> str:
    """
    Apply post-processor skills (role=post_processor) to the primary output.

    Post-processors such as brand_guidelines_v1 are applied AFTER the primary
    agent generates content — they refine tone, styling, and brand compliance
    without being mixed into the generation prompt.

    Returns the refined content, or the original if no post-processors are
    configured for this output type or Claude is unavailable.
    """
    if not content.strip() or not is_claude_enabled():
        return content

    sc = ctx.skill_card if isinstance(ctx.skill_card, dict) else {}
    post_processors: list[dict] = (sc.get("post_processor_skills_by_output_type") or {}).get(ctx.output_type) or []
    if not post_processors:
        return content

    # Collect instructions and workflow_steps from all post-processors for this output
    system_parts: list[str] = ["You are a post-processing specialist."]
    for skill in post_processors:
        name = str(skill.get("display_name") or skill.get("id") or "Brand Stylist")
        instr = str(skill.get("prompt_instructions") or "").strip()
        steps = skill.get("workflow_steps")
        checks = skill.get("acceptance_checks")

        system_parts.append(f"\n## {name}")
        if instr:
            system_parts.append(instr)
        if isinstance(steps, list) and steps:
            system_parts.append("\nFollow these steps:")
            for i, s in enumerate(steps, 1):
                system_parts.append(f"  {i}. {s}")
        if isinstance(checks, list) and checks:
            system_parts.append("\nEnsure the output satisfies:")
            for c in checks:
                system_parts.append(f"  - {c}")

    system_parts.append(
        "\nPreserve ALL information from the original. "
        "Only improve tone, style, and brand compliance. "
        "Return the complete refined output only."
    )

    system = "\n".join(system_parts)
    user = (
        f"Refine the following {ctx.output_type} output according to the style guidelines above.\n\n"
        f"CONTENT:\n{content}"
    )

    emit = ctx.emit_event
    skill_label = ", ".join(str(s.get("display_name") or s.get("id") or "") for s in post_processors)
    if emit:
        try:
            emit(
                "step",
                {
                    "status": "post_processing_start",
                    "skill_name": skill_label,
                    "output_type": ctx.output_type,
                },
            )
        except Exception:  # noqa: BLE001, S110, SIM105
            pass

    try:
        refined = claude_generate(system=system, user=user, temperature=0.1, max_tokens=3000)
        out = refined if isinstance(refined, str) and refined.strip() else content
        if emit:
            try:
                emit(
                    "step",
                    {
                        "status": "post_processing_done",
                        "skill_name": skill_label,
                        "output_type": ctx.output_type,
                    },
                )
            except Exception:  # noqa: BLE001, S110, SIM105
                pass
        return out
    except Exception:  # noqa: BLE001
        if emit:
            try:
                emit(
                    "step",
                    {
                        "status": "post_processing_done",
                        "skill_name": skill_label,
                        "output_type": ctx.output_type,
                        "error": True,
                    },
                )
            except Exception:  # noqa: BLE001, S110, SIM105
                pass
        return content


def _run_pptx_post_processor(ctx: AgentContext, slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply brand / post_processor skills to slide JSON (same slide count and slide_types).

    When a primary skill is present, post-processor rules are already inlined into
    the primary generation prompt by _build_system_from_skill (Section 5.6), so this
    separate Claude call is skipped — saving a full API round-trip.
    """
    if not slides or not is_claude_enabled():
        return slides
    sc = ctx.skill_card if isinstance(ctx.skill_card, dict) else {}
    post_processors: list[dict] = (sc.get("post_processor_skills_by_output_type") or {}).get("pptx") or []
    if not post_processors:
        return slides
    # Skip separate post-processing when rules were already inlined into the
    # primary generation prompt (primary skill present → rules in Zone 3).
    if _primary_skill(ctx):
        return slides

    system_parts: list[str] = [
        "You post-process a slide deck JSON blueprint for brand tone, clarity, and consistency.",
        "Input and output: one JSON object {\"slides\": [...]} only — no markdown fences or commentary.",
        "Preserve the same number of slides in the same order; do not change any slide_type value.",
        "Keep facts, numbers, and process names accurate; tighten titles, bullets, descriptions, and table cells.",
    ]
    for skill in post_processors:
        name = str(skill.get("display_name") or skill.get("id") or "Brand")
        instr = str(skill.get("prompt_instructions") or "").strip()
        system_parts.append(f"\n## {name}")
        if instr:
            system_parts.append(instr)
    system = "\n".join(system_parts)
    payload = json.dumps({"slides": slides}, ensure_ascii=False)

    emit = ctx.emit_event
    skill_label = ", ".join(str(s.get("display_name") or s.get("id") or "") for s in post_processors)
    if emit:
        try:
            emit(
                "step",
                {
                    "status": "post_processing_start",
                    "skill_name": skill_label,
                    "output_type": "pptx",
                },
            )
        except Exception:  # noqa: BLE001, S110, SIM105
            pass

    try:
        out = claude_generate_json(
            system=system,
            user=f"Refine this deck JSON per the guidelines above:\n\n{payload}",
            temperature=0.1,
            max_tokens=8192,
        )
        if isinstance(out, dict):
            new_slides = out.get("slides")
            if isinstance(new_slides, list) and len(new_slides) == len(slides):
                merged: list[dict[str, Any]] = []
                for i, raw in enumerate(new_slides):
                    merged.append(raw if isinstance(raw, dict) else slides[i])
                if emit:
                    try:
                        emit(
                            "step",
                            {
                                "status": "post_processing_done",
                                "skill_name": skill_label,
                                "output_type": "pptx",
                            },
                        )
                    except Exception:  # noqa: BLE001, S110, SIM105
                        pass
                return merged
    except Exception:  # noqa: BLE001, S110
        pass
    if emit:
        try:
            emit(
                "step",
                {
                    "status": "post_processing_done",
                    "skill_name": skill_label,
                    "output_type": "pptx",
                    "error": True,
                },
            )
        except Exception:  # noqa: BLE001, S110, SIM105
            pass
    return slides


_TOOL_USAGE_POLICY = (
    "\n\nTool usage policy (follow in order):\n"
    "1. BEFORE generating: call retrieve_context with a query describing the process domain.\n"
    "2. BEFORE generating: call process_model_query(filter_type='summary') to confirm step/role counts.\n"
    "3. BEFORE generating: call search_leading_practices if available.\n"
    "4. AFTER first draft: call save_draft(key='v1', content=...) to persist the draft.\n"
    "5. AFTER first draft: call the structural validator "
    "(document_builder / table_builder / diagram_builder / outline_validator) and fix issues.\n"
    "6. AFTER revision: call cross_reference_checker to verify roles and step names match the ProcessModel.\n"
    "7. Use format_table for tabular output rather than building rows manually.\n"
    "8. Reserve web_search for external standards not in the project context."
)


def _deliverable_type_for_skill(skill_id: str) -> str:
    """
    Map an active skill ID to a deliverable type string for content routing.

    Format agents use this to select the appropriate user prompt and
    deterministic fallback for their active content skill.

    Returns one of: 'sop', 'raci', 'narrative', 'brd', 'approach_note',
    'proposal', or 'generic' (default).
    """
    sid = (skill_id or "").lower()
    if "sop" in sid:
        return "sop"
    if "raci" in sid:
        return "raci"
    if "narrative" in sid:
        return "narrative"
    if "brd" in sid:
        return "brd"
    if "approach_note" in sid:
        return "approach_note"
    if "proposal" in sid:
        return "proposal"
    return "generic"


def _raci_deterministic_updates(pm: ProcessModel, preferred: str) -> dict[str, Any]:
    steps = pm.get("steps") or []
    roles = pm.get("roles") or ["Process Owner", "Contributor"]
    accountable = roles[0] if roles else "Process Owner"
    rows: list[str] = []
    for st in steps:
        name = html.escape(st.get("name") or "—")
        resp = html.escape(st.get("role") or "—")
        acct = html.escape(accountable)
        others = [r for r in roles if r not in (st.get("role"), accountable)]
        consulted = html.escape(", ".join(others[:4]) if others else "—")
        rows.append(f"<tr><td>{name}</td><td>{resp}</td><td>{acct}</td><td>{consulted}</td><td>—</td></tr>")

    body = "\n        ".join(rows) if rows else (
        "<tr><td colspan=\"5\">No activities — add numbered or bulleted steps to the run instruction.</td></tr>"
    )
    title = html.escape(pm.get("process_name") or "RACI")
    html_fallback = textwrap.dedent(
        f"""\
        <!DOCTYPE html>
        <html lang="en"><head><meta charset="utf-8"/><title>{title}</title>
        <style>
          body {{ font-family: system-ui, sans-serif; margin: 1rem; }}
          table {{ border-collapse: collapse; width: 100%; max-width: 960px; }}
          th, td {{ border: 1px solid #ccc; padding: 8px 10px; text-align: left; }}
          th {{ background: #f0f4f8; }}
        </style></head><body>
        <h1>RACI — {title}</h1>
        <table>
          <thead><tr>
            <th>Activity</th><th>Responsible</th><th>Accountable</th><th>Consulted</th><th>Informed</th>
          </tr></thead>
          <tbody>
        {body}
          </tbody>
        </table>
        <p style="color:#666;font-size:0.9rem">RACI derived from extracted process steps and roles.</p>
        </body></html>
        """
    ).strip()
    updates: dict[str, Any] = {"raci_html": html_fallback}
    if preferred in {"markdown", "xlsx"}:
        md_rows = ["| Activity | Responsible | Accountable | Consulted | Informed |", "|---|---|---|---|---|"]
        for st in steps:
            name = (st.get("name") or "—").replace("|", "\\|")
            resp = (st.get("role") or "—").replace("|", "\\|")
            others = [r for r in roles if r not in (st.get("role"), accountable)]
            consulted = (", ".join(others[:4]) if others else "—").replace("|", "\\|")
            md_rows.append(f"| {name} | {resp} | {accountable} | {consulted} | — |")
        updates["raci_markdown"] = "\n".join(md_rows)
    return updates


def run_raci_agent(ctx: AgentContext) -> AgentOutput:
    """
    Legacy content generator retained for direct invocation in tests/tooling.
    This agent writes to raci_html / raci_markdown (legacy state keys).
    For new output routing, use run_xlsx_agent with raci_v2 skill active.
    """
    pm = _model(ctx)
    preferred = _pref(ctx, "raci", "xlsx")
    llm_target = "Markdown table" if preferred in {"markdown", "xlsx"} else "strict HTML table"
    if is_claude_enabled():
        sb = _build_system_from_skill(
            ctx, "raci",
            fallback_system=(
                f"You are a RACI matrix author. "
                f"Output format: {llm_target}. "
                "Return ONLY the table — no preamble, no section headings, no explanation. "
                "RACI definitions: "
                "R (Responsible) = the role that executes the activity. "
                "A (Accountable) = the role that owns the outcome and signs off — EXACTLY ONE per row. "
                "C (Consulted) = roles whose input is required before the step completes. "
                "I (Informed) = roles notified after the step completes. "
                "A role may hold multiple letters in one cell (e.g. 'R/A') only when the same person is both executor and owner. "
                "Never leave Accountable blank."
            ),
        )
        user = (
            "Build a RACI matrix from the ProcessModel below.\n\n"
            "Assignment rules:\n"
            "1. Responsible (R): use step.role. If step.role is absent or 'TBD', assign R to the first role in ProcessModel.roles.\n"
            "2. Accountable (A): assign to the first role in ProcessModel.roles unless a more senior role is evident from the name "
            "(e.g. 'Manager', 'Director', 'Lead', 'Owner'). Exactly one A per row — never blank, never multiple.\n"
            "3. Consulted (C): assign remaining roles whose work depends on or feeds into this step. "
            "If no such roles exist, use '—'.\n"
            "4. Informed (I): assign roles that receive the output of this step but do not participate. "
            "If none, use '—'.\n\n"
            f"Output format: {preferred} (markdown table with header row if markdown, full HTML table if html).\n"
            "Column order: Activity | Responsible | Accountable | Consulted | Informed\n"
            "One row per ProcessModel.steps entry. Do not add rows for roles — only for activities.\n"
            "Do not include a title row, caption, or explanatory text — table only.\n\n"
            f"{process_model_json_block(pm)}"
        )
        loop_out = _run_subagent_tool_loop_text(ctx, agent_id="raci", system=sb.system, user=user, temperature=sb.temperature, max_rounds=sb.max_rounds)
        model_out = loop_out
        if not model_out:
            try:
                model_out = claude_generate(system=sb.system, user=user, temperature=sb.temperature, max_tokens=1800)
            except Exception:  # noqa: BLE001 — fallback
                model_out = None
        if isinstance(model_out, str) and model_out.strip():
            model_out = _apply_quality_gate(ctx, "raci", model_out, system=sb.system, temperature=sb.temperature)
            model_out = _run_post_processor(ctx, model_out)
            if preferred in {"markdown", "xlsx"} and "|" in model_out:
                base = _raci_deterministic_updates(pm, preferred)
                base["raci_markdown"] = model_out
                return AgentOutput(updates=base)
            if preferred == "html" and "<table" in model_out.lower() and "<tr" in model_out.lower():
                return AgentOutput(updates={"raci_html": model_out})

    return AgentOutput(updates=_raci_deterministic_updates(pm, preferred))


def run_sop_agent(ctx: AgentContext) -> AgentOutput:
    """
    Legacy content generator retained for direct invocation in tests/tooling.
    This agent writes to sop_markdown (legacy state key).
    For new output routing, use run_docx_agent with sop_v2 skill active.
    """
    pm = _model(ctx)
    if is_claude_enabled():
        sb = _build_system_from_skill(
            ctx, "sop",
            fallback_system=(
                "You are a technical procedure writer. "
                "Audience: an operator who must execute this process without prior context. "
                "Register: formal, imperative, present-tense verbs (e.g. 'Submit the form', not 'You should submit'). "
                "Return ONLY valid Markdown. No HTML. No preamble. The document must start with a # heading."
            ),
        )
        user = (
            "Write a Standard Operating Procedure (SOP) from the ProcessModel below.\n\n"
            "Document structure — use EXACTLY these sections in this order:\n"
            "1. `# <process_name>` — H1 title only, no subtitle\n"
            "2. `## Purpose` — 1–3 sentences: what problem this process solves and who benefits\n"
            "3. `## Scope` — 1–2 sentences: what is covered and what is explicitly out of scope\n"
            "4. `## Roles` — bulleted list of each role in ProcessModel.roles with a one-sentence description "
            "of their mandate in this process\n"
            "5. `## Procedure` — numbered list where each item corresponds to exactly one ProcessModel step; "
            "format: `N. **<step.name>** _(role: <step.role>)_` followed by a sub-list of inputs/outputs/tools "
            "if any are present in the step; do not add steps not in the ProcessModel\n"
            "6. `## Decision Points` — include only if ProcessModel.decisions is non-empty; "
            "for each decision: `**<condition>** → Yes: <true_path step names>, No: <false_path step names>`; "
            "omit this section entirely if decisions is []\n"
            "7. `## References` — single bullet: 'Source: run instruction and assembled project context'\n\n"
            "Length constraint: ≤80 words per section (Purpose, Scope). Procedure steps: ≤20 words per step name line.\n"
            "Do not add sections beyond the seven listed above.\n\n"
            f"{process_model_json_block(pm)}"
        )
        md = _run_subagent_tool_loop_text(ctx, agent_id="sop", system=sb.system, user=user, temperature=sb.temperature, max_rounds=sb.max_rounds)
        if not md:
            try:
                md = claude_generate(system=sb.system, user=user, temperature=sb.temperature, max_tokens=2200)
            except Exception:  # noqa: BLE001 — fallback
                md = None
        if isinstance(md, str) and md.strip().startswith("#"):
            md = _apply_quality_gate(ctx, "sop", md, system=sb.system, temperature=sb.temperature)
            md = _run_post_processor(ctx, md)
            return AgentOutput(updates={"sop_markdown": md})

    # Deterministic fallback.
    name = pm.get("process_name") or "Standard Operating Procedure"
    steps = pm.get("steps") or []
    roles = ", ".join(pm.get("roles") or [])
    lines: list[str] = [
        f"# {name}",
        "",
        "## Purpose",
        "",
        "This procedure documents the workflow extracted from the engagement instruction and project context.",
        "",
        "## Roles",
        "",
        roles or "_Not specified — inferred defaults._",
        "",
        "## Procedure",
        "",
    ]
    if not steps:
        lines.extend(
            [
                "_No discrete steps were parsed. Provide numbered (1., 2.) or bullet (-) steps in the run instruction._",
                "",
            ]
        )
    else:
        for i, st in enumerate(steps, start=1):
            role = st.get("role") or "TBD"
            nm = st.get("name") or "Step"
            lines.append(f"{i}. **{nm}** — _{role}_")
            if st.get("notes"):
                lines.append(f"   - Notes: {st['notes']}")
            lines.append("")

    decs = pm.get("decisions") or []
    if decs:
        lines.extend(["## Decision points", ""])
        for d in decs:
            lines.append(f"- **{d.get('id', '?')}**: {d.get('condition', '')}")
        lines.append("")

    lines.extend(
        [
            "## References",
            "",
            "- Source: assembled project context and run instruction (see run artifacts).",
            "",
        ]
    )
    return AgentOutput(updates={"sop_markdown": "\n".join(lines).strip() + "\n"})


def run_narrative_agent(ctx: AgentContext) -> AgentOutput:
    """
    Legacy content generator retained for direct invocation in tests/tooling.
    This agent writes to narrative_md (legacy state key).
    For new output routing, use run_docx_agent with narrative_v2 skill active.
    """
    pm = _model(ctx)
    actx = (ctx.assembled_context or "").strip()
    if is_claude_enabled():
        sb = _build_system_from_skill(
            ctx, "narrative",
            fallback_system=(
                "You are a management consultant writing a client-facing briefing note. "
                "Audience: a senior stakeholder who will not read technical details — they need insight, not procedure. "
                "Tone: authoritative, direct, no hedging language ('it appears', 'it seems', 'we believe'). "
                "Return ONLY valid Markdown starting with a # heading. No HTML. No preamble."
            ),
        )
        user = (
            "Write an executive briefing note from the ProcessModel and context excerpt below.\n\n"
            "Document structure — use EXACTLY these sections in this order:\n"
            "1. `# <process_name> — Executive Briefing` — H1 title\n"
            "2. `## What This Process Does` — 2–4 sentences: the business outcome delivered by this process, "
            "who initiates it, and who benefits; do not describe individual steps\n"
            "3. `## Key Activities` — bulleted list of ≤6 items; each item names the activity and its owner role "
            "in ≤12 words; derived from ProcessModel.steps; omit low-signal steps if there are more than 6\n"
            "4. `## Roles and Accountability` — one bullet per role in ProcessModel.roles; "
            "state what that role is accountable for in this process in ≤15 words\n"
            "5. `## Recommended Next Actions` — exactly 2–4 numbered items; "
            "each action must be specific to this process (not generic advice); "
            "each item ≤20 words; no action should duplicate another\n\n"
            "Constraints:\n"
            "  - Do not quote or paraphrase the context excerpt verbatim.\n"
            "  - Do not add a 'Context Used' or 'References' section.\n"
            "  - Do not repeat information across sections.\n"
            "  - Do not use the phrase 'in conclusion' or 'in summary'.\n\n"
            f"{process_model_json_block(pm)}\n"
            f"{context_excerpt_block(actx, 4000)}"
        )
        user = _append_conversation_digest_block(user, ctx)
        md: str | None = None
        if settings.subagent_narrative_thinking_enabled and is_claude_enabled():
            try:
                res = claude_generate_with_thinking(
                    system=sb.system,
                    user=user,
                    max_tokens=1800,
                    budget_tokens=settings.anthropic_subagent_thinking_budget_tokens,
                )
                thinking_t = str(res.get("thinking_text") or "").strip()
                if thinking_t and ctx.emit_event:
                    ctx.emit_event("narrative_thinking_excerpt", {"thinking_excerpt": thinking_t[:1500]})
                increment("narrative_thinking_used_total")
                cand = str(res.get("text") or "").strip()
                if cand.startswith("#"):
                    md = cand
            except Exception:  # noqa: BLE001
                md = None
        if not md:
            md = _run_subagent_tool_loop_text(
                ctx, agent_id="narrative", system=sb.system, user=user, temperature=sb.temperature, max_rounds=sb.max_rounds
            )
        if not md:
            try:
                md = claude_generate(system=sb.system, user=user, temperature=sb.temperature, max_tokens=1800)
            except Exception:  # noqa: BLE001 — fallback
                md = None
        if isinstance(md, str) and md.strip().startswith("#"):
            md = _apply_quality_gate(ctx, "narrative", md, system=sb.system, temperature=sb.temperature)
            md = _run_post_processor(ctx, md)
            return AgentOutput(updates={"narrative_md": md})

    # Deterministic fallback.
    ctx_excerpt = (actx[:1200] + "…") if len(actx) > 1200 else actx
    name = pm.get("process_name") or "Engagement process"
    steps = pm.get("steps") or []
    roles = pm.get("roles") or []
    summary = (
        f"The following narrative summarizes **{name}**, structured as **{len(steps)}** workflow step(s) "
        f"across **{len(roles)}** role(s)."
    )
    if steps:
        highlights = "; ".join(f"{s.get('name', '')}" for s in steps[:5])
        if len(steps) > 5:
            highlights += "; …"
        summary += f" Key activities include: {highlights}."
    body = [
        f"# Executive narrative — {name}",
        "",
        "## Summary",
        "",
        summary,
        "",
        "## Context used",
        "",
        "```",
        ctx_excerpt or "_No additional tiered context was available._",
        "```",
        "",
        "## Recommended next actions",
        "",
    ]
    if steps:
        body.append("1. Validate each step with process owners and update RACI where handoffs are unclear.")
        body.append("2. Confirm tooling and systems referenced in source materials.")
    else:
        body.append("1. Enrich the run instruction with numbered steps to unlock full SOP and diagram outputs.")
    body.extend(["", "---", "", "*Generated by ProcessDoc Studio (deterministic extraction).*", ""])
    return AgentOutput(updates={"narrative_md": "\n".join(body).strip() + "\n"})


def run_drawio_agent(ctx: AgentContext) -> AgentOutput:
    pm = _model(ctx)
    preferred = _pref(ctx, "process_map", "drawio_xml")
    if preferred == "mermaid":
        steps = pm.get("steps") or []
        lines = ["flowchart TD"]
        for idx, step in enumerate(steps):
            node = f"s{idx+1}"
            label = str(step.get("name") or f"Step {idx+1}").replace('"', "'")
            lines.append(f'    {node}["{label}"]')
            if idx > 0:
                lines.append(f"    s{idx} --> {node}")
        if len(lines) == 1:
            lines.append('    s1["Process Start"]')
        return AgentOutput(updates={"process_map_mermaid": "\n".join(lines)})
    if is_claude_enabled():
        sb = _build_system_from_skill(
            ctx, "process_map",
            fallback_system=(
                "You are a diagrams.net (draw.io) mxGraph XML generator. "
                "Return ONLY valid mxGraphModel XML — no prose, no markdown fences, no XML declaration. "
                "The output must be parseable as-is by an XML parser. "
                "Every cell that is a vertex or edge must have parent='1'. "
                "The two scaffolding cells (id='0' root, id='1' layer) must always be present."
            ),
        )
        user = (
            "Generate a diagrams.net mxGraphModel XML diagram from the ProcessModel below.\n\n"
            "Required XML structure:\n"
            "<mxGraphModel><root>\n"
            "  <mxCell id='0'/>\n"
            "  <mxCell id='1' parent='0'/>\n"
            "  <!-- one mxCell per step, one mxCell per decision, one mxCell per edge -->\n"
            "</root></mxGraphModel>\n\n"
            "Step cells (one per ProcessModel.steps entry):\n"
            "  id='sN' where N is the step index (s1, s2, ...)\n"
            "  value='<step.name>'\n"
            "  vertex='1' parent='1'\n"
            "  style='rounded=1;whiteSpace=wrap;html=1;'\n"
            "  <mxGeometry x='{40 + (N-1)*160}' y='100' width='140' height='60' as='geometry'/>\n\n"
            "Decision cells (one per ProcessModel.decisions entry, only if non-empty):\n"
            "  id='dN' where N is the decision index (d1, d2, ...)\n"
            "  value='<decision.condition>'\n"
            "  vertex='1' parent='1'\n"
            "  style='rhombus;whiteSpace=wrap;html=1;'\n"
            "  <mxGeometry x='{x}' y='220' width='140' height='80' as='geometry'/>\n\n"
            "Edge cells (one per sequential step connection, plus true/false edges from decisions):\n"
            "  id='eN' where N is incremented globally\n"
            "  edge='1' source='<sourceId>' target='<targetId>' parent='1'\n"
            "  For decision edges: value='Yes' (true_path) or 'No' (false_path)\n"
            "  style='edgeStyle=orthogonalEdgeStyle;'\n"
            "  <mxGeometry relative='1' as='geometry'/>\n\n"
            "Swimlane rule: if ProcessModel.swimlanes is non-empty, group steps by role using "
            "swimlane container cells (style='swimlane;') with child cells inside them (parent='containerCellId'). "
            "If swimlanes is empty, place all cells flat under parent='1'.\n\n"
            "Do not output anything outside the <mxGraphModel> element.\n\n"
            f"{process_model_json_block(pm)}"
        )
        _drawio_hints = _drawio_context_hints(ctx)
        if _drawio_hints:
            user += f"\n\nContext hints for swimlane structure and roles:\n{_drawio_hints}"
        _pm_feedback = ctx.plan_payload.get("process_map_visual_feedback") or []
        if _pm_feedback and isinstance(_pm_feedback, list):
            _pm_hints = "\n".join(
                f"- {h.get('instruction', '')}" for h in _pm_feedback
                if isinstance(h, dict) and h.get("instruction")
            )
            if _pm_hints:
                user += f"\n\nVisual QA feedback from previous generation (must be addressed):\n{_pm_hints}"
        xml_out = _run_subagent_tool_loop_text(ctx, agent_id="process_map", system=sb.system, user=user, temperature=sb.temperature, max_rounds=sb.max_rounds)
        if not xml_out:
            try:
                xml_out = claude_generate(system=sb.system, user=user, temperature=sb.temperature, max_tokens=1600)
            except Exception:  # noqa: BLE001 — fallback
                xml_out = None
        normalized = _normalize_drawio_xml(xml_out) if isinstance(xml_out, str) else None
        if normalized and "<mxCell" in normalized:
            return AgentOutput(updates={"drawio_xml": normalized})

    return AgentOutput(updates={"drawio_xml": process_model_to_drawio_xml(pm)})


def run_xlsx_agent(ctx: AgentContext) -> AgentOutput:
    """
    Skill-aware XLSX agent. When raci_v2 is the active skill, generates a RACI matrix
    (Activity | Responsible | Accountable | Consulted | Informed). Otherwise generates
    the standard process data table (Activity | Owner | Inputs | Outputs | Tools | Duration | Notes).
    """
    pm = _model(ctx)
    steps = pm.get("steps") or []
    roles = pm.get("roles") or []
    primary = _primary_skill(ctx)
    skill_id = str((primary or {}).get("id") or "")
    deliverable = _deliverable_type_for_skill(skill_id)
    is_raci = (deliverable == "raci")

    if is_claude_enabled():
        sb = _build_system_from_skill(
            ctx, "xlsx",
            fallback_system=(
                "You are a data normalisation specialist preparing worksheet content for XLSX export. "
                "Return ONLY a GitHub-flavored Markdown table — header row first, then one data row per step. "
                "No title, no section heading, no explanation before or after the table. "
                "Empty cells must contain '—', never left blank. "
                "Cell values containing '|' must escape it as '\\|'. "
                "No cell value may exceed 200 characters — truncate with '…' if longer."
            ),
        )
        if is_raci:
            accountable = roles[0] if roles else "Process Owner"
            user = (
                "Build a RACI matrix Markdown table from the ProcessModel below.\n\n"
                "Column definitions (in this exact order):\n"
                "  Activity     — step.name\n"
                "  Responsible  — step.role; use roles[0] if step.role is absent\n"
                "  Accountable  — the role that owns the outcome (exactly one per row); "
                f"default to '{accountable}' unless a more senior role is evident\n"
                "  Consulted    — roles whose input is required; '—' if none\n"
                "  Informed     — roles notified after completion; '—' if none\n\n"
                "Header row: | Activity | Responsible | Accountable | Consulted | Informed |\n"
                "Separator:  |---|---|---|---|---|\n"
                "One data row per step. No title, no caption — table only.\n"
                "Exactly one Accountable per row — never blank, never multiple.\n\n"
                f"{process_model_json_block(pm)}"
            )
        else:
            user = (
                "Build a worksheet table from the ProcessModel below. "
                "Each row represents one step from ProcessModel.steps, in the order they appear.\n\n"
                "Column definitions (in this exact order):\n"
                "  Activity  — step.name\n"
                "  Owner     — step.role; use ProcessModel.roles[0] if step.role is absent\n"
                "  Inputs    — step.inputs joined by ', '; '—' if empty\n"
                "  Outputs   — step.outputs joined by ', '; '—' if empty\n"
                "  Tools     — step.tools joined by ', '; '—' if empty\n"
                "  Duration  — step.duration_estimate; '—' if absent\n"
                "  Notes     — step.notes; '—' if absent\n\n"
                "Header row format: | Activity | Owner | Inputs | Outputs | Tools | Duration | Notes |\n"
                "Separator row format: |---|---|---|---|---|---|---|\n"
                "One data row per step. No title, no summary row.\n\n"
                f"{process_model_json_block(pm)}"
            )
        _xlsx_feedback = ctx.plan_payload.get("xlsx_visual_feedback") or []
        if _xlsx_feedback and isinstance(_xlsx_feedback, list):
            _xlsx_hints = "\n".join(
                f"- {h.get('instruction', '')}" for h in _xlsx_feedback
                if isinstance(h, dict) and h.get("instruction")
            )
            if _xlsx_hints:
                user += f"\n\nVisual QA feedback from previous generation (must be addressed):\n{_xlsx_hints}"
        md = _run_subagent_tool_loop_text(ctx, agent_id="xlsx", system=sb.system, user=user,
                                          temperature=sb.temperature, max_rounds=sb.max_rounds)
        if not md:
            try:
                md = claude_generate(system=sb.system, user=user, temperature=sb.temperature, max_tokens=1800)
            except Exception:
                md = None
        if isinstance(md, str) and "|" in md:
            md = _apply_quality_gate(ctx, "xlsx", md, system=sb.system, temperature=sb.temperature)
            return AgentOutput(updates={"xlsx_markdown": md})

    # Deterministic fallback
    if is_raci:
        accountable = roles[0] if roles else "Process Owner"
        lines = ["| Activity | Responsible | Accountable | Consulted | Informed |", "|---|---|---|---|---|"]
        if not steps:
            lines.append("| No extracted activity | TBD | TBD | — | — |")
        else:
            for st in steps:
                if not isinstance(st, dict):
                    continue
                nm = (st.get("name") or "—").replace("|", "\\|")
                resp = (st.get("role") or (roles[0] if roles else "TBD")).replace("|", "\\|")
                others = [r for r in roles if r not in (st.get("role"), accountable)]
                cons = (", ".join(others[:3]) if others else "—").replace("|", "\\|")
                lines.append(f"| {nm} | {resp} | {accountable} | {cons} | — |")
    else:
        lines = [
            "| Activity | Owner | Inputs | Outputs | Tools | Duration | Notes |",
            "|---|---|---|---|---|---|---|",
        ]
        if not steps:
            lines.append("| No extracted activity | TBD | - | - | - | - | Add structured steps in instruction |")
        else:
            for st in steps:
                if not isinstance(st, dict):
                    continue
                activity = str(st.get("name") or "Step").replace("|", "\\|")
                owner = str(st.get("role") or (roles[0] if roles else "TBD")).replace("|", "\\|")
                inputs = ", ".join([str(v) for v in (st.get("inputs") or [])[:4]]) or "-"
                outputs = ", ".join([str(v) for v in (st.get("outputs") or [])[:4]]) or "-"
                tools = ", ".join([str(v) for v in (st.get("tools") or [])[:4]]) or "-"
                duration = str(st.get("duration_estimate") or "-").replace("|", "\\|")
                notes = str(st.get("notes") or "-").replace("|", "\\|")
                lines.append(f"| {activity} | {owner} | {inputs} | {outputs} | {tools} | {duration} | {notes} |")
    return AgentOutput(updates={"xlsx_markdown": "\n".join(lines)})


def run_pdf_agent(ctx: AgentContext) -> AgentOutput:
    """
    Skill-aware PDF agent. When narrative_v2 is active, generates an executive
    narrative report. When sop_v2 is active, generates an SOP-style PDF report.
    Default produces a standard process report.
    """
    pm = _model(ctx)
    actx = (ctx.assembled_context or "").strip()
    primary = _primary_skill(ctx)
    skill_id = str((primary or {}).get("id") or "")
    deliverable = _deliverable_type_for_skill(skill_id)

    if is_claude_enabled():
        sb = _build_system_from_skill(
            ctx, "pdf",
            fallback_system=(
                "You are a management consultant authoring a client-facing report for PDF export. "
                "Audience: a senior decision-maker who reads the executive summary first. "
                "Tone: authoritative, factual, present tense. No hedging phrases. "
                "Return ONLY valid Markdown. The document must start with a # heading. No HTML. No preamble."
            ),
        )
        if deliverable == "narrative":
            user = (
                "Write an executive briefing note for PDF export from the ProcessModel and context below.\n\n"
                "Document structure — use EXACTLY these sections in this order:\n"
                "1. `# <process_name> — Executive Briefing` — H1 title\n"
                "2. `## What This Process Does` — 2–4 sentences: business outcome, initiator, beneficiaries\n"
                "3. `## Key Activities` — ≤6 bulleted items naming activity and owner role in ≤12 words each\n"
                "4. `## Roles and Accountability` — one bullet per role in ≤15 words\n"
                "5. `## Recommended Next Actions` — exactly 2–4 numbered items, ≤20 words each\n\n"
                "Constraints: no hedging language; no 'Context Used' section; no repeated information.\n\n"
                f"{process_model_json_block(pm)}\n"
                f"{context_excerpt_block(actx, 3500)}"
            )
        elif deliverable == "sop":
            user = (
                "Write an SOP-format report for PDF export from the ProcessModel below.\n\n"
                "Document structure:\n"
                "1. `# <process_name> — Standard Operating Procedure`\n"
                "2. `## Purpose` — 2–4 sentences\n"
                "3. `## Scope` — 1–2 sentences\n"
                "4. `## Roles` — bulleted list\n"
                "5. `## Procedure` — numbered steps from ProcessModel.steps\n"
                "6. `## Decision Points` — only if decisions is non-empty\n"
                "7. `## References` — Source: run instruction and project context\n\n"
                f"{process_model_json_block(pm)}"
            )
        elif deliverable == "proposal":
            p_skill = _primary_skill(ctx)
            _sid = str((p_skill or {}).get("id") or "").strip() or PROPOSAL_SKILL_ID
            contract = proposal_prompt_contract(
                "pdf", skill_id=_sid, skill_card=p_skill if isinstance(p_skill, dict) else None
            )
            sections = "\n".join(f"- {s}" for s in contract.get("sections", []))
            constraints = "\n".join(f"- {c}" for c in contract.get("constraints", []))
            user = (
                "Write a finance transformation proposal for PDF export.\n\n"
                "Use this section contract in the same order:\n"
                f"{sections}\n\n"
                "Proposal constraints:\n"
                f"{constraints}\n\n"
                "Formatting requirements:\n"
                "- Return only markdown with `#` title and `##` sections.\n"
                "- Include a concise value-case table (lever, impact, confidence, owner).\n"
                "- Include a 90-day workplan with milestones and governance cadence.\n\n"
                f"{process_model_json_block(pm)}\n"
                f"{context_excerpt_block(actx, 3500)}"
            )
        else:
            user = (
                "Write a consulting report for PDF export from the ProcessModel and context below.\n\n"
                "Document structure — use EXACTLY these sections in this order:\n"
                "1. `# <process_name> — Process Report` — H1 title\n"
                "2. `## Executive Summary` — 3–5 sentences: process purpose, owner, step count, outcome\n"
                "3. `## Workflow Overview` — numbered list, one item per step; "
                "format: `N. **<step.name>** _(owner: <step.role>)_`\n"
                "4. `## Operational Considerations` — 3–5 bullets from ProcessModel or context only; "
                "if none evident: 'No explicit risks or constraints were identified.'\n"
                "5. `## Next Actions` — exactly 3 numbered items, ≤25 words each\n\n"
                f"{process_model_json_block(pm)}\n"
                f"{context_excerpt_block(actx, 3500)}"
            )

        _pdf_feedback = ctx.plan_payload.get("pdf_visual_feedback") or []
        if _pdf_feedback and isinstance(_pdf_feedback, list):
            _pdf_hints = "\n".join(
                f"- {h.get('instruction', '')}" for h in _pdf_feedback
                if isinstance(h, dict) and h.get("instruction")
            )
            if _pdf_hints:
                user += f"\n\nVisual QA feedback from previous generation (must be addressed):\n{_pdf_hints}"

        _pdf_narrative = ctx.plan_payload.get("pdf_narrative_feedback") or []
        if _pdf_narrative and isinstance(_pdf_narrative, list):
            _pdf_narrative_hints = "\n".join(
                f"- {h.get('instruction', '')}" for h in _pdf_narrative
                if isinstance(h, dict) and h.get("instruction")
            )
            if _pdf_narrative_hints:
                user += (
                    "\n\nNarrative coherence feedback from previous generation "
                    "(must be addressed — tighten arc, transitions, and topic continuity):\n"
                    f"{_pdf_narrative_hints}"
                )
        md = _run_subagent_tool_loop_text(ctx, agent_id="pdf", system=sb.system, user=user,
                                          temperature=sb.temperature, max_rounds=sb.max_rounds)
        if not md:
            try:
                md = claude_generate(system=sb.system, user=user, temperature=sb.temperature, max_tokens=1800)
            except Exception:
                md = None
        if isinstance(md, str) and md.strip():
            md = _apply_quality_gate(ctx, "pdf", md, system=sb.system, temperature=sb.temperature)
            md = _run_post_processor(ctx, md)
            return AgentOutput(updates={"pdf_markdown": md})

    if deliverable == "proposal":
        title = pm.get("process_name") or "Finance Transformation Proposal"
        lines = [
            f"# {title}",
            "",
            "## Executive Summary",
            "This proposal summarizes transformation intent, value opportunities, and a phased execution path.",
            "",
            "## Workstreams and Timeline",
            "1. Mobilize and baseline",
            "2. Design and pilot",
            "3. Scale and stabilize",
            "",
            "## Value Case",
            "| Lever | Impact | Confidence | Owner |",
            "|---|---|---|---|",
            "| Close acceleration | [TBC] | Medium | CFO office |",
            "",
            "## Risks and Mitigations",
            "- Delivery capacity constraints -> phased rollout and governance cadence.",
            "",
            "## Next Steps",
            "1. Validate assumptions with finance and controllership teams.",
            "2. Finalize pilot scope and decision checkpoints.",
        ]
        return AgentOutput(updates={"pdf_markdown": "\n".join(lines)})
    title = pm.get("process_name") or "Process Report"
    steps = pm.get("steps") or []
    lines = [
        f"# {title}",
        "",
        "## Executive Summary",
        "",
        f"This report summarizes the process across {len(steps)} extracted step(s).",
        "",
        "## Workflow Overview",
        "",
    ]
    for i, st in enumerate(steps[:20], start=1):
        if not isinstance(st, dict):
            continue
        lines.append(f"{i}. **{st.get('name') or 'Step'}** — {st.get('role') or 'TBD'}")
    lines.extend(["", "## Next Actions", "", "- Validate step ownership", "- Finalize deliverable formatting"])
    return AgentOutput(updates={"pdf_markdown": "\n".join(lines)})


def run_docx_agent(ctx: AgentContext) -> AgentOutput:
    """
    Skill-aware DOCX agent. Content type (SOP, narrative, RACI, BRD, generic)
    is determined by the active primary skill. The skill's system prompt and
    the deliverable-specific user prompt together drive generation.
    """
    pm = _model(ctx)
    actx = (ctx.assembled_context or "").strip()
    primary = _primary_skill(ctx)
    skill_id = str((primary or {}).get("id") or "")
    deliverable = _deliverable_type_for_skill(skill_id)

    if is_claude_enabled():
        sb = _build_system_from_skill(
            ctx, "docx",
            fallback_system=(
                "You are a technical documentation author preparing a DOCX-ready procedure document. "
                "Audience: an internal team member who will follow this document during execution. "
                "Heading hierarchy: # for title (H1), ## for main sections (H2), ### for sub-sections (H3). "
                "Return ONLY valid Markdown. The document must start with a # heading. No HTML. No preamble. "
                "Do not include YAML front matter."
            ),
        )

        # Select the user prompt based on the active deliverable type
        if deliverable == "sop":
            user = (
                "Write a Standard Operating Procedure (SOP) from the ProcessModel below.\n\n"
                "Document structure — use EXACTLY these sections in this order:\n"
                "1. `# <process_name>` — H1 title only\n"
                "2. `## Purpose` — 2–4 sentences: what problem this process solves and who benefits\n"
                "3. `## Scope` — 1–2 sentences: what is covered and what is explicitly out of scope\n"
                "4. `## Roles` — bulleted list of each role with a one-sentence mandate\n"
                "5. `## Procedure` — numbered list, one item per step; "
                "format: `N. **<step.name>** _(role: <step.role>)_` with sub-bullets for inputs/outputs/tools if non-empty\n"
                "6. `## Decision Points` — only if decisions is non-empty; omit entirely otherwise\n"
                "7. `## References` — single bullet: 'Source: run instruction and assembled project context'\n\n"
                "Length constraint: ≤80 words per section (Purpose, Scope). "
                "Do not add sections beyond the seven listed above.\n\n"
                f"{process_model_json_block(pm)}"
            )
        elif deliverable == "narrative":
            user = (
                "Write an executive briefing note from the ProcessModel and context excerpt below.\n\n"
                "Document structure — use EXACTLY these sections in this order:\n"
                "1. `# <process_name> — Executive Briefing` — H1 title\n"
                "2. `## What This Process Does` — 2–4 sentences: business outcome, who initiates it, who benefits\n"
                "3. `## Key Activities` — ≤6 bulleted items naming activity and owner role in ≤12 words each\n"
                "4. `## Roles and Accountability` — one bullet per role in ≤15 words\n"
                "5. `## Recommended Next Actions` — exactly 2–4 numbered items, ≤20 words each, specific to this process\n\n"
                "Constraints: no hedging language; no 'Context Used' section; no section repetition.\n\n"
                f"{process_model_json_block(pm)}\n"
                f"{context_excerpt_block(actx, 4000)}"
            )
        elif deliverable == "raci":
            user = (
                "Build a RACI matrix document from the ProcessModel below.\n\n"
                "Document structure:\n"
                "1. `# RACI Matrix — <process_name>` — H1 title\n"
                "2. `## Assignment Rules` — 2-sentence explanation of R/A/C/I definitions\n"
                "3. `## RACI Table` — Markdown table with columns: "
                "Activity | Responsible | Accountable | Consulted | Informed\n"
                "   Assignment rules: R = step.role; A = first role in roles[] or most senior; "
                "C/I = remaining roles; exactly one A per row; use '—' for empty cells.\n\n"
                "Return ONLY valid Markdown starting with the # heading.\n\n"
                f"{process_model_json_block(pm)}"
            )
        elif deliverable == "proposal":
            p_skill = _primary_skill(ctx)
            _sid = str((p_skill or {}).get("id") or "").strip() or PROPOSAL_SKILL_ID
            contract = proposal_prompt_contract(
                "docx", skill_id=_sid, skill_card=p_skill if isinstance(p_skill, dict) else None
            )
            discovery = (ctx.plan_payload or {}).get("discovery") if isinstance((ctx.plan_payload or {}).get("discovery"), dict) else {}
            discovery_client = discovery.get("client") if isinstance(discovery.get("client"), dict) else {}
            discovery_outcome = discovery.get("outcome") if isinstance(discovery.get("outcome"), dict) else {}
            discovery_themes = discovery.get("win_themes") if isinstance(discovery.get("win_themes"), list) else []
            discovery_block = (
                "Discovery context:\n"
                f"- Client: {discovery_client.get('name', '')} ({discovery_client.get('industry', '')})\n"
                f"- Target outcome: {discovery_outcome.get('primary', '')}\n"
                f"- Decision to enable: {discovery_outcome.get('decision', '')}\n"
                f"- Win themes: {', '.join(str(x) for x in discovery_themes[:3])}\n\n"
                if discovery
                else ""
            )
            sections = "\n".join(f"- {s}" for s in contract.get("sections", []))
            constraints = "\n".join(f"- {c}" for c in contract.get("constraints", []))
            user = (
                "Write a finance transformation proposal document suitable for DOCX export.\n\n"
                "Use this section contract in the same order:\n"
                f"{sections}\n\n"
                "Proposal constraints:\n"
                f"{constraints}\n\n"
                "Document requirements:\n"
                "- Use `#` for the document title and `##` for each contract section.\n"
                "- Add a quantified value case with assumptions and confidence levels.\n"
                "- Include implementation workstreams, sequencing, and ownership by role.\n"
                "- Include risks, mitigations, and measurable success criteria.\n\n"
                + discovery_block
                + f"{process_model_json_block(pm)}\n"
                + f"{context_excerpt_block(actx, 4000)}"
            )
        elif deliverable == "brd":
            user = (
                "Write a Business Requirements Document (BRD) from the ProcessModel and context below.\n\n"
                "Document structure — use these sections:\n"
                "1. `# Business Requirements Document — <process_name>`\n"
                "2. `## Executive Summary` — 3–5 sentences on business need and objectives\n"
                "3. `## Current State` — describe the process as extracted from the ProcessModel\n"
                "4. `## Business Requirements` — numbered list of ≥5 specific, measurable requirements\n"
                "5. `## Roles and Stakeholders` — one bullet per role with responsibility\n"
                "6. `## Success Criteria` — 3–5 measurable criteria\n"
                "7. `## References` — Source: run instruction and project context\n\n"
                f"{process_model_json_block(pm)}\n"
                f"{context_excerpt_block(actx, 3000)}"
            )
        else:
            # Generic DOCX — procedure document
            user = (
                "Write a procedure document for DOCX export from the ProcessModel below.\n\n"
                "Document structure — use EXACTLY these sections in this order:\n"
                "1. `# <process_name>` — H1 title only\n"
                "2. `## Purpose` — 2–4 sentences: the business reason this process exists\n"
                "3. `## Scope` — 2–3 sentences: activities and systems covered\n"
                "4. `## Roles and Responsibilities` — one bullet per role with mandate\n"
                "5. `## Procedure` — numbered steps matching ProcessModel.steps exactly\n"
                "6. `## Governance and Controls` — include only if ProcessModel.decisions is non-empty\n"
                "7. `## References` — single bullet: 'Source: run instruction and assembled project context'\n\n"
                "Constraints: Purpose and Scope ≤80 words each. "
                "Do not invent controls not present in the ProcessModel.\n\n"
                f"{process_model_json_block(pm)}"
            )

        _docx_feedback = ctx.plan_payload.get("docx_visual_feedback") or []
        if _docx_feedback and isinstance(_docx_feedback, list):
            _docx_hints = "\n".join(
                f"- {h.get('instruction', '')}" for h in _docx_feedback
                if isinstance(h, dict) and h.get("instruction")
            )
            if _docx_hints:
                user += f"\n\nVisual QA feedback from previous generation (must be addressed):\n{_docx_hints}"

        _docx_narrative = ctx.plan_payload.get("docx_narrative_feedback") or []
        if _docx_narrative and isinstance(_docx_narrative, list):
            _docx_narrative_hints = "\n".join(
                f"- {h.get('instruction', '')}" for h in _docx_narrative
                if isinstance(h, dict) and h.get("instruction")
            )
            if _docx_narrative_hints:
                user += (
                    "\n\nNarrative coherence feedback from previous generation "
                    "(must be addressed — tighten arc, transitions, and topic continuity):\n"
                    f"{_docx_narrative_hints}"
                )
        user = _append_conversation_digest_block(user, ctx)
        md = _run_subagent_tool_loop_text(ctx, agent_id="docx", system=sb.system, user=user,
                                          temperature=sb.temperature, max_rounds=sb.max_rounds)
        if not md:
            try:
                md = claude_generate(system=sb.system, user=user, temperature=sb.temperature, max_tokens=2200)
            except Exception:
                md = None
        if isinstance(md, str) and md.strip():
            md = _apply_quality_gate(ctx, "docx", md, system=sb.system, temperature=sb.temperature)
            md = _run_post_processor(ctx, md)
            return AgentOutput(updates={"docx_markdown": md})

    # Deterministic fallback — deliverable-aware
    return AgentOutput(updates={"docx_markdown": _docx_deterministic_fallback(pm, deliverable)})


def _docx_deterministic_fallback(pm: ProcessModel, deliverable: str) -> str:
    """Deterministic DOCX content for when Claude is unavailable."""
    name = pm.get("process_name") or "Process Document"
    steps = pm.get("steps") or []
    roles = pm.get("roles") or []
    roles_str = ", ".join(roles)

    if deliverable == "sop":
        lines = [f"# {name}", "", "## Purpose", "",
                 "This procedure documents the workflow extracted from the engagement instruction.", "",
                 "## Scope", "", roles_str or "_Roles not specified._", "", "## Roles", ""]
        for r in roles:
            lines.append(f"- **{r}**")
        lines += ["", "## Procedure", ""]
        for i, st in enumerate(steps, 1):
            lines.append(f"{i}. **{st.get('name') or 'Step'}** _(role: {st.get('role') or 'TBD'})_")
        lines += ["", "## References", "", "- Source: run instruction and assembled project context."]
        return "\n".join(lines).strip() + "\n"

    elif deliverable == "narrative":
        n_steps = len(steps)
        n_roles = len(roles)
        highlights = "; ".join(s.get("name", "") for s in steps[:5])
        if len(steps) > 5:
            highlights += "; …"
        lines = [f"# {name} — Executive Briefing", "", "## What This Process Does", "",
                 f"This process covers **{name}**, structured across **{n_steps}** step(s) and **{n_roles}** role(s). "
                 f"Key activities include: {highlights}.", "", "## Key Activities", ""]
        for st in steps[:6]:
            lines.append(f"- **{st.get('name', '—')}** _(owner: {st.get('role', 'TBD')})_")
        lines += ["", "## Roles and Accountability", ""]
        for r in roles:
            lines.append(f"- **{r}**: accountable for their assigned steps in this process")
        lines += ["", "## Recommended Next Actions", "",
                  "1. Validate step ownership with process owners.",
                  "2. Confirm tooling and systems referenced in source materials."]
        return "\n".join(lines).strip() + "\n"

    elif deliverable == "raci":
        accountable = roles[0] if roles else "Process Owner"
        lines = [f"# RACI Matrix — {name}", "", "## Assignment Rules", "",
                 "R = Responsible (executes). A = Accountable (owns outcome, exactly one per row). "
                 "C = Consulted (input required). I = Informed (notified).", "",
                 "## RACI Table", "",
                 "| Activity | Responsible | Accountable | Consulted | Informed |",
                 "|---|---|---|---|---|"]
        for st in steps:
            nm = (st.get("name") or "—").replace("|", "\\|")
            resp = (st.get("role") or "—").replace("|", "\\|")
            others = [r for r in roles if r not in (st.get("role"), accountable)]
            cons = (", ".join(others[:3]) if others else "—").replace("|", "\\|")
            lines.append(f"| {nm} | {resp} | {accountable} | {cons} | — |")
        return "\n".join(lines).strip() + "\n"
    elif deliverable == "proposal":
        lines = [
            f"# Finance Transformation Proposal — {name}",
            "",
            "## Executive Summary",
            "This proposal outlines a pragmatic finance transformation path, value case, and delivery approach.",
            "",
            "## Current State and Problem Statement",
            "Current-state process complexity and handoff friction are captured in the extracted workflow model.",
            "",
            "## Target Operating Model",
            "Define future-state process ownership, governance, and standardization priorities.",
            "",
            "## Workstreams and Timeline",
            "1. Mobilize and baseline",
            "2. Design and pilot",
            "3. Scale and stabilize",
            "",
            "## Value Case",
            "| Lever | Impact | Confidence | Owner |",
            "|---|---|---|---|",
            "| Close acceleration | [TBC] | Medium | CFO office |",
            "",
            "## Risks and Mitigations",
            "- Change adoption risk -> run role-based enablement and governance cadence.",
            "",
            "## Next Steps",
            "1. Validate assumptions with finance leadership.",
            "2. Approve pilot scope and governance forum.",
        ]
        return "\n".join(lines).strip() + "\n"

    else:
        # Generic
        lines = [f"# {name}", "", "## Purpose", "Documented procedure for operational execution.", "",
                 "## Procedure"]
        for i, st in enumerate(steps[:30], 1):
            if isinstance(st, dict):
                lines.append(f"{i}. {st.get('name') or 'Step'} ({st.get('role') or 'TBD'})")
        return "\n".join(lines)


def _shared_user_context_appendix(ctx: AgentContext) -> str:
    """
    Build the user-prompt context appendix with labelled sections.

    For PPTX output, context is segmented by purpose so the model can
    locate the right facts for each slide type without scanning 30KB:
      - QUANTITATIVE METRICS  → stat_cards slides
      - PAIN POINTS           → problem statement slides
      - VALUE DRIVERS & ROI   → value case slides
      - LEADING PRACTICES     → credibility / case study slides
    """
    blocks: list[str] = []
    ui = ctx.user_instruction.strip()
    if ui:
        blocks.append(f"## User instruction\n{ui[:2200]}")

    ac = ctx.assembled_context.strip()
    if ac and ctx.output_type == "pptx":
        # ── Labelled context for PPTX: segment by slide purpose ──────────
        # Split assembled_context into purpose-labelled sections so the model
        # can find the right facts per slide without scanning the entire blob.
        enrichment = ctx.enrichment
        metrics_parts: list[str] = []
        value_parts: list[str] = []

        # Extract structured metrics from enrichment if available
        if enrichment:
            steps = getattr(enrichment, "steps_count", None) or (
                getattr(getattr(enrichment, "process_analytics", None), "steps_count", None)
            )
            roles = getattr(enrichment, "roles_count", None) or (
                getattr(getattr(enrichment, "process_analytics", None), "roles_count", None)
            )
            systems = getattr(enrichment, "systems_count", None)
            if steps or roles or systems:
                metrics_parts.append(
                    f"Process scale: {steps or '[TBC]'} steps, "
                    f"{roles or '[TBC]'} roles, {systems or '[TBC]'} systems"
                )

            drivers = getattr(enrichment, "value_drivers", [])
            if isinstance(drivers, list) and drivers:
                driver_names = [
                    str(d.get("name") if isinstance(d, dict) else d)
                    for d in drivers[:5] if d
                ]
                value_parts.append("Value drivers: " + ", ".join(n for n in driver_names if n))

            risks_obj = getattr(enrichment, "risk_profile", None)
            risks = getattr(risks_obj, "risks", []) if risks_obj else []
            if isinstance(risks, list) and risks:
                risk_names = [
                    str(r.get("name") if isinstance(r, dict) else r)
                    for r in risks[:5] if r
                ]
                value_parts.append("Key risks: " + ", ".join(n for n in risk_names if n))

        # Build labelled sections
        labelled: list[str] = []
        if metrics_parts:
            labelled.append(
                "## QUANTITATIVE METRICS (use for stat_cards slides)\n" + "\n".join(metrics_parts)
            )

        # Scan assembled_context for pain-point / current-state signals
        ac_lower = ac.lower()
        has_pain = any(kw in ac_lower for kw in ("pain point", "challenge", "problem", "current state", "issue", "gap"))
        has_value = any(kw in ac_lower for kw in ("saving", "roi", "cost reduction", "benefit", "improvement", "value"))
        has_lp = any(kw in ac_lower for kw in ("case study", "leading practice", "benchmark", "reference"))

        if has_pain:
            labelled.append("## PAIN POINTS & CURRENT STATE (use for problem statement slides)")
        if has_value and value_parts:
            labelled.append(
                "## VALUE DRIVERS & ROI (use for value case slides)\n" + "\n".join(value_parts)
            )
        elif value_parts:
            labelled.append("## VALUE DRIVERS\n" + "\n".join(value_parts))
        if has_lp:
            labelled.append("## LEADING PRACTICES & CASE STUDIES (use for credibility slides)")

        if labelled:
            # Prepend labels, then include full context below
            label_block = "\n\n".join(labelled)
            blocks.append(
                f"## Assembled project context (labelled for slide generation)\n"
                f"{label_block}\n\n"
                f"## Full context\n{ac[:3500]}"
            )
        else:
            blocks.append(f"## Assembled project context (excerpt)\n{ac[:3500]}")
    elif ac:
        blocks.append(f"## Assembled project context (excerpt)\n{ac[:3500]}")

    pae = ctx.prior_artifacts_excerpt.strip()
    if pae:
        blocks.append(pae)
    enrichment_context = str(getattr(ctx.enrichment, "context_snippets", "") or "").strip()
    if enrichment_context:
        blocks.append(f"## Prior artifacts context\n{enrichment_context[:2200]}")
    if not blocks:
        return ""
    return wrap_untrusted_bundle("\n\n".join(blocks) + "\n\n---\n\n")


def _pptx_visual_feedback_indices(feedback: list[Any]) -> set[int]:
    """1-based slide indices from Visual QA remediation_hints."""
    idxs: set[int] = set()
    for h in feedback:
        if not isinstance(h, dict):
            continue
        raw = h.get("slide_index")
        if isinstance(raw, int) and raw >= 1:
            idxs.add(raw)
        elif isinstance(raw, float) and raw >= 1.0:
            idxs.add(int(raw))
        elif isinstance(raw, str) and raw.strip().isdigit():
            idxs.add(int(raw.strip()))
    return idxs


def _merge_pptx_slides_repair(
    prior: list[dict[str, Any]],
    repaired: list[dict[str, Any]],
    fix_indices_1based: set[int],
) -> list[dict[str, Any]]:
    """Prefer prior slides; overwrite positions flagged by Visual QA when the model returned a dict."""
    out: list[dict[str, Any]] = [dict(s) for s in prior]
    if not fix_indices_1based:
        return repaired if repaired else out
    for j in range(len(out)):
        if (j + 1) in fix_indices_1based and j < len(repaired) and isinstance(repaired[j], dict):
            out[j] = repaired[j]
    return out


def _normalize_pptx_slide_identities(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure stable slide/element identities for targeted regeneration workflows."""
    normalized: list[dict[str, Any]] = []
    collection_key_map: dict[str, str] = {
        "stat_cards": "card_id",
        "column_cards": "card_id",
        "stack_layers": "layer_id",
    }
    for idx, raw_slide in enumerate(slides, start=1):
        if not isinstance(raw_slide, dict):
            continue
        slide = dict(raw_slide)
        if not str(slide.get("slide_id") or "").strip():
            slide["slide_id"] = f"slide_{idx:02d}"
        slide.setdefault("slide_index", idx)
        for key, id_field in collection_key_map.items():
            value = slide.get(key)
            if not isinstance(value, list):
                continue
            out_items: list[Any] = []
            for item_idx, item in enumerate(value, start=1):
                if isinstance(item, dict):
                    next_item = dict(item)
                    if not str(next_item.get(id_field) or "").strip():
                        next_item[id_field] = f"{slide['slide_id']}_{key}_{item_idx:02d}"
                    out_items.append(next_item)
                else:
                    out_items.append(item)
            slide[key] = out_items
        bullets = slide.get("bullets")
        if isinstance(bullets, list) and bullets:
            slide.setdefault(
                "bullet_ids",
                [f"{slide['slide_id']}_bullets_{i:02d}" for i in range(1, len(bullets) + 1)],
            )
        normalized.append(slide)
    return normalized


def _pptx_deterministic_slides(pm: ProcessModel) -> list[dict[str, Any]]:
    """Full minimal deck when Claude is off or JSON fails — matches pptx_v1 mandatory sequence."""
    steps = pm.get("steps") or []
    roles = pm.get("roles") or []
    process_name = str(pm.get("process_name") or "Process Overview")
    n_s, n_r = len(steps), len(roles)
    fill_rot = ["dark", "mid_dark", "green", "gray", "mid", "dark_green"]
    step_src = steps or [{"name": "No steps extracted", "description": "", "role": "TBD"}]
    stack: list[dict[str, Any]] = []
    for i, s in enumerate(step_src[:6]):
        if isinstance(s, dict):
            stack.append(
                {
                    "label": str(s.get("name") or "Step")[:40],
                    "description": str(s.get("description") or f"Owner: {s.get('role') or 'TBD'}")[:100],
                    "fill": fill_rot[i % len(fill_rot)],
                }
            )
        else:
            stack.append({"label": f"Step {i + 1}", "description": "", "fill": fill_rot[i % len(fill_rot)]})

    role_bullets = [f"{r}: accountable for assigned activities in this process." for r in roles[:8]]
    if not role_bullets:
        role_bullets = ["Define process ownership and RACI with stakeholders."]

    table_rows: list[list[str]] = []
    for st in steps[:12]:
        if not isinstance(st, dict):
            continue
        ins = str(st.get("inputs") or "—")
        outs = str(st.get("outputs") or "—")
        io = f"{ins} → {outs}"
        table_rows.append(
            [
                str(st.get("name") or "—")[:40],
                str(st.get("role") or "TBD")[:30],
                io[:80],
            ]
        )
    if not table_rows:
        table_rows = [["—", "TBD", "See process documentation"]]

    return [
        {
            "title": process_name,
            "slide_type": "title",
            "subtitle": "Process Overview",
            "badges": [
                f"{n_s} workflow steps",
                f"{n_r} roles",
                "ProcessDoc Studio",
            ],
        },
        {
            "title": "Process scale",
            "slide_type": "stat_cards",
            "stat_cards": [
                {
                    "stat": str(n_s),
                    "label": "workflow steps\ncaptured in model",
                    "description": "Step count shows scope of the process for prioritization and control design.",
                    "fill": "dark",
                },
                {
                    "stat": str(n_r),
                    "label": "distinct roles\ninvolved",
                    "description": "Role coverage highlights handoffs and accountability surfaces.",
                    "fill": "mid_dark",
                },
                {
                    "stat": "[TBC]",
                    "label": "SLA / run rate\n(to validate)",
                    "description": "Quantify cycle time or frequency when operational data is available.",
                    "fill": "gray",
                },
            ],
        },
        {
            "title": "Operating pillars",
            "slide_type": "column_cards",
            "column_cards": [
                {
                    "heading": "Governance",
                    "accent": "green",
                    "body": "Controls, approvals, and policy checkpoints that keep the process compliant and auditable.",
                },
                {
                    "heading": "Execution",
                    "accent": "dark",
                    "body": "Day-to-day activities, handoffs, and tooling used to move work from intake to completion.",
                },
                {
                    "heading": "Insight",
                    "accent": "gray",
                    "body": "Metrics and feedback loops that expose bottlenecks and drive continuous improvement.",
                },
            ],
        },
        {
            "title": "Workflow layers",
            "slide_type": "stack_layers",
            "stack_layers": stack,
        },
        {
            "title": "Role mandates",
            "slide_type": "bullets",
            "bullets": role_bullets[:8],
        },
        {
            "title": "Workflow walkthrough",
            "slide_type": "table",
            "table": {
                "headers": ["Step", "Owner", "Inputs → Outputs"],
                "rows": table_rows,
                "x": 0.28,
                "y": 1.0,
                "w": 9.44,
                "h": 4.3,
            },
        },
        {
            "title": "Controls and metrics",
            "slide_type": "stat_cards",
            "stat_cards": [
                {
                    "stat": "[TBC]",
                    "label": "key control\npoints",
                    "description": "Map critical controls to steps once the control framework is agreed.",
                    "fill": "dark",
                },
                {
                    "stat": "[TBC]",
                    "label": "error or\nexception rate",
                    "description": "Track defect or rework rates where systems provide operational data.",
                    "fill": "mid_dark",
                },
                {
                    "stat": "[TBC]",
                    "label": "cycle time\nor SLA",
                    "description": "Baseline throughput targets after measuring end-to-end lead time.",
                    "fill": "gray",
                },
            ],
        },
        {
            "title": "Recommended next actions",
            "slide_type": "bullets",
            "bullets": [
                "1. Validate ownership per workflow step with process owners.",
                "2. Confirm control checks and handoffs against policy.",
                "3. Approve delivery format and communication plan.",
            ],
        },
    ]


def _generate_slides_batched(
    ctx: AgentContext,
    *,
    system: str,
    user_core: str,
    appendix: str,
    pm: dict,
    outline: list[dict],
    temperature: float = 0.3,
    max_rounds: int | None = None,
) -> list[dict] | None:
    """
    Generate slides in batches of 4-5, guided by the deck outline preview.

    Each batch receives the outline for its slides plus context from prior batches,
    enabling intermediate validation and better quality for long decks.
    Returns the combined slide list, or None if any batch fails critically.
    """
    batch_size = 4
    all_slides: list[dict] = []
    n_total = len(outline)

    for batch_start in range(0, n_total, batch_size):
        batch_end = min(batch_start + batch_size, n_total)
        batch_outline = outline[batch_start:batch_end]

        # Build the batch-specific prompt
        outline_desc = "\n".join(
            f"  {batch_start + i + 1}. [{s.get('slide_type', 'bullets')}] {s.get('title', '')} — {s.get('purpose', '')}"
            for i, s in enumerate(batch_outline)
        )
        batch_instruction = (
            f"Generate slides {batch_start + 1}–{batch_end} of {n_total} for this deck.\n"
            f"Follow this outline for these slides:\n{outline_desc}\n\n"
            "Return ONLY valid JSON: {\"slides\": [...]}\n"
            "Each slide must match the outline entry's title and slide_type.\n"
        )
        if all_slides:
            # Provide prior slides as context for continuity
            prior_summary = json.dumps(
                [{"title": s.get("title"), "slide_type": s.get("slide_type")} for s in all_slides],
                ensure_ascii=False,
            )
            batch_instruction += f"\nPrior slides already generated (maintain continuity):\n{prior_summary}\n"

        batch_user = batch_instruction + "\n" + user_core + appendix + f"{process_model_json_block(pm)}"

        raw_json = _run_subagent_tool_loop_text(
            ctx, agent_id="pptx", system=system, user=batch_user,
            temperature=temperature, max_rounds=max_rounds,
        )
        batch_obj: dict | None = None
        if raw_json:
            try:
                batch_obj = _extract_first_json_object(raw_json)
            except Exception:
                batch_obj = None
        if not batch_obj:
            try:
                batch_obj = claude_generate_json(system=system, user=batch_user, temperature=temperature, max_tokens=4096)
            except Exception:
                batch_obj = None

        batch_slides = batch_obj.get("slides") if isinstance(batch_obj, dict) else None
        if isinstance(batch_slides, list) and batch_slides:
            valid = [s for s in batch_slides if isinstance(s, dict) and s.get("title")]
            all_slides.extend(valid)
        else:
            # Batch failed — fall back to single-shot generation
            _session_debug_log(
                run_id=ctx.run_id,
                hypothesis_id="H5",
                location="subagents.py:_generate_slides_batched:batch_fail",
                message=f"Batch {batch_start + 1}-{batch_end} failed, aborting batched mode",
                data={"batch_start": batch_start, "batch_end": batch_end},
            )
            return None

    return all_slides if all_slides else None


def _resolve_presentation_title(pm: dict, state: dict) -> str:
    """
    Return the best available presentation title.

    Validates pm["process_name"] and falls back gracefully:
    1. Use pm["process_name"] if it looks like a real title (not a chat message or annotation).
    2. Else: use first meaningful line from user_intent_original.
    3. Final fallback: "Process Overview".

    Rules are domain-agnostic — no hardcoded domain keywords.
    """
    _CHAT_MARKERS = ("assistant:", "user:", "👋", "💬", "🎯", "🚀", "qa remediation", "guardrail")
    name = (pm.get("process_name") or "").strip()
    name_lower = name.lower()
    if name and 5 <= len(name) <= 120 and not any(m in name_lower for m in _CHAT_MARKERS):
        return name
    # Fall back to user intent
    intent = (state.get("user_intent_original") or "").strip()
    if intent:
        first_line = intent.splitlines()[0].strip()
        if 5 <= len(first_line) <= 120:
            return first_line
    return "Process Overview"


def run_pptx_agent(ctx: AgentContext) -> AgentOutput:
    pm = _model(ctx)
    primary = _primary_skill(ctx) or {}
    # region agent log
    _session_debug_log(
        run_id=ctx.run_id,
        hypothesis_id="H4",
        location="subagents.py:run_pptx_agent:entry",
        message="PPTX agent entered",
        data={
            "claude_enabled": bool(is_claude_enabled()),
            "primary_skill_id": str(primary.get("id") or ""),
            "primary_skill_display_name": str(primary.get("display_name") or ""),
            "assembled_context_chars": len(str(ctx.assembled_context or "")),
            "process_model_steps": len(pm.get("steps") or []) if isinstance(pm, dict) else 0,
            "skill_instruction_chars": len(str(_skill_instruction(ctx, "pptx") or "")),
        },
    )
    # endregion
    if is_claude_enabled():
        sb = _build_system_from_skill(
            ctx, "pptx",
            fallback_system=(
                "You are a Deloitte presentation strategist producing a slide blueprint for python-pptx rendering. "
                "Use varied, professional slide types — not just bullet lists. "
                "Return ONLY a JSON object with a single top-level key 'slides' containing an array. "
                "No prose, no markdown fences, no explanation. The JSON must be parseable with json.loads().\n\n"
                "CRITICAL: Always populate slides with actual data. Never generate empty arrays for stat_cards, column_cards, or table rows.\n\n"
                "EXAMPLE — stat_cards slide (slide_type=\"stat_cards\"):\n"
                '{"slide_type": "stat_cards", "title": "Process Scale & Scope", "stat_cards": [\n'
                '  {"stat": "14", "label": "Process Steps", "description": "End-to-end procure-to-pay workflow", "fill": "dark"},\n'
                '  {"stat": "5", "label": "Key Roles", "description": "Procurement, Finance, Stores, Treasury, Vendors", "fill": "mid_dark"},\n'
                '  {"stat": "$450M", "label": "Annual Spend", "description": "High-volume P2P spanning organization", "fill": "gray"}\n'
                ']}\n\n'
                "EXAMPLE — column_cards slide (slide_type=\"column_cards\"):\n"
                '{"slide_type": "column_cards", "title": "Three Pillars", "column_cards": [\n'
                '  {"heading": "Governance", "accent": "green", "body": "Centralize vendor master; enforce controls"},\n'
                '  {"heading": "Quality", "accent": "dark", "body": "Activate QM module; block failures"},\n'
                '  {"heading": "Automation", "accent": "gray", "body": "OCR invoices; DMEE payment integration"}\n'
                ']}\n\n'
                "EXAMPLE — table slide (slide_type=\"table\"):\n"
                '{"slide_type": "table", "title": "Workflow Steps", "table": {\n'
                '  "headers": ["Step", "Owner", "Inputs → Outputs"],\n'
                '  "rows": [\n'
                '    ["1. Create PR", "Dept Head", "Material list → PR in ME51N"],\n'
                '    ["2. Countersign", "Finance", "PR >INR 50K → Approved"],\n'
                '    ["3. Create PO", "Procurement", "PR → PO in ME21N"]\n'
                "  ]\n"
                '}}\n\n'
                "RULE: Do NOT generate empty stat_cards=[], column_cards=[], or table.rows=[]. Always populate with real data.\n"
            ),
        )
        plan_discovery = (ctx.plan_payload or {}).get("discovery") if isinstance((ctx.plan_payload or {}).get("discovery"), dict) else {}
        is_proposal_skill = bool(str(primary.get("id") or "").startswith("proposal_")) if isinstance(primary, dict) else False
        n_steps = len(pm.get("steps") or [])
        discovery_budget = (plan_discovery.get("length_budget") if isinstance(plan_discovery.get("length_budget"), dict) else {})
        budget_pptx = int(discovery_budget.get("pptx")) if str(discovery_budget.get("pptx") or "").isdigit() else None
        if is_proposal_skill and budget_pptx:
            n_slides_guidance = f"{max(6, min(budget_pptx, 20))} slides"
        elif n_steps <= 3:
            n_slides_guidance = "6 slides"
        elif n_steps <= 6:
            n_slides_guidance = "7–8 slides"
        else:
            n_slides_guidance = "8–10 slides"

        # ── Inject enriched context metrics (Phase 1 fix) ──────────────────────
        enrichment = ctx.enrichment
        analytics = getattr(enrichment, "process_analytics", None) if enrichment else None
        steps_count = analytics.steps_count if analytics else n_steps
        roles_count = analytics.roles_count if analytics else len(set(s.get("role") or s.get("owner") for s in pm.get("steps", []) if isinstance(s, dict)))
        analytics.decision_points if analytics else len(pm.get("decisions", []) or [])
        systems_count = len(pm.get("systems", [])) if isinstance(pm.get("systems"), list) else 3

        # Extract risks and value drivers from enrichment
        risk_profile = getattr(enrichment, "risk_profile", None) if enrichment else None
        risk_profile.risks if risk_profile else pm.get("risks", [])
        getattr(enrichment, "value_drivers", []) if enrichment else pm.get("improvement_opportunities", [])

        # Build data injection for key slides
        data_for_slide_2 = (
            f"\nDATA FOR SLIDE 2 (stat_cards) — MUST POPULATE WITH THESE METRICS:\n"
            f"- Card 1: stat=\"{steps_count}\", label=\"Process Steps\", "
            f"description=\"End-to-end workflow from initiation to completion\"\n"
            f"- Card 2: stat=\"{roles_count}\", label=\"Key Roles\", "
            f"description=\"Departments and stakeholders involved in execution\"\n"
            f"- Card 3: stat=\"{systems_count}\", label=\"System Touchpoints\", "
            f"description=\"Applications and tools required for automation\"\n"
        )

        extracted_metrics = pm.get("metrics") or []
        if extracted_metrics and isinstance(extracted_metrics, list):
            metric_hints = "\n".join(
                f"  - stat=\"{m.get('stat', '')}\", label=\"{m.get('label', '')}\", "
                f"source=\"{m.get('source', 'inferred from context')}\""
                for m in extracted_metrics[:3]
                if isinstance(m, dict) and m.get("stat") and m.get("label")
            )
            if metric_hints:
                data_for_slide_7 = (
                    f"\nDATA FOR SLIDE 7 (stat_cards) — use these extracted metrics:\n"
                    f"{metric_hints}\n"
                    "Each card MUST have stat, label, and description. "
                    "Cite source inline using the source field provided.\n"
                )
            else:
                data_for_slide_7 = (
                    "\nDATA FOR SLIDE 7 (stat_cards) — derive 3 metrics from the ProcessModel "
                    "(cycle time, error rate, control points, SLA, or volume counts). "
                    "Each card needs stat, label, description. Use [TBC] only if truly unquantifiable.\n"
                )
        else:
            data_for_slide_7 = (
                "\nDATA FOR SLIDE 7 (stat_cards) — derive 3 metrics from the ProcessModel "
                "(cycle time, error rate, control points, SLA, or volume counts). "
                "Each card needs stat, label, description. Use [TBC] only if truly unquantifiable.\n"
            )

        presentation_title = _resolve_presentation_title(pm, {"user_intent_original": ctx.user_intent_original})

        # ── Skill-aware slide sequence ──────────────────────────────────────
        # If the primary skill defines a slide_sequence (e.g., proposal skills
        # have a different structure than process documentation), use it.
        # This allows each domain skill to control the slide ordering via
        # SKILL.md configuration rather than hardcoded Python.

        # ── Shared slide schema (used by both skill-aware and fallback paths) ──
        _slide_schema = (
            "Each slide object schema (omit fields that are null):\n"
            "  title         string — ≤10 words (required)\n"
            "  slide_type    string — one of: title | bullets | stat_cards | column_cards |\n"
            "                         stack_layers | table | chart | section_divider (required)\n"
            "  subtitle      string | null\n"
            "  bullets       string[] | null — each ≤15 words; for slide_type=\"bullets\"\n"
            "  badges        string[] | null — short phrases for title slide pills (slide_type=\"title\" only)\n"
            "  stat_cards    [{stat: string, label: string, description: string, fill: \"dark\"|\"mid_dark\"|\"gray\"}] | null\n"
            "                — stat: short metric (e.g. \"3–5\"); label: 2–4 word title;\n"
            "                  description: 1 sentence of context (10–20 words, tells the reader *why* it matters)\n"
            "  column_cards  [{heading: string, accent: \"green\"|\"dark\"|\"gray\", body: string}] | null\n"
            "                — exactly 3 cards; body ≤40 words\n"
            "  stack_layers  [{label: string, description: string, fill: \"green\"|\"dark\"|\"mid_dark\"|\"gray\"|\"dark_green\"}] | null\n"
            "                — 3–6 rows; label ≤3 words; description ≤15 words\n"
            "  footer_note   string | null — single-line summary band at slide bottom (use sparingly)\n"
            "  table         {headers: string[], rows: string[][], x: 0.28, y: 1.0, w: 9.44, h: 4.3} | null\n"
            "  chart         {type: \"bar\"|\"line\"|\"pie\", categories: string[],\n"
            "                 series: [{name: string, values: number[]}]} | null\n\n"
            "Rules:\n"
            "  - title and slide_type are required on every slide.\n"
            "  - stat_cards must have exactly 3 items; do not fabricate numbers.\n"
            "  - column_cards must have exactly 3 items.\n"
            "  - Do not mix bullets + table on the same slide.\n"
            "  - Return ONLY valid JSON: {\"slides\": [...]}\n\n"
        )

        skill_slide_sequence = primary.get("slide_sequence") if primary else None
        if isinstance(skill_slide_sequence, list) and skill_slide_sequence:
            slide_mandate_lines = [f"{i}. {step}" for i, step in enumerate(skill_slide_sequence, 1)]
            slide_mandate = "\n".join(slide_mandate_lines)
            user_core = (
                f"Create a {n_slides_guidance} executive presentation grounded in the ProcessModel AND any excerpts "
                "below (user instruction, assembled context, prior narrative/document drafts).\n"
                "Use Deloitte visual conventions: varied slide types, not just bullets.\n"
                f"Presentation title (use exactly): \"{presentation_title}\"\n"
                + data_for_slide_2 + data_for_slide_7 + "\n"
                f"Slide ordering mandate (follow this sequence):\n{slide_mandate}\n\n"
                + _slide_schema
            )
        else:
            # Default sequence (proposal-aware when discovery is available)
            arc = str(plan_discovery.get("narrative_arc") or "").strip().lower()
            proposal_mandate = {
                "scqa": (
                    "1. Situation/Context\n2. Complication\n3. Key Question\n4. Answer/Hypothesis\n"
                    "5. Evidence & Value\n6. Delivery approach\n7. Risks & mitigations\n8. Next actions"
                ),
                "pyramid": (
                    "1. Governing thought\n2-4. Supporting arguments\n5-6. Evidence and proof\n"
                    "7. Implementation roadmap\n8. Decision ask and next actions"
                ),
                "case_led": (
                    "1. Client context\n2. Case for change\n3. Target outcomes\n4-5. Proposed approach\n"
                    "6. Proof points\n7. Commercial view\n8. Next actions"
                ),
                "compare": (
                    "1. Decision context\n2. Option criteria\n3-5. Option comparison\n6. Recommended option\n"
                    "7. Delivery implications\n8. Next actions"
                ),
            }.get(arc)
            user_core = (
                f"Create a {n_slides_guidance} executive presentation grounded in the ProcessModel AND any excerpts "
                "below (user instruction, assembled context, prior narrative/document drafts).\n"
                "Use Deloitte visual conventions: varied slide types, not just bullets.\n"
                f"Presentation title (use exactly): \"{presentation_title}\"\n"
                + data_for_slide_2 + data_for_slide_7 + "\n"
                + (
                    f"Slide ordering mandate ({arc or 'default'}):\n{proposal_mandate}\n\n"
                    if is_proposal_skill and proposal_mandate
                    else
                    "Slide ordering mandate (follow this sequence):\n"
                    f"1. slide_type=\"title\" — title=\"{presentation_title}\", subtitle=\"Process Overview\",\n"
                    "   badges=[up to 4 short capability phrases from ProcessModel context]\n"
                    "2. slide_type=\"stat_cards\" — exactly 3 cards quantifying scale/impact metrics;\n"
                    "   derive from step count, role count, or ProcessModel.metadata; fills: dark, mid_dark, gray\n"
                    "   each card MUST have a description: 1 sentence (10–20 words) explaining the metric's significance\n"
                    "3. slide_type=\"column_cards\" — exactly 3 columns representing the three core pillars\n"
                    "   of this process (e.g. Intelligence / Quality / Productivity); accent: green, dark, gray\n"
                    "4. slide_type=\"stack_layers\" — 3–6 rows showing workflow phases or architecture layers;\n"
                    "   fills rotate: green, mid_dark, dark, gray, mid, dark_green\n"
                    "5. slide_type=\"bullets\" — Process Overview: one bullet per role mandate\n"
                    "6. slide_type=\"table\" — Workflow Walkthrough: headers=[Step, Owner, Inputs → Outputs];\n"
                    "   one row per ProcessModel.steps entry\n"
                    "7. slide_type=\"stat_cards\" — 3 Key Metrics or Controls derived from the process\n"
                    "   (error rate, SLA, compliance gates, cycle time, etc.);\n"
                    "   each card must have stat, label, description; use [TBC] only if truly unquantifiable\n"
                    "   Prefer stat_cards here — use column_cards only if all 3 items are purely qualitative pillars\n"
                    "8+ (if more slides needed): slide_type=\"bullets\" or \"column_cards\" for workflow phases\n"
                    "Final slide: slide_type=\"bullets\", title=\"Recommended Next Actions\",\n"
                    "   bullets=[exactly 3 numbered actions specific to this process, each ≤15 words]\n\n"
                )
                + _slide_schema
            )
        appendix = _shared_user_context_appendix(ctx)
        if plan_discovery:
            discovery_lines = []
            client = plan_discovery.get("client") if isinstance(plan_discovery.get("client"), dict) else {}
            outcome = plan_discovery.get("outcome") if isinstance(plan_discovery.get("outcome"), dict) else {}
            themes = plan_discovery.get("win_themes") if isinstance(plan_discovery.get("win_themes"), list) else []
            if client:
                discovery_lines.append(f"Client context: {client.get('name', '')} ({client.get('industry', '')})")
            if outcome:
                discovery_lines.append(f"Desired outcome: {outcome.get('primary', '')}; decision: {outcome.get('decision', '')}")
            if themes:
                discovery_lines.append("Win themes: " + ", ".join(str(x) for x in themes[:3]))
            if discovery_lines:
                appendix = appendix + "\n\nDiscovery inputs:\n- " + "\n- ".join(discovery_lines)
        user = user_core + appendix + f"{process_model_json_block(pm)}"
        visual_feedback: list[dict] = (ctx.plan_payload or {}).get("pptx_visual_feedback") or []
        if visual_feedback and isinstance(visual_feedback, list):
            hints_text = "\n".join(
                f"- Slide {h.get('slide_index', '?')}: {h.get('instruction', '')}"
                for h in visual_feedback
                if isinstance(h, dict) and h.get("instruction")
            )
            if hints_text:
                user = (
                    user
                    + f"\n\nVisual QA feedback from previous generation (must be addressed):\n{hints_text}"
                )
        prior_slides_raw = (ctx.plan_payload or {}).get("prior_pptx_slides")
        prior_slides: list[dict[str, Any]] | None = None
        if isinstance(prior_slides_raw, list):
            prior_slides = [s for s in prior_slides_raw if isinstance(s, dict)]
        fix_indices = _pptx_visual_feedback_indices(visual_feedback) if visual_feedback and isinstance(visual_feedback, list) else set()
        repair_mode = bool(prior_slides and fix_indices)
        if repair_mode and prior_slides:
            user += (
                "\n\n## VISUAL QA REPAIR (targeted slides only)\n"
                f"Return JSON {{\"slides\": [...]}} with exactly {len(prior_slides)} slides "
                "in the same order as PRIOR_DECK below.\n"
                f"Replace ONLY slides at these 1-based indices: {sorted(fix_indices)} "
                "to satisfy the Visual QA feedback above.\n"
                "For all other positions, copy each slide from PRIOR_DECK unchanged "
                "(identical structure and content).\n\n"
                "PRIOR_DECK:\n"
                + json.dumps(prior_slides, ensure_ascii=False)
            )
        # ── Batched generation (when deck outline is available & not in repair mode) ──
        batched_slides: list[dict] | None = None
        deck_outline_raw = (ctx.plan_payload or {}).get("deck_outline_preview")
        if (
            not repair_mode
            and isinstance(deck_outline_raw, dict)
            and isinstance(deck_outline_raw.get("slides"), list)
            and len(deck_outline_raw["slides"]) >= 6
        ):
            batched_slides = _generate_slides_batched(
                ctx,
                system=sb.system,
                user_core=user_core,
                appendix=appendix,
                pm=pm,
                outline=deck_outline_raw["slides"],
                temperature=sb.temperature,
                max_rounds=sb.max_rounds,
            )

        if batched_slides:
            # region agent log
            _session_debug_log(
                run_id=ctx.run_id,
                hypothesis_id="H5",
                location="subagents.py:run_pptx_agent:batched",
                message="PPTX slides generated via batched mode",
                data={"slide_count": len(batched_slides), "used_primary_skill_id": str(primary.get("id") or "")},
            )
            # endregion
            slide_dicts = batched_slides
            json_str = json.dumps({"slides": slide_dicts}, ensure_ascii=False)
            json_str = _apply_quality_gate(ctx, "pptx", json_str, system=sb.system, temperature=sb.temperature)
            try:
                obj2 = _extract_first_json_object(json_str)
                slides2 = obj2.get("slides") if isinstance(obj2, dict) else None
                if isinstance(slides2, list) and slides2:
                    slide_dicts = [s for s in slides2 if isinstance(s, dict)] or slide_dicts
            except Exception:  # noqa: S110 — best-effort, non-fatal
                pass
            slide_dicts = _run_pptx_post_processor(ctx, slide_dicts)
            slide_dicts = _normalize_pptx_slide_identities(slide_dicts)
            return AgentOutput(updates={"pptx_slides": slide_dicts})

        # ── Single-shot generation (default path) ──
        raw_json = _run_subagent_tool_loop_text(ctx, agent_id="pptx", system=sb.system, user=user, temperature=sb.temperature, max_rounds=sb.max_rounds)
        obj: dict | None = None
        if raw_json:
            try:
                obj = _extract_first_json_object(raw_json)
            except Exception:
                obj = None
        if not obj:
            try:
                obj = claude_generate_json(system=sb.system, user=user, temperature=sb.temperature, max_tokens=8192)
            except Exception:
                obj = None
        slides = obj.get("slides") if isinstance(obj, dict) else None
        if isinstance(slides, list) and slides:
            slide_dicts = [s for s in slides if isinstance(s, dict)]
            if slide_dicts:
                if repair_mode and prior_slides:
                    slide_dicts = _merge_pptx_slides_repair(prior_slides, slide_dicts, fix_indices)
                json_str = json.dumps({"slides": slide_dicts}, ensure_ascii=False)
                json_str = _apply_quality_gate(ctx, "pptx", json_str, system=sb.system, temperature=sb.temperature)
                try:
                    obj2 = _extract_first_json_object(json_str)
                    slides2 = obj2.get("slides") if isinstance(obj2, dict) else None
                    if isinstance(slides2, list) and slides2:
                        slide_dicts = [s for s in slides2 if isinstance(s, dict)] or slide_dicts
                except Exception:  # noqa: S110 — best-effort, non-fatal
                    pass
                slide_dicts = _run_pptx_post_processor(ctx, slide_dicts)
                slide_dicts = _normalize_pptx_slide_identities(slide_dicts)
                # region agent log
                _session_debug_log(
                    run_id=ctx.run_id,
                    hypothesis_id="H5",
                    location="subagents.py:run_pptx_agent:generated",
                    message="PPTX slides generated via tool loop / model",
                    data={
                        "slide_count": len(slide_dicts),
                        "repair_mode": bool(repair_mode),
                        "used_primary_skill_id": str(primary.get("id") or ""),
                    },
                )
                # endregion
                return AgentOutput(updates={"pptx_slides": slide_dicts})

    fallback_slides = _normalize_pptx_slide_identities(_pptx_deterministic_slides(pm))
    # region agent log
    _session_debug_log(
        run_id=ctx.run_id,
        hypothesis_id="H5",
        location="subagents.py:run_pptx_agent:fallback",
        message="PPTX slides generated via deterministic fallback",
        data={
            "slide_count": len(fallback_slides),
            "used_primary_skill_id": str(primary.get("id") or ""),
        },
    )
    # endregion
    return AgentOutput(updates={"pptx_slides": fallback_slides})
