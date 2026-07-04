"""LLM planning/routing methods mixed into Coordinator (see app.agents.coordinator)."""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.agents.coordinator_state_manager import CoordinatorStateManager

from app.agents.prompt_hygiene import UNTRUSTED_JSON_USER_NOTE, wrap_untrusted
from app.agents.subagents import (
    run_docx_agent,
    run_drawio_agent,
    run_narrative_agent,
    run_pdf_agent,
    run_pptx_agent,
    run_sop_agent,
    run_xlsx_agent,
)
from app.core.config import settings
from app.core.state import ProcessDocState
from app.schemas.llm_contracts import CoordinatorPlanResponse
from app.services.claude import (
    _extract_first_json_object,
)
from app.services.proposal_policy import derive_proposal_skill_targets

_OUTPUT_AGENTS: dict[str, object] = {
    "process_map": run_drawio_agent,
    "docx":        run_docx_agent,
    "pptx":        run_pptx_agent,
    "xlsx":        run_xlsx_agent,
    "pdf":         run_pdf_agent,
    "sop":         run_sop_agent,
    "narrative":   run_narrative_agent,
}

# Rough complexity weights (1=fast, 5=slow) for ordering metadata emitted in coordinator_plan events.
# Does not change execution order (which is LLM-driven); used as a scheduling hint.
_OUTPUT_TYPE_COMPLEXITY: dict[str, int] = {
    "pptx": 5, "xlsx": 4, "docx": 3, "pdf": 3,
    "narrative": 2, "sop": 2, "process_map": 1,
}

_OUTPUT_TYPE_REQUIREMENTS_PATH = Path(__file__).resolve().parents[2] / "config" / "output_types.json"
_JSON_PATH_CACHE: dict[str, tuple[int, object]] = {}

_EVENT_COORDINATOR_PLAN = "coordinator_plan"
_MAX_EVENT_TEXT = 4000
_DEBUG_LOG_PATH = Path(settings.processdoc_coordinator_debug_log).expanduser() if str(settings.processdoc_coordinator_debug_log or "").strip() else None
_DEBUG_SESSION_ID = "a9841a"
_LOG = logging.getLogger(__name__)

def _session_debug_log(*, run_id: str | None, hypothesis_id: str, location: str, message: str, data: dict[str, Any]) -> None:
    if _DEBUG_LOG_PATH is None:
        return
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
    except Exception as exc:
        _LOG.debug("coordinator session debug log write failed: %s", exc)


@dataclass
class ExecutionPlan:
    """LLM or fallback ordering for output agents; merged against user-requested ceiling."""

    ordered_output_types: list[str]
    rationale: str
    per_output_notes: dict[str, str] = field(default_factory=dict)
    used_llm_plan: bool = False
    fallback_reason: str | None = None
    thinking_excerpt: str = ""
    execution_milestones: list[dict[str, Any]] = field(default_factory=list)


def _milestone_labels_from_plan(plan: ExecutionPlan, wanted: list[str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    want = {str(x).strip() for x in wanted if str(x).strip()}
    for m in plan.execution_milestones:
        if not isinstance(m, dict):
            continue
        ot = str(m.get("output_type") or "").strip()
        label = str(m.get("label") or "").strip()
        if ot in want and label:
            labels[f"out:{ot}"] = label
    return labels


def _load_json_path_cached(path: Path) -> object:
    cache_key = str(path)
    stat = path.stat()
    cached = _JSON_PATH_CACHE.get(cache_key)
    if cached and cached[0] == stat.st_mtime_ns:
        return cached[1]
    raw = path.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    _JSON_PATH_CACHE[cache_key] = (stat.st_mtime_ns, parsed)
    return parsed


def _debug_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    raw = (settings.processdoc_coordinator_debug_log or "").strip()
    if not raw:
        return
    path = Path(raw)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "sessionId": "5b96f3",
            "runId": "skill-selection-check",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception as exc:
        _LOG.debug("coordinator debug log write failed: %s", exc)


# Deliverable types that map to a format type + content skill hint.
# When a user requests "sop", they mean a docx document driven by sop_v2 content skill.
_DELIVERABLE_TO_FORMAT: dict[str, tuple[str, str]] = {
    "sop": ("docx", "sop_v2"),
    "raci": ("xlsx", "raci_v2"),
    "narrative": ("docx", "narrative_v2"),
    "report": ("pdf", "narrative_v2"),
    "approach_note": ("docx", "approach_note_v1"),
    "brd": ("docx", "brd_v1"),
    "proposal": ("docx", "proposal_finance_transformation_v1"),
    "deck": ("pptx", "narrative_v2"),
    "executive_deck": ("pptx", "narrative_v2"),
    "brd_deck": ("pptx", "brd_v1"),
    "proposal_deck": ("pptx", "proposal_finance_transformation_v1"),
}

# Format-type aliases (file format synonyms only — no deliverable types)
_FORMAT_ALIASES: dict[str, str] = {
    "process_map": "process_map",
    "drawio": "process_map",
    "diagram": "process_map",
    "map": "process_map",
    "docx": "docx",
    "word": "docx",
    "pptx": "pptx",
    "ppt": "pptx",
    "presentation": "pptx",
    "slides": "pptx",
    "xlsx": "xlsx",
    "excel": "xlsx",
    "spreadsheet": "xlsx",
    "pdf": "pdf",
}


def _canonical_requested(raw: list[str] | None) -> tuple[list[str], dict[str, str]]:
    """
    Canonicalise requested output types to format types only.

    Returns:
        (output_types, content_skill_hints)
        where content_skill_hints[format_type] = skill_id to use as primary content skill.

    Deliverable aliases (sop, raci, narrative) are mapped to their format type
    and generate a content skill hint that the coordinator injects as the primary
    skill for that output's generation. The skill drives what content structure
    the format agent produces (SOP sections, RACI table, executive briefing, etc.).
    """
    out: list[str] = []
    hints: dict[str, str] = {}
    for x in raw or []:
        token = (x or "").strip().lower()
        if token in _DELIVERABLE_TO_FORMAT:
            fmt, skill_hint = _DELIVERABLE_TO_FORMAT[token]
            if fmt not in out:
                out.append(fmt)
            hints.setdefault(fmt, skill_hint)  # first hint wins per format type
        elif token in _FORMAT_ALIASES:
            key = _FORMAT_ALIASES[token]
            if key not in out:
                out.append(key)
        elif token:
            if token not in out:
                out.append(token)
    if out:
        return out, hints
    # No implicit default output types; caller must provide explicit selection.
    return [], hints


def _merge_intent_hints(
    *,
    wanted: list[str],
    existing_hints: dict[str, str],
    instruction: str,
) -> dict[str, str]:
    """
    Add content-skill hints when callers requested only format types (docx/pptx/pdf)
    but user intent clearly implies a deliverable-specific skill.
    """
    hints = dict(existing_hints or {})
    text = (instruction or "").strip().lower()
    if not text:
        return hints

    # Generic alias recovery: infer deliverable aliases from instruction text.
    for token, (fmt, skill_hint) in _DELIVERABLE_TO_FORMAT.items():
        if fmt not in wanted or fmt in hints:
            continue
        aliases = {token, token.replace("_", " ")}
        if any(a and a in text for a in aliases):
            hints[fmt] = skill_hint

    proposal_targets = derive_proposal_skill_targets(
        instruction=text,
        output_types=wanted,
        base_targets=hints,
    )
    hints.update(proposal_targets)

    return hints


def _sanitize_content_skill_targets(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        ks = str(k or "").strip()
        vs = str(v or "").strip()
        if ks and vs:
            out[ks] = vs
    return out


def _skill_public_dict(card: dict | None) -> dict:
    if not isinstance(card, dict):
        return {}
    return {k: v for k, v in card.items() if not str(k).startswith("_")}


def _merge_planned_output_order(planned: list[str], ceiling: list[str]) -> list[str]:
    """Preserve planner order for valid types, then append any remaining ceiling types."""
    ceiling_set = set(ceiling)
    seen: set[str] = set()
    out: list[str] = []
    for t in planned:
        if t in ceiling_set and t not in seen:
            out.append(t)
            seen.add(t)
    for t in ceiling:
        if t not in seen:
            out.append(t)
    return out


def _trim_registry_for_planning(registry: list[dict]) -> list[dict]:
    """
    Build a compact skill summary for the coordinator planning prompt.
    Includes ``use_when`` so the LLM can make intent-driven skill decisions,
    and ``role`` so it knows which skills are post-processors vs. primary generators.
    """
    out: list[dict] = []
    for card in registry:
        if not isinstance(card, dict):
            continue
        entry: dict = {
            "id": str(card.get("id") or "").strip(),
            "output_types": list(card.get("output_types") or []),
            "display_name": str(card.get("display_name") or card.get("title") or card.get("name") or "")[:80],
            "role": str(card.get("role") or "primary").strip().lower(),
        }
        use_when = str(card.get("use_when") or card.get("description") or "").strip()
        if use_when:
            entry["use_when"] = use_when[:200]
        out.append(entry)
    return out


def _process_model_summary(state: ProcessDocState) -> str:
    pm = state.get("process_model")
    if not isinstance(pm, dict):
        return "{}"
    raw = json.dumps(pm, ensure_ascii=True)
    if len(raw) > 12000:
        return raw[:12000] + "\n…"
    return raw


def _truncate_event_text(text: str, limit: int = _MAX_EVENT_TEXT) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 1] + "…"



from app.agents import coordinator as _coordinator_module


class CoordinatorPlanning:
    """Mixed into Coordinator; see app.agents.coordinator for shared state/__init__."""

    @staticmethod
    def _emit_coordinator_plan(
        emit_event: Callable[[str, dict[str, Any]], None] | None,
        plan: ExecutionPlan,
        *,
        wanted: list[str],
        contract_nodes: list[dict],
    ) -> None:
        if not emit_event:
            return
        payload: dict[str, Any] = {
            "rationale": _truncate_event_text(plan.rationale, 2000),
            "used_llm_plan": plan.used_llm_plan,
            "planned_outputs": list(wanted),
            "fallback_reason": plan.fallback_reason,
            "per_output_notes": plan.per_output_notes or {},
            "run_contract_present": bool(contract_nodes),
        }
        if plan.thinking_excerpt:
            payload["thinking_excerpt"] = _truncate_event_text(plan.thinking_excerpt, 1500)
        emit_event(_EVENT_COORDINATOR_PLAN, payload)

    def _plan_with_reasoning(
        self,
        state: ProcessDocState,
        *,
        ceiling_types: list[str],
        effective_registry: list[dict],
        emit_event: Callable[[str, dict[str, Any]], None] | None,
        contract_nodes: list[dict],
    ) -> tuple[list[str], ExecutionPlan]:
        ceiling = list(ceiling_types)
        if not ceiling:
            plan = ExecutionPlan(
                ordered_output_types=[],
                rationale="",
                used_llm_plan=False,
                fallback_reason="empty_request",
            )
            self._emit_coordinator_plan(emit_event, plan, wanted=[], contract_nodes=contract_nodes)
            return [], plan

        if not _coordinator_module.settings.coordinator_llm_planning_enabled:
            plan = ExecutionPlan(
                ordered_output_types=list(ceiling),
                rationale="",
                used_llm_plan=False,
                fallback_reason="coordinator_llm_planning_disabled",
            )
            self._emit_coordinator_plan(emit_event, plan, wanted=ceiling, contract_nodes=contract_nodes)
            return ceiling, plan

        if not _coordinator_module.is_claude_enabled():
            plan = ExecutionPlan(
                ordered_output_types=list(ceiling),
                rationale="",
                used_llm_plan=False,
                fallback_reason="claude_disabled",
            )
            self._emit_coordinator_plan(emit_event, plan, wanted=ceiling, contract_nodes=contract_nodes)
            return ceiling, plan

        # When a run_contract exists, worker execution order follows contract nodes; planning still informs rationale.
        system = (
            "You are a helpful digital teammate and consulting expert for ProcessDoc Studio. "
            "Sound like a trusted colleague: warm, clear, and collaborative. "
            "Ground recommendations in the user's goal—explain briefly why the execution order "
            "reduces rework and serves their outcome (no generic filler).\n"
            "Given the user instruction, extracted process model, skill registry summary, "
            "and the list of allowed output types for this run, produce a JSON object ONLY (no markdown) "
            'with keys: "rationale" (short string), "ordered_output_types" (array of strings), '
            '"per_output_notes" (optional object mapping output type id to a short note), '
            '"execution_milestones" (optional array of {"output_type": string, "label": string}, max 12). '
            "Voice for user-visible fields: rationale reads like a concise note from a teammate; "
            "execution_milestones labels are short, action-oriented, and user-friendly; "
            "per_output_notes flag skill/intent mismatches or dependencies in plain language.\n"
            "Rules:\n"
            "- Every element of ordered_output_types must appear in allowed_output_types.\n"
            "- Include every allowed type exactly once in an order that minimises rework "
            "(e.g. narrative before dependent artifacts when helpful).\n"
            "- Consult each skill's 'use_when' field to confirm the skill is appropriate for "
            "the user's stated intent. If a skill's use_when does not match the instruction, "
            "note this in per_output_notes.\n"
            "- Skills with role='post_processor' run after their associated primary skill; "
            "do not reorder them ahead of their primary.\n"
            "- Do not add types outside allowed_output_types.\n"
            '- For execution_milestones, only use output_type values from allowed_output_types; '
            "labels are shown in the run checklist (optional).\n"
            "- Optional fields conversation_digest and grounding_excerpt summarize prior HITL chat "
            "and retrieval-aligned source snippets; use them to align ordering and notes with user intent.\n"
            + UNTRUSTED_JSON_USER_NOTE
        )
        conv_digest = str(state.get("conversation_digest") or "")
        ground_ex = str(state.get("planner_retrieval_excerpt") or "")
        user_payload = {
            "user_instruction": wrap_untrusted(
                "user_instruction",
                str(state.get("user_instruction") or state.get("raw_text") or ""),
                max_chars=8000,
            ),
            "process_model_json": wrap_untrusted(
                "process_model_summary",
                _process_model_summary(state),
                max_chars=12000,
            ),
            "allowed_output_types": ceiling,
            "skill_registry": _trim_registry_for_planning(effective_registry),
            "run_contract_present": bool(contract_nodes),
            "conversation_digest": wrap_untrusted(
                "conversation_digest",
                conv_digest,
                max_chars=_coordinator_module.settings.conversation_digest_planner_max_chars,
            ),
            "grounding_excerpt": wrap_untrusted(
                "grounding_excerpt",
                ground_ex,
                max_chars=_coordinator_module.settings.coordinator_planning_context_chars,
            ),
        }
        user = json.dumps(user_payload, ensure_ascii=True)

        try:
            result = _coordinator_module.claude_generate_with_thinking(
                system=system,
                user=user,
                max_tokens=_coordinator_module.settings.anthropic_coordinator_plan_max_tokens,
                budget_tokens=_coordinator_module.settings.anthropic_thinking_budget_tokens,
            )
        except Exception as exc:
            plan = ExecutionPlan(
                ordered_output_types=list(ceiling),
                rationale="",
                used_llm_plan=False,
                fallback_reason=f"api_error:{exc.__class__.__name__}",
            )
            self._emit_coordinator_plan(emit_event, plan, wanted=ceiling, contract_nodes=contract_nodes)
            return ceiling, plan

        thinking_text = str(result.get("thinking_text") or "")
        assistant_text = str(result.get("text") or "")
        try:
            parsed = _extract_first_json_object(assistant_text)
        except Exception:
            plan = ExecutionPlan(
                ordered_output_types=list(ceiling),
                rationale="",
                used_llm_plan=False,
                fallback_reason="invalid_json",
                thinking_excerpt=_truncate_event_text(thinking_text, 1500),
            )
            self._emit_coordinator_plan(emit_event, plan, wanted=ceiling, contract_nodes=contract_nodes)
            return ceiling, plan

        if not isinstance(parsed, dict):
            plan = ExecutionPlan(
                ordered_output_types=list(ceiling),
                rationale="",
                used_llm_plan=False,
                fallback_reason="invalid_payload_type",
                thinking_excerpt=_truncate_event_text(thinking_text, 1500),
            )
            self._emit_coordinator_plan(emit_event, plan, wanted=ceiling, contract_nodes=contract_nodes)
            return ceiling, plan

        try:
            validated = CoordinatorPlanResponse.model_validate(parsed)
        except Exception:
            plan = ExecutionPlan(
                ordered_output_types=list(ceiling),
                rationale="",
                used_llm_plan=False,
                fallback_reason="invalid_plan_contract",
                thinking_excerpt=_truncate_event_text(thinking_text, 1500),
            )
            self._emit_coordinator_plan(emit_event, plan, wanted=ceiling, contract_nodes=contract_nodes)
            return ceiling, plan

        planned = [str(x).strip() for x in validated.ordered_output_types if str(x).strip()]
        rationale = str(validated.rationale or "").strip()
        notes: dict[str, str] = {
            str(k).strip(): str(v)[:500]
            for k, v in (validated.per_output_notes or {}).items()
            if str(k).strip()
        }
        exec_ms: list[dict[str, Any]] = [
            {"output_type": str(item.output_type).strip(), "label": str(item.label).strip()[:300]}
            for item in validated.execution_milestones[:12]
            if str(item.output_type).strip() and str(item.label).strip()
        ]

        wanted = _merge_planned_output_order(planned, ceiling)
        plan = ExecutionPlan(
            ordered_output_types=wanted,
            rationale=rationale,
            per_output_notes=notes,
            used_llm_plan=True,
            thinking_excerpt=_truncate_event_text(thinking_text, 1500),
            execution_milestones=exec_ms,
        )
        self._emit_coordinator_plan(emit_event, plan, wanted=wanted, contract_nodes=contract_nodes)
        return wanted, plan

    # ============================================================================
    # Agentic Loop (Phase 0 Refactor)
    # ============================================================================

    def _lead_replan(
        self,
        state: ProcessDocState,
        sm: "CoordinatorStateManager",
        failed_task_id: str,
        error: str,
        *,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        """
        Lead agent replans strategy after task failure.

        For Phase 0, simple strategy: mark task as queued for retry with adjusted parameters.
        Future: Call Claude to generate alternative plan.
        """
        _LOG.info(f"Replanning after task failure: {failed_task_id} - {error}")

        if failed_task_id not in sm.task_board:
            _LOG.warning(f"Replan requested for unknown task: {failed_task_id}")
            return

        task = sm.task_board[failed_task_id]
        attempts = int(task.get("attempts") or 0)

        if attempts < 2:
            # Retry: reset to queued for another attempt.
            action = "retry"
            task["status"] = "queued"
            task["error"] = error
            task["assigned_teammate"] = None
        elif task.get("phase") == "generation":
            # Generation tasks are skippable — degrade gracefully rather than blocking the run.
            action = "skip"
            task["status"] = "skipped"
            task["error"] = f"Skipped after {attempts} attempts: {error}"
            if emit_event:
                emit_event("coordinator_skip_event", {
                    "task_id": failed_task_id,
                    "output_type": task.get("output_type"),
                    "reason": f"Exceeded retry budget ({attempts} attempts): {error[:200]}",
                    "phase": task.get("phase"),
                })
        else:
            # Setup or finalization tasks cannot be skipped; keep as failed so
            # CoordinatorStateManager.replanning_count will eventually exceed max_replans.
            action = "escalate"

        if emit_event:
            emit_event("coordinator_replan_event", {
                "failed_task": failed_task_id,
                "error": error,
                "action": action,
                "attempts": attempts,
                "replan_count": sm.replanning_count,
            })
        _LOG.info("Replan for %s: action=%s attempts=%d", failed_task_id, action, attempts)

