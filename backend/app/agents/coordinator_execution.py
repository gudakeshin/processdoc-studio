"""Run dispatch/execution-loop methods mixed into Coordinator (see app.agents.coordinator)."""

import json
import logging
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

if TYPE_CHECKING:
    from app.agents.coordinator_state_manager import CoordinatorStateManager

from app.agents.coordinator_teammate_integration import CoordinatorTeammateIntegration
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
from app.core.run_control import abort_scope as _coordinator_abort_scope
from app.core.run_control import poll_abort as _coordinator_poll_abort
from app.core.state import ProcessDocState
from app.db.models import MemoryEvent, MemoryItem, ProjectMemoryProfile, UserProjectPreference
from app.services.langfuse_tracing import langfuse_span
from app.services.memory_context import merge_long_term_items_into_profile
from app.services.observability import increment
from app.services.proposal_policy import derive_proposal_skill_targets
from app.services.run_events import build_event_payload
from app.services.run_todo_snapshot import (
    build_run_todo_rows,
    emit_run_todo_snapshot,
    todo_bulk_set,
    todo_set_status,
)

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


class CoordinatorExecution:
    """Mixed into Coordinator; see app.agents.coordinator for shared state/__init__."""

    def _execute_single_task(
        self,
        task_id: str,
        state: ProcessDocState,
        output_type: str | None = None,
        max_retries: int = 1,
    ) -> tuple[dict[str, Any], str | None]:
        """
        Execute a single task and return (output_patch, error_message).

        For output tasks (out:*), dispatches to the corresponding agent.
        For other tasks, returns success without execution.
        """
        if not output_type:
            # Not an output task, just mark as done
            return {}, None

        if output_type not in _coordinator_module._OUTPUT_AGENTS:
            # No agent for this output type, skip
            return {}, None

        worker = _coordinator_module._OUTPUT_AGENTS[output_type]

        try:
            # Execute worker with retry
            update, err = self._execute_worker_with_retry(
                worker,
                state,
                max_retries=max_retries,
                output_type=output_type,
            )
            if err:
                return {}, err
            return update, None
        except Exception as e:
            return {}, str(e)

    def _poll_and_execute_tasks(
        self,
        state: ProcessDocState,
        sm: "CoordinatorStateManager",
        *,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
        abort_check: Callable[[], bool] | None = None,
    ) -> tuple[dict[str, Any], list[tuple[str, str]]]:
        """
        Poll for task completion and execute any ready tasks.

        Returns:
            Tuple of (state_updates, failed_tasks_list)
        """
        _coordinator_poll_abort()

        failed_tasks = []
        all_updates = {}

        # Execute any assigned tasks that are in "running" state
        for task_id, task_info in sm.task_board.items():
            if task_info["status"] != "running":
                continue

            output_type = task_info.get("output_type")

            # Execute the task
            update, err = self._execute_single_task(
                task_id,
                state,
                output_type=output_type,
                max_retries=1,
            )

            if err:
                sm.mark_task_failed(task_id, error=err)
                failed_tasks.append((task_id, err))
                _LOG.error(f"Task {task_id} failed: {err}")
                # Emit updated todo snapshot after task failure
                if emit_event:
                    emit_run_todo_snapshot(emit_event, sm.as_todo_snapshot())
            else:
                sm.mark_task_done(task_id, emit_event=emit_event)
                all_updates.update(update)
                _LOG.info(f"Task {task_id} completed")
                # Emit updated todo snapshot after task completion
                if emit_event:
                    emit_run_todo_snapshot(emit_event, sm.as_todo_snapshot())

            if emit_event:
                emit_event("task_execution_result", {
                    "task_id": task_id,
                    "status": "failed" if err else "completed",
                    "error": err,
                })

        return all_updates, failed_tasks

    def _run_finalization_phase(
        self,
        state: ProcessDocState,
        sm: "CoordinatorStateManager",
        wanted: list[str],
        *,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
        abort_check: Callable[[], bool] | None = None,
    ) -> ProcessDocState:
        """
        Execute finalization phase: QA loop, guardrails, hooks.

        Extracted from the original run() method (lines 1323-1389) to enable
        integration into the agentic loop.
        """
        _coordinator_poll_abort()

        project_id = state.get("project_id")
        run_id = str(state.get("run_id") or "")

        # Extract outputs from state
        outputs = self._outputs_from_state(state, wanted)

        # Unified framework is now the authoritative quality gate.
        unified_reports, outputs = self._run_unified_quality_framework(state, outputs, wanted, emit_event=emit_event)
        state["deliverable_quality_report"] = None
        state["unified_quality_reports"] = unified_reports

        # QA loop
        qa_threshold = float(state.get("qa_threshold", 0.8))
        max_qa_loops = max(1, min(5, int(state.get("max_qa_loops", 2) or 2)))

        _coordinator_poll_abort()
        qa_report = self.qa_loop.run(
            outputs,
            threshold=qa_threshold,
            project_id=state.get("project_id"),
            max_loops=max_qa_loops,
        )

        if not qa_report.get("passed", False):
            remediation = qa_report.get("remediation_instructions", {})
            if isinstance(remediation, dict) and remediation:
                _coordinator_poll_abort()
                pre_scores = qa_report.get("scores", {})
                outputs = self._apply_qa_remediation(state, wanted, remediation)
                post_qa = self.qa_loop.run(
                    outputs,
                    threshold=qa_threshold,
                    project_id=state.get("project_id"),
                    max_loops=max_qa_loops,
                )
                post_qa["pre_remediation_scores"] = pre_scores
                post_qa["remediation_applied"] = True
                post_qa["remediation_converged"] = bool(post_qa.get("passed", False))
                qa_report = post_qa

        # Guardrails evaluation
        _coordinator_poll_abort()
        guardrail_report = self.guardrails.evaluate(outputs, dpdp_gate7=True)

        state["qa_report"] = qa_report
        state["guardrail_report"] = guardrail_report

        # Post-generation hooks
        if emit_event:
            hook_results = _coordinator_module.run_hooks_sync(
                "post_output_generation",
                {"state": state, "project_id": project_id, "run_id": run_id},
                project_id=str(project_id) if project_id else None,
            )
            for h in hook_results:
                emit_event(
                    "hook_result",
                    {
                        "hook_point": "post_output_generation",
                        "hook_name": h.hook_name,
                        "outcome": h.outcome,
                        "message": h.message,
                    },
                )
                if h.outcome == "ABORT":
                    raise RuntimeError(f"hook_abort:{h.hook_name}:{h.message}")

            emit_event("fanout_complete", {"stages": ["context_assembly", "skill_selection", "plan_validation"]})

        return state

    def _run_setup_phase(
        self,
        state: ProcessDocState,
        sm: "CoordinatorStateManager",
        *,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
        abort_check: Callable[[], bool] | None = None,
    ) -> tuple["CoordinatorStateManager", dict[str, Any]]:
        """
        Execute setup phase: context assembly, planning, skill selection.

        Extracted from the original run() method (lines 789-1187) to enable
        integration into the agentic loop.

        Returns:
            Tuple of (updated state_manager, state_dict)
        """
        from app.agents.coordinator_state_manager import ExecutionPlanSnapshot

        _coordinator_poll_abort()

        # Parallel fanout stage (context, skills, plan validation)
        if emit_event:
            emit_event("fanout_start", {"stages": ["context_assembly", "skill_selection", "plan_validation"]})
            fanout = self._parallel_read_stages(state)
            if fanout.get("errors"):
                increment("fanout_failures_total")
                emit_event("fanout_failed", {"errors": fanout.get("errors")})
                raise RuntimeError("parallel_read_stage_failure")
            state["parallel_stage_contract"] = fanout
            emit_event("fanout_stage_results", fanout)

        _coordinator_poll_abort()

        # DPDP redaction
        raw = state.get("raw_text", "")
        redacted, dpdp_report = self.dpdp.redact(raw)
        state["dpdp_report_json"] = dpdp_report

        # Leading practices
        lp_snippets: list[str] = []
        project_id = state.get("project_id")
        if project_id:
            try:
                from app.services.leading_practices import leading_practice_library_service

                dpdp_enabled = bool(state.get("dpdp_flags", {}).get("enabled", True))
                lp_results = leading_practice_library_service.search(
                    redacted,
                    project_id=project_id,
                    dpdp_enabled=dpdp_enabled,
                )
                # Additional per-output-type LP searches for PPTX and DOCX.
                _lp_seen_ids: set[str] = {str(r.get("id")) for r in lp_results if r.get("id")}
                _output_labels = {"pptx": "Executive presentation", "docx": "Detailed process document"}
                for _otype, _label in _output_labels.items():
                    if _otype in (state.get("requested_outputs") or []):
                        try:
                            _extra = leading_practice_library_service.search(
                                f"{redacted}\n[OUTPUT: {_label}]",
                                project_id=project_id,
                                dpdp_enabled=dpdp_enabled,
                            )
                            for _r in _extra:
                                _rid = str(_r.get("id") or "")
                                if _rid and _rid not in _lp_seen_ids:
                                    lp_results.append(_r)
                                    _lp_seen_ids.add(_rid)
                        except Exception as exc:
                            _LOG.warning(
                                "LP extra search failed for output=%s: %s",
                                _otype,
                                exc,
                            )
                lp_results = lp_results[:50]
                for r in lp_results:
                    text = r.get("text")
                    heading = r.get("heading") or ""
                    if isinstance(text, str) and text.strip():
                        prefix = f"[LP]{heading}".strip() if heading else "[LP]"
                        lp_snippets.append(f"{prefix}\n{text}")
            except Exception:
                lp_snippets = []

        # Intent-triggered pre-search: if the user's instruction signals a search
        # request, run wiki + web searches before context assembly so results land
        # in assembled_context for ALL subagents (not just the one that calls the tool).
        # Gated by _coordinator_module.settings.coordinator_pre_search_enabled (overall) and
        # coordinator_pre_search_web_enabled (web leg only) so operators can cap
        # outbound-network cost without disabling the wiki side.
        _SEARCH_INTENT_RE = re.compile(
            r"\b(search|look up|lookup|look for|find|research|browse|check|fetch|"
            r"retrieve|pull|are there any|what does .{0,40} say|examples of|"
            r"instances of|references to|tell me about)\b",
            re.IGNORECASE,
        )
        if (
            project_id
            and _coordinator_module.settings.coordinator_pre_search_enabled
            and _SEARCH_INTENT_RE.search(redacted)
        ):
            _pre_wiki: list[dict] = []
            _pre_web: list[dict] = []
            try:
                from app.services.wiki_operations import search_wiki as _search_wiki_fn

                _pre_wiki = _search_wiki_fn(redacted[:600], project_id=project_id, max_results=6)
                for _w in _pre_wiki:
                    _title = _w.get("title") or "Wiki"
                    _body = str(_w.get("snippet") or "").strip()
                    if _body:
                        lp_snippets.append(f"[Wiki-Search: {_title}]\n{_body}")
            except Exception as exc:
                _LOG.warning("pre-run wiki search failed for project=%s: %s", project_id, exc)
            if _coordinator_module.settings.coordinator_pre_search_web_enabled:
                try:
                    from app.services.web_search import web_search_service as _wss

                    _pre_web = _wss.search(redacted[:300], project_id=project_id)
                    for _r in _pre_web:
                        _title = _r.get("title") or "Web"
                        _url = _r.get("url") or ""
                        _snip = str(_r.get("snippet") or "").strip()
                        if _snip:
                            lp_snippets.append(f"[Web: {_title}]\n{_url}\n{_snip}")
                except Exception as exc:
                    _LOG.warning("pre-run web search failed for project=%s: %s", project_id, exc)
            if emit_event and (_pre_wiki or _pre_web):
                emit_event("pre_run_search_triggered", {
                    "wiki_results": len(_pre_wiki),
                    "web_results": len(_pre_web),
                })
            existing_web = state.get("web_search_results") or []
            state["web_search_results"] = existing_web + _pre_web

        # Memory context (events + profile)
        memory_events: list[dict[str, object]] = []
        profile_payload: dict[str, object] = {}
        if project_id:
            session = _coordinator_module.SessionLocal()
            try:
                run_id = state.get("run_id")
                rows = session.scalars(
                    select(MemoryEvent)
                    .where(MemoryEvent.project_id == project_id)
                    .order_by(MemoryEvent.id.desc())
                    .limit(500)
                ).all()
                for row in reversed(rows):
                    try:
                        payload = json.loads(row.payload)
                    except Exception:
                        payload = {"summary": row.payload}
                    memory_events.append({"event_type": row.event_type, "payload": payload})
                if run_id:
                    memory_events = memory_events[-250:]
                profile = session.scalar(
                    select(ProjectMemoryProfile).where(ProjectMemoryProfile.project_id == project_id)
                )
                if profile and profile.summary_json:
                    try:
                        parsed = json.loads(profile.summary_json)
                        if isinstance(parsed, dict):
                            profile_payload = parsed
                    except Exception:
                        profile_payload = {}
                memory_v2_enabled = _coordinator_module.settings.memory_v2_retrieval_enabled
                if memory_v2_enabled:
                    long_term_rows = session.scalars(
                        select(MemoryItem)
                        .where(MemoryItem.project_id == project_id, MemoryItem.is_archived.is_(False))
                        .order_by(MemoryItem.updated_at.desc())
                        .limit(40)
                    ).all()
                    inj, consent_skipped, ledger_skipped = merge_long_term_items_into_profile(
                        profile_payload,
                        list(long_term_rows),
                        respect_consent=_coordinator_module.settings.memory_respect_consent_in_context,
                        session=session,
                        project_id=project_id,
                        enforce_consent_ledger=_coordinator_module.settings.memory_enforce_consent_ledger,
                    )
                    if consent_skipped:
                        increment("memory_items_consent_skipped_total", consent_skipped)
                    if ledger_skipped:
                        increment("memory_items_ledger_blocked_total", ledger_skipped)
                    if inj:
                        increment("memory_items_injected_into_context_total", inj)
                uid = state.get("user_id")
                if uid and isinstance(uid, str) and uid.strip():
                    up = session.scalar(
                        select(UserProjectPreference).where(
                            UserProjectPreference.user_id == uid.strip(),
                            UserProjectPreference.project_id == project_id,
                        )
                    )
                    if up and up.preferences_json:
                        try:
                            pj = json.loads(up.preferences_json)
                            if isinstance(pj, dict):
                                lines = pj.get("context_lines")
                                if isinstance(lines, list):
                                    clean = [str(x).strip() for x in lines if str(x).strip()]
                                    if clean:
                                        profile_payload.setdefault("user_preference_lines", clean)
                        except Exception:  # noqa: S110 — best-effort, non-fatal
                            pass
            finally:
                session.close()

        # Context assembly
        use_v2 = _coordinator_module.settings.memory_compaction_v1_enabled
        if use_v2:
            increment("coordinator_context_assemble_v2_total")
            context = self.context_engine.assemble_v2(
                project_id,
                redacted,
                run_memory_events=memory_events,
                project_profile=profile_payload,
                lp_snippets=lp_snippets,
                char_cap=_coordinator_module.settings.memory_compaction_char_cap,
            )
            state["compaction_snapshot"] = context.metadata or {}
            state["memory_summary"] = {
                "non_negotiables": profile_payload.get("non_negotiables", []),
                "recent_changes": [e.get("payload") for e in memory_events[-5:]],
            }
        else:
            context = self.context_engine.assemble(
                project_id,
                redacted,
                lp_snippets=lp_snippets,
            )

        state["assembled_context"] = context.text

        if emit_event and context.metadata:
            provenance = context.metadata.get("context_provenance")
            if provenance:
                emit_event("context_provenance_summary", provenance)
            dropped = context.metadata.get("tier4_dropped_sources")
            if dropped:
                emit_event("context_compaction_warning", dropped)

        _coordinator_poll_abort()

        # Process extraction
        self._ensure_deliverable_archetype(state)
        state = _coordinator_module.run_process_extraction(state)
        _coordinator_poll_abort()

        # Planner retrieval excerpt
        planner_query = (
            f"{str(state.get('user_instruction') or state.get('raw_text') or '')[:4000]}\n"
            f"{_process_model_summary(state)[:2000]}"
        )
        excerpt = self.context_engine.planner_excerpt(
            project_id,
            planner_query,
            char_cap=max(800, _coordinator_module.settings.coordinator_planning_context_chars),
        )
        state["planner_retrieval_excerpt"] = excerpt
        if excerpt:
            increment("planner_excerpt_chars_total", len(excerpt))

        # Content skill hints and targets
        effective_registry = [*self.skill_registry, *self._load_project_custom_skills(project_id)]
        plan_payload = state.get("plan_payload")
        ceiling, content_skill_hints = _canonical_requested(state.get("requested_outputs"))
        plan_targets: dict[str, str] = {}
        if isinstance(plan_payload, dict):
            plan_targets = _sanitize_content_skill_targets(plan_payload.get("content_skill_targets"))
            if isinstance(plan_payload.get("discovery"), dict):
                state["proposal_discovery"] = dict(plan_payload.get("discovery") or {})
            regen = str(plan_payload.get("regeneration_directive") or "").strip()
            if regen:
                state["user_instruction"] = (
                    f"{state.get('user_instruction', '').strip()}\n\n{regen}"
                ).strip()
        content_skill_hints = _merge_intent_hints(
            wanted=ceiling,
            existing_hints=content_skill_hints,
            instruction=str(state.get("user_instruction") or state.get("raw_text") or ""),
        )
        for out in ceiling:
            target = plan_targets.get(out)
            if target:
                content_skill_hints[out] = target
        state["content_skill_hints"] = content_skill_hints

        # Run contract
        contract_nodes: list[dict] = []
        if isinstance(plan_payload, dict):
            run_contract = plan_payload.get("run_contract")
            if isinstance(run_contract, dict) and isinstance(run_contract.get("nodes"), list):
                contract_nodes = [n for n in run_contract["nodes"] if isinstance(n, dict)]
            sel = plan_payload.get("selected_strategy")
            if isinstance(sel, dict):
                opt = sel.get("option")
                if isinstance(opt, dict):
                    title = str(opt.get("title") or "").strip() or str(sel.get("option_id") or "").strip()
                    summ = str(opt.get("summary") or "").strip()[:2000]
                    tools_raw = opt.get("tools_suggested")
                    tlist = [str(x).strip() for x in tools_raw if str(x).strip()] if isinstance(tools_raw, list) else []
                    tools_s = ", ".join(tlist[:16])
                    block = (
                        f"\n\n[User-selected execution strategy: {title}]\n{summ}\n"
                        f"Suggested skills: {tools_s}\n"
                    )
                    state["user_instruction"] = f"{state.get('user_instruction', '')}{block}".strip()

        _coordinator_poll_abort()

        # LLM planning
        wanted, execution_plan = self._plan_with_reasoning(
            state,
            ceiling_types=ceiling,
            effective_registry=effective_registry,
            emit_event=emit_event,
            contract_nodes=contract_nodes,
        )
        state["coordinator_execution_plan"] = {
            "ordered_output_types": execution_plan.ordered_output_types,
            "rationale": execution_plan.rationale,
            "per_output_notes": execution_plan.per_output_notes,
            "used_llm_plan": execution_plan.used_llm_plan,
            "fallback_reason": execution_plan.fallback_reason,
        }
        self._initialize_framework_context(state, wanted)

        _coordinator_poll_abort()

        # Skill selection
        run_id = str(state.get("run_id") or "")
        if run_id:
            langfuse_span(
                trace_id=run_id,
                name="coordinator.plan",
                input_payload={"requested_outputs": ceiling},
                output_payload={
                    "ordered_output_types": execution_plan.ordered_output_types,
                    "used_llm_plan": execution_plan.used_llm_plan,
                    "fallback_reason": execution_plan.fallback_reason,
                },
            )

        skills_by_output: dict[str, list[dict]] = {}
        selected_skills: list[dict] = []
        missing_required: dict[str, list[str]] = {}
        for out_type in wanted:
            required = self.output_requirements.get(out_type, [])
            card_by_id = {
                str(card.get("id") or "").strip(): card
                for card in effective_registry
                if isinstance(card, dict) and str(card.get("id") or "").strip()
            }
            selected_cards: list[dict] = []
            for req_id in required:
                if req_id in card_by_id:
                    selected_cards.append(card_by_id[req_id])
            if not selected_cards:
                for card in effective_registry:
                    if out_type in (card.get("output_types") or []):
                        selected_cards = [card]
                        break
            hint_skill_id = content_skill_hints.get(out_type)
            if hint_skill_id and hint_skill_id in card_by_id:
                hint_card = card_by_id[hint_skill_id]
                if hint_card not in selected_cards:
                    selected_cards.insert(0, hint_card)
            missing = [req_id for req_id in required if req_id not in card_by_id]
            if selected_cards:
                skills_by_output[out_type] = selected_cards
                for selected_card in selected_cards:
                    if selected_card not in selected_skills:
                        selected_skills.append(selected_card)
                if missing:
                    missing_required[out_type] = missing
            else:
                missing_required[out_type] = required

        primary_skill_by_output = {
            out_type: cards[0]
            for out_type, cards in skills_by_output.items()
            if cards
        }
        post_processor_skills_by_output: dict[str, list[dict]] = {}
        for out_type, cards in skills_by_output.items():
            pp = [c for c in cards if str((c or {}).get("role") or "primary").strip().lower() == "post_processor"]
            if pp:
                post_processor_skills_by_output[out_type] = [_skill_public_dict(c) for c in pp]

        state["skill_card"] = {
            "selected_skills": [_skill_public_dict(s) for s in selected_skills],
            "skills_by_output_type": {
                k: [_skill_public_dict(c) for c in vals] for k, vals in skills_by_output.items()
            },
            "primary_skill_by_output_type": {
                k: _skill_public_dict(v) for k, v in primary_skill_by_output.items()
            },
            "missing_required_skills": missing_required,
            "post_processor_skills_by_output_type": post_processor_skills_by_output,
        }

        state["skill_instructions_by_output"] = {}
        for out_type, cards in skills_by_output.items():
            parts: list[str] = []
            for card in cards:
                role = str((card or {}).get("role") or "primary").strip().lower()
                if role == "post_processor":
                    continue
                instruction = str((card or {}).get("prompt_instructions") or "").strip()
                skill_id = str((card or {}).get("id") or "").strip()
                if instruction:
                    parts.append(f"[{skill_id or out_type}] {instruction}")
            if parts:
                state["skill_instructions_by_output"][out_type] = "\n\n".join(parts)

        # Initialize task board
        sm.execution_plan = ExecutionPlanSnapshot(
            ordered_output_types=execution_plan.ordered_output_types,
            rationale=execution_plan.rationale,
            per_output_notes=execution_plan.per_output_notes,
            complexity_weights={
                ot: _OUTPUT_TYPE_COMPLEXITY.get(ot, 3)
                for ot in execution_plan.ordered_output_types
            },
            used_llm_plan=execution_plan.used_llm_plan,
            fallback_reason=execution_plan.fallback_reason,
            thinking_excerpt=execution_plan.thinking_excerpt,
        )
        sm.initialize_task_board(wanted, contract_nodes)

        return sm, state

    def _run_event_loop(
        self,
        state: ProcessDocState,
        *,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
        abort_check: Callable[[], bool] | None = None,
    ) -> ProcessDocState:
        """
        Event-driven agentic loop using CoordinatorStateManager.

        This is the Phase 0 refactoring target that converts from linear pipeline
        to task-board-driven execution with replanning capability.

        For now, this is opt-in via COORDINATOR_AGENTIC_LOOP_ENABLED. Once stable,
        will become the default and the old run() will be deprecated.
        """
        from app.agents.coordinator_state_manager import (
            CoordinatorStateError,
            CoordinatorStateManager,
        )

        with _coordinator_abort_scope(abort_check):
            def _emit(event_type: str, payload: dict[str, Any]) -> None:
                if emit_event:
                    emit_event(event_type, payload)

            run_id = str(state.get("run_id") or "")
            project_id = state.get("project_id")
            state.get("requested_outputs") or []

            # Initialize state manager
            sm = CoordinatorStateManager(
                run_id=run_id,
                project_id=str(project_id) if project_id else "",
            )

            try:
                # Main event loop
                while sm.current_state != "done":
                    _coordinator_poll_abort()

                    if sm.current_state == "init":
                        # Placeholder: In full implementation, transition to planning
                        sm.transition_to("planning")
                        _emit("coordinator_event_loop", {"state": "init", "message": "Starting event loop"})

                    elif sm.current_state == "planning":
                        # Run setup phase: context, planning, skill selection
                        try:
                            sm, state = self._run_setup_phase(
                                state,
                                sm,
                                emit_event=emit_event,
                                abort_check=abort_check,
                            )
                            _LOG.info(f"Setup phase complete: {len(sm.task_board)} tasks created")
                            # Emit initial todo snapshot after task board is populated
                            if emit_event:
                                emit_run_todo_snapshot(emit_event, sm.as_todo_snapshot())
                            sm.transition_to("task_assignment")
                        except Exception as e:
                            _LOG.error(f"Setup phase failed: {e}")
                            raise

                    elif sm.current_state == "task_assignment":
                        # Get ready tasks
                        ready = sm.get_ready_task_ids()

                        if not ready:
                            if sm.all_tasks_done():
                                sm.transition_to("finalize")
                            else:
                                # Wait for tasks to complete
                                time.sleep(0.1)
                                continue
                        else:
                            # Assign ready tasks to teammates
                            for task_id in ready:
                                teammate = sm.next_teammate()
                                sm.assign_task(task_id, teammate)

                            sm.transition_to("execution")

                    elif sm.current_state == "execution":
                        # Poll for task completion and execute tasks
                        updates, failed_tasks = self._poll_and_execute_tasks(
                            state,
                            sm,
                            emit_event=emit_event,
                            abort_check=abort_check,
                        )

                        # Apply state updates
                        if updates:
                            self._apply_worker_patch(state, updates)

                        # Check for failures
                        if failed_tasks:
                            task_id, error = failed_tasks[0]
                            _LOG.warning(f"Task failure detected: {task_id} - {error}")
                            sm.transition_to("replan_on_failure", task_id=task_id, error=error)
                        else:
                            sm.transition_to("task_assignment")

                    elif sm.current_state == "replan_on_failure":
                        # Call lead agent to replan after failure
                        task_id = sm.failure_context.get("task_id")
                        error = sm.failure_context.get("error", "Unknown error")

                        self._lead_replan(
                            state,
                            sm,
                            failed_task_id=task_id,
                            error=error,
                            emit_event=emit_event,
                        )

                        sm.transition_to("task_assignment")

                    elif sm.current_state == "finalize":
                        # Run finalization phase: QA, guardrails, hooks
                        try:
                            state = self._run_finalization_phase(
                                state,
                                sm,
                                wanted=sm.requested_outputs,
                                emit_event=emit_event,
                                abort_check=abort_check,
                            )
                            _LOG.info("Finalization phase complete")
                            sm.transition_to("done")
                        except Exception as e:
                            _LOG.error(f"Finalization phase failed: {e}")
                            raise

                    # Emit state for SSE
                    _emit("coordinator_state_event", sm.get_task_summary())

                _LOG.info(f"Coordinator event loop completed: {sm}")

            except CoordinatorStateError as e:
                _LOG.error(f"Coordinator state error: {e}")
                raise RuntimeError(f"coordinator_state_error: {e}") from e

            return state

    def run(
        self,
        state: ProcessDocState,
        *,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
        abort_check: Callable[[], bool] | None = None,
    ) -> ProcessDocState:
        # Phase 2: Initialize subprocess integration if enabled
        if self.executor and not self.teammate_integration:
            self.teammate_integration = CoordinatorTeammateIntegration(
                executor=self.executor,
                emit_event=emit_event,
            )

        # Phase 0: Use agentic event-driven loop if enabled (opt-in feature)
        # Settings now explicitly loads .env files from both repo root and backend directories
        agentic_loop_enabled = bool(_coordinator_module.settings.coordinator_agentic_loop_enabled)
        _LOG.warning(f"[AGENTIC-CHECK] coordinator_agentic_loop_enabled = {agentic_loop_enabled}")

        if agentic_loop_enabled:
            _LOG.warning("🎯🎯🎯 [AGENTIC-LOOP-ACTIVE] AGENTIC LOOP ENABLED - USING NEW STATE MACHINE PATH 🎯🎯🎯")
            _LOG.info("[AGENTIC-LOOP-ACTIVE] Coordinator using agentic event loop (Phase 0)")
            return self._run_event_loop(
                state,
                emit_event=emit_event,
                abort_check=abort_check,
            )

        # Otherwise, use traditional linear execution pipeline (fallback for stability)
        _LOG.warning("⚠️⚠️⚠️ [AGENTIC-LOOP-DISABLED] AGENTIC LOOP DISABLED - USING OLD THREADPOOL PATH ⚠️⚠️⚠️")
        with _coordinator_abort_scope(abort_check):
            state["framework_rollout_flags"] = {
                "enable_deliverable_registry": bool(_coordinator_module.settings.enable_deliverable_registry),
                "enable_unified_quality_framework": bool(_coordinator_module.settings.enable_unified_quality_framework),
                "enable_content_enrichment_engine": bool(_coordinator_module.settings.enable_content_enrichment_engine),
            }
            # region agent log
            _session_debug_log(
                run_id=str(state.get("run_id") or ""),
                hypothesis_id="H0",
                location="coordinator.py:run:entry",
                message="Coordinator run entered",
                data={
                    "project_id": str(state.get("project_id") or ""),
                    "requested_outputs_raw": state.get("requested_outputs"),
                    "raw_text_chars": len(str(state.get("raw_text") or "")),
                },
            )
            # endregion
            _coordinator_poll_abort()
            if emit_event:
                emit_event("fanout_start", {"stages": ["context_assembly", "skill_selection", "plan_validation"]})
                fanout = self._parallel_read_stages(state)
                if fanout.get("errors"):
                    increment("fanout_failures_total")
                    state["serial_stage_skipped"] = True
                    emit_event("fanout_failed", {"errors": fanout.get("errors")})
                    emit_event("serial_pipeline_skipped", {"reason": "fanout_failed", "errors": fanout.get("errors")})
                    raise RuntimeError("parallel_read_stage_failure")
                state["parallel_stage_contract"] = fanout
                emit_event("fanout_stage_results", fanout)
            _coordinator_poll_abort()
            raw = state.get("raw_text", "")
            redacted, dpdp_report = self.dpdp.redact(raw)
            lp_snippets: list[str] = []
            project_id = state.get("project_id")
            if project_id:
                try:
                    from app.services.leading_practices import leading_practice_library_service

                    dpdp_enabled = bool(state.get("dpdp_flags", {}).get("enabled", True))
                    lp_results = leading_practice_library_service.search(
                        redacted,
                        project_id=project_id,
                        dpdp_enabled=dpdp_enabled,
                    )
                    for r in lp_results:
                        text = r.get("text")
                        heading = r.get("heading") or ""
                        if isinstance(text, str) and text.strip():
                            prefix = f"[LP]{heading}".strip() if heading else "[LP]"
                            lp_snippets.append(f"{prefix}\n{text}")
                except Exception:
                    lp_snippets = []

            memory_events: list[dict[str, object]] = []
            profile_payload: dict[str, object] = {}
            if project_id:
                session = _coordinator_module.SessionLocal()
                try:
                    run_id = state.get("run_id")
                    rows = session.scalars(
                        select(MemoryEvent)
                        .where(MemoryEvent.project_id == project_id)
                        .order_by(MemoryEvent.id.desc())
                        .limit(500)
                    ).all()
                    for row in reversed(rows):
                        try:
                            payload = json.loads(row.payload)
                        except Exception:
                            payload = {"summary": row.payload}
                        memory_events.append({"event_type": row.event_type, "payload": payload})
                    if run_id:
                        memory_events = memory_events[-250:]
                    profile = session.scalar(
                        select(ProjectMemoryProfile).where(ProjectMemoryProfile.project_id == project_id)
                    )
                    if profile and profile.summary_json:
                        try:
                            parsed = json.loads(profile.summary_json)
                            if isinstance(parsed, dict):
                                profile_payload = parsed
                        except Exception:
                            profile_payload = {}
                    memory_v2_enabled = _coordinator_module.settings.memory_v2_retrieval_enabled
                    if memory_v2_enabled:
                        long_term_rows = session.scalars(
                            select(MemoryItem)
                            .where(MemoryItem.project_id == project_id, MemoryItem.is_archived.is_(False))
                            .order_by(MemoryItem.updated_at.desc())
                            .limit(40)
                        ).all()
                        inj, consent_skipped, ledger_skipped = merge_long_term_items_into_profile(
                            profile_payload,
                            list(long_term_rows),
                            respect_consent=_coordinator_module.settings.memory_respect_consent_in_context,
                            session=session,
                            project_id=project_id,
                            enforce_consent_ledger=_coordinator_module.settings.memory_enforce_consent_ledger,
                        )
                        if consent_skipped:
                            increment("memory_items_consent_skipped_total", consent_skipped)
                        if ledger_skipped:
                            increment("memory_items_ledger_blocked_total", ledger_skipped)
                        if inj:
                            increment("memory_items_injected_into_context_total", inj)
                    uid = state.get("user_id")
                    if uid and isinstance(uid, str) and uid.strip():
                        up = session.scalar(
                            select(UserProjectPreference).where(
                                UserProjectPreference.user_id == uid.strip(),
                                UserProjectPreference.project_id == project_id,
                            )
                        )
                        if up and up.preferences_json:
                            try:
                                pj = json.loads(up.preferences_json)
                                if isinstance(pj, dict):
                                    lines = pj.get("context_lines")
                                    if isinstance(lines, list):
                                        clean = [str(x).strip() for x in lines if str(x).strip()]
                                        if clean:
                                            profile_payload.setdefault("user_preference_lines", clean)
                            except Exception:  # noqa: S110 — best-effort, non-fatal
                                pass
                finally:
                    session.close()

            use_v2 = _coordinator_module.settings.memory_compaction_v1_enabled
            if use_v2:
                increment("coordinator_context_assemble_v2_total")
                context = self.context_engine.assemble_v2(
                    project_id,
                    redacted,
                    run_memory_events=memory_events,
                    project_profile=profile_payload,
                    lp_snippets=lp_snippets,
                    char_cap=_coordinator_module.settings.memory_compaction_char_cap,
                )
                state["compaction_snapshot"] = context.metadata or {}
                state["memory_summary"] = {
                    "non_negotiables": profile_payload.get("non_negotiables", []),
                    "recent_changes": [e.get("payload") for e in memory_events[-5:]],
                }
            else:
                context = self.context_engine.assemble(
                    project_id,
                    redacted,
                    lp_snippets=lp_snippets,
                )

            state["assembled_context"] = context.text
            _coordinator_poll_abort()
            # region agent log
            _session_debug_log(
                run_id=str(state.get("run_id") or ""),
                hypothesis_id="H2",
                location="coordinator.py:run:context_assembled",
                message="Context assembled before output generation",
                data={
                    "project_id": str(project_id or ""),
                    "requested_outputs_raw": state.get("requested_outputs"),
                    "assembled_context_chars": len(str(context.text or "")),
                    "compaction_snapshot": state.get("compaction_snapshot"),
                    "context_metadata": context.metadata or {},
                },
            )
            # endregion
            state["dpdp_report_json"] = dpdp_report
            if not state.get("user_instruction"):
                state["user_instruction"] = state.get("raw_text", "")

            self._ensure_deliverable_archetype(state)
            state = _coordinator_module.run_process_extraction(state)
            _coordinator_poll_abort()
            planner_query = (
                f"{str(state.get('user_instruction') or state.get('raw_text') or '')[:4000]}\n"
                f"{_process_model_summary(state)[:2000]}"
            )
            excerpt = self.context_engine.planner_excerpt(
                project_id,
                planner_query,
                char_cap=max(800, _coordinator_module.settings.coordinator_planning_context_chars),
            )
            state["planner_retrieval_excerpt"] = excerpt
            if excerpt:
                increment("planner_excerpt_chars_total", len(excerpt))
            effective_registry = [*self.skill_registry, *self._load_project_custom_skills(project_id)]
            plan_payload = state.get("plan_payload")
            ceiling, content_skill_hints = _canonical_requested(state.get("requested_outputs"))
            plan_targets: dict[str, str] = {}
            if isinstance(plan_payload, dict):
                plan_targets = _sanitize_content_skill_targets(plan_payload.get("content_skill_targets"))
                if isinstance(plan_payload.get("discovery"), dict):
                    state["proposal_discovery"] = dict(plan_payload.get("discovery") or {})
                regen = str(plan_payload.get("regeneration_directive") or "").strip()
                if regen:
                    state["user_instruction"] = (
                        f"{state.get('user_instruction', '').strip()}\n\n{regen}"
                    ).strip()
            content_skill_hints = _merge_intent_hints(
                wanted=ceiling,
                existing_hints=content_skill_hints,
                instruction=str(state.get("user_instruction") or state.get("raw_text") or ""),
            )
            # Persisted plan targets are authoritative for this run.
            for out in ceiling:
                target = plan_targets.get(out)
                if target:
                    content_skill_hints[out] = target
            state["content_skill_hints"] = content_skill_hints
            contract_nodes: list[dict] = []
            if isinstance(plan_payload, dict):
                run_contract = plan_payload.get("run_contract")
                if isinstance(run_contract, dict) and isinstance(run_contract.get("nodes"), list):
                    contract_nodes = [n for n in run_contract["nodes"] if isinstance(n, dict)]
                sel = plan_payload.get("selected_strategy")
                if isinstance(sel, dict):
                    opt = sel.get("option")
                    if isinstance(opt, dict):
                        title = str(opt.get("title") or "").strip() or str(sel.get("option_id") or "").strip()
                        summ = str(opt.get("summary") or "").strip()[:2000]
                        tools_raw = opt.get("tools_suggested")
                        tlist = [str(x).strip() for x in tools_raw if str(x).strip()] if isinstance(tools_raw, list) else []
                        tools_s = ", ".join(tlist[:16])
                        block = (
                            f"\n\n[User-selected execution strategy: {title}]\n{summ}\n"
                            f"Suggested skills: {tools_s}\n"
                        )
                        state["user_instruction"] = f"{state.get('user_instruction', '')}{block}".strip()

            _coordinator_poll_abort()
            wanted, execution_plan = self._plan_with_reasoning(
                state,
                ceiling_types=ceiling,
                effective_registry=effective_registry,
                emit_event=emit_event,
                contract_nodes=contract_nodes,
            )
            state["coordinator_execution_plan"] = {
                "ordered_output_types": execution_plan.ordered_output_types,
                "rationale": execution_plan.rationale,
                "per_output_notes": execution_plan.per_output_notes,
                "used_llm_plan": execution_plan.used_llm_plan,
                "fallback_reason": execution_plan.fallback_reason,
            }
            self._initialize_framework_context(state, wanted)
            _coordinator_poll_abort()
            milestone_labels = _milestone_labels_from_plan(execution_plan, wanted)
            run_todos = build_run_todo_rows(wanted, milestone_labels=milestone_labels)
            for _tid in ("context", "process_model", "plan"):
                todo_set_status(run_todos, _tid, "done")
            emit_run_todo_snapshot(emit_event, run_todos)
            run_id = str(state.get("run_id") or "")
            if run_id:
                langfuse_span(
                    trace_id=run_id,
                    name="coordinator.plan",
                    input_payload={"requested_outputs": ceiling},
                    output_payload={
                        "ordered_output_types": execution_plan.ordered_output_types,
                        "used_llm_plan": execution_plan.used_llm_plan,
                        "fallback_reason": execution_plan.fallback_reason,
                    },
                )
            scratchpad_lines: list[str] = []
            if execution_plan.rationale:
                scratchpad_lines.append(f"Plan rationale: {execution_plan.rationale}")
            if execution_plan.per_output_notes:
                scratchpad_lines.append("Per-output notes:")
                for out, note in execution_plan.per_output_notes.items():
                    if str(note).strip():
                        scratchpad_lines.append(f"- {out}: {str(note).strip()[:220]}")
            if execution_plan.fallback_reason:
                scratchpad_lines.append(f"Planner fallback: {execution_plan.fallback_reason}")
            if scratchpad_lines and _coordinator_module.settings.scratchpad_visibility_enabled:
                state["scratchpad_summary"] = "\n".join(scratchpad_lines)[:4000]
            # region agent log
            _debug_log(
                "H4",
                "coordinator.py:run:requested",
                "Requested outputs canonicalized",
                {
                    "project_id": project_id,
                    "requested_outputs_raw": state.get("requested_outputs"),
                    "wanted_outputs": wanted,
                },
            )
            # endregion

            # Select the relevant skill cards for the requested output types.
            # This is primarily used for downstream prompt/tool governance; generation
            # still routes to the concrete sub-agents implemented in `subagents.py`.
            skills_by_output: dict[str, list[dict]] = {}
            selected_skills: list[dict] = []
            missing_required: dict[str, list[str]] = {}
            content_skill_hints: dict[str, str] = state.get("content_skill_hints") or {}
            for out_type in wanted:
                required = self.output_requirements.get(out_type, [])
                card_by_id = {
                    str(card.get("id") or "").strip(): card
                    for card in effective_registry
                    if isinstance(card, dict) and str(card.get("id") or "").strip()
                }
                selected_cards: list[dict] = []
                for req_id in required:
                    if req_id in card_by_id:
                        selected_cards.append(card_by_id[req_id])
                if not selected_cards:
                    for card in effective_registry:
                        if out_type in (card.get("output_types") or []):
                            selected_cards = [card]
                            break
                # Inject content skill hint at position 0 so it becomes the primary skill.
                # When a user requests "sop" (aliased to "docx"), sop_v2 drives the content
                # structure while docx_v1 and frontend_design_docx_v1 add formatting guidance.
                hint_skill_id = content_skill_hints.get(out_type)
                if hint_skill_id and hint_skill_id in card_by_id:
                    hint_card = card_by_id[hint_skill_id]
                    # Insert at front if not already present
                    if hint_card not in selected_cards:
                        selected_cards.insert(0, hint_card)
                missing = [req_id for req_id in required if req_id not in card_by_id]
                if selected_cards:
                    skills_by_output[out_type] = selected_cards
                    for selected_card in selected_cards:
                        if selected_card not in selected_skills:
                            selected_skills.append(selected_card)
                    if missing:
                        missing_required[out_type] = missing
                else:
                    missing_required[out_type] = required

            primary_skill_by_output = {
                out_type: cards[0]
                for out_type, cards in skills_by_output.items()
                if cards
            }
            # Separate primary generator skills from post-processor skills.
            # Post-processors (role="post_processor") run after the primary output is generated
            # to apply styling/brand passes — they must NOT be mixed into the generation prompt.
            post_processor_skills_by_output: dict[str, list[dict]] = {}
            for out_type, cards in skills_by_output.items():
                pp = [c for c in cards if str((c or {}).get("role") or "primary").strip().lower() == "post_processor"]
                if pp:
                    post_processor_skills_by_output[out_type] = [_skill_public_dict(c) for c in pp]

            state["skill_card"] = {
                "selected_skills": [_skill_public_dict(s) for s in selected_skills],
                "skills_by_output_type": {
                    k: [_skill_public_dict(c) for c in vals] for k, vals in skills_by_output.items()
                },
                "primary_skill_by_output_type": {
                    k: _skill_public_dict(v) for k, v in primary_skill_by_output.items()
                },
                "missing_required_skills": missing_required,
                # Post-processor skills keyed by output type — consumed by sub-agents after primary generation.
                "post_processor_skills_by_output_type": post_processor_skills_by_output,
            }
            # Build skill instructions ONLY from primary generator skills.
            # Injecting post-processor instructions (e.g. brand colors, typography) into the
            # generation prompt conflates document writing with visual styling.
            state["skill_instructions_by_output"] = {}
            for out_type, cards in skills_by_output.items():
                parts: list[str] = []
                for card in cards:
                    role = str((card or {}).get("role") or "primary").strip().lower()
                    if role == "post_processor":
                        continue  # post-processors applied as a separate pass, not here
                    instruction = str((card or {}).get("prompt_instructions") or "").strip()
                    skill_id = str((card or {}).get("id") or "").strip()
                    if instruction:
                        parts.append(f"[{skill_id or out_type}] {instruction}")
                if parts:
                    state["skill_instructions_by_output"][out_type] = "\n\n".join(parts)
            # region agent log
            _debug_log(
                "H5",
                "coordinator.py:run:skill_selection",
                "Skills selected for requested outputs",
                {
                    "project_id": project_id,
                    "wanted_outputs": wanted,
                    "selected_skill_ids": [str((s or {}).get("id") or "") for s in selected_skills],
                    "skills_by_output_type": {k: [str((v or {}).get("id") or "") for v in vals] for k, vals in skills_by_output.items()},
                    "missing_required_skills": missing_required,
                },
            )
            # endregion
            # region agent log
            _session_debug_log(
                run_id=str(state.get("run_id") or ""),
                hypothesis_id="H1",
                location="coordinator.py:run:skills_for_outputs",
                message="Skill selection resolved for outputs",
                data={
                    "wanted_outputs": wanted,
                    "content_skill_hints": content_skill_hints,
                    "skills_by_output_type": {
                        k: [str((v or {}).get("id") or "") for v in vals] for k, vals in skills_by_output.items()
                    },
                    "primary_skill_by_output_type": {
                        k: str((v or {}).get("id") or "") for k, v in primary_skill_by_output.items()
                    },
                },
            )
            # endregion
            if emit_event:
                hook_results = _coordinator_module.run_hooks_sync(
                    "post_skill_selection",
                    {"state": state, "project_id": project_id, "run_id": state.get("run_id")},
                    project_id=str(project_id) if project_id else None,
                )
                for h in hook_results:
                    emit_event(
                        "hook_result",
                        {
                            "hook_point": "post_skill_selection",
                            "hook_name": h.hook_name,
                            "outcome": h.outcome,
                            "message": h.message,
                        },
                    )
                    if h.outcome == "ABORT":
                        raise RuntimeError(f"hook_abort:{h.hook_name}:{h.message}")

            _coordinator_poll_abort()
            if emit_event:
                state["_emit_run_event"] = emit_event
            else:
                state.pop("_emit_run_event", None)

            if bool(getattr(_coordinator_module.settings, "swarm_orchestration_enabled", False)):
                cycle = ("teammate-2", "teammate-3", "teammate-1")
                by_ot: dict[str, str] = {}
                idx = 0
                for k in wanted:
                    if k in _coordinator_module._OUTPUT_AGENTS:
                        by_ot[k] = cycle[idx % len(cycle)]
                        idx += 1
                state["swarm_teammate_by_output"] = by_ot
            else:
                state.pop("swarm_teammate_by_output", None)

            max_workers = min(4, max(1, len([k for k in wanted if k in _coordinator_module._OUTPUT_AGENTS])))

            qa_report: dict[str, Any] = {}
            guardrail_report: dict[str, Any] = {}

            todo_bulk_set(run_todos, "out:", "running")
            emit_run_todo_snapshot(emit_event, run_todos)

            # run_contract node order is authoritative when present; parallel fan-out uses `wanted` order otherwise.
            if contract_nodes:
                worker_by_output = {k: _coordinator_module._OUTPUT_AGENTS[k] for k in wanted if k in _coordinator_module._OUTPUT_AGENTS}
                node_statuses: list[dict] = []
                for node in contract_nodes:
                    _coordinator_poll_abort()
                    output_type = str(node.get("output_type") or "").strip()
                    node_id = str(node.get("id") or output_type or "node")
                    if output_type not in worker_by_output:
                        node_statuses.append({"id": node_id, "output_type": output_type, "status": "skipped"})
                        continue
                    retry_policy = node.get("retry_policy") if isinstance(node.get("retry_policy"), dict) else {}
                    max_retries = int(retry_policy.get("max_retries", 1) or 1)
                    update, err = self._execute_worker_with_retry(
                        worker_by_output[output_type],
                        state,
                        max_retries=max_retries,
                        output_type=output_type,
                    )
                    self._apply_worker_patch(state, update)
                    node_statuses.append(
                        {
                            "id": node_id,
                            "output_type": output_type,
                            "status": "failed" if err else "completed",
                            "error": err,
                        }
                    )
                state["run_contract_progress"] = node_statuses
            else:
                worker_jobs = [(k, _coordinator_module._OUTPUT_AGENTS[k]) for k in wanted if k in _coordinator_module._OUTPUT_AGENTS]

                # Phase 2: Use subprocess workers if enabled, otherwise use ThreadPoolExecutor
                if self.teammate_integration:
                    # Subprocess-based execution
                    _LOG.info(f"Using subprocess workers for {len(worker_jobs)} output types")
                    for k, _w in worker_jobs:
                        _coordinator_poll_abort()
                        patch, err = self.teammate_integration.execute_worker_subprocess(
                            output_type=k,
                            state=state,
                            task_id=f"out:{k}",
                        )
                        if err:
                            state.setdefault("worker_errors", []).append(err)
                        elif patch:
                            self._apply_worker_patch(state, patch)
                else:
                    # Traditional ThreadPoolExecutor-based execution
                    _LOG.info(f"Using ThreadPoolExecutor for {len(worker_jobs)} output types")
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        future_map = {
                            executor.submit(
                                self._execute_worker_with_retry,
                                w,
                                state,
                                max_retries=1,
                                output_type=k,
                                defer_state_merge=True,
                            ): k
                            for k, w in worker_jobs
                        }
                        for fut in as_completed(future_map):
                            _coordinator_poll_abort()
                            patch, err = fut.result()
                            if err:
                                state.setdefault("worker_errors", []).append(err)
                            elif patch:
                                self._apply_worker_patch(state, patch)

            werrs = state.get("worker_errors")
            failed_workers = bool(werrs) if isinstance(werrs, list) else bool(werrs)
            if contract_nodes:
                prog = state.get("run_contract_progress") or []
                by_ot = {
                    str(p.get("output_type") or "").strip(): p
                    for p in prog
                    if isinstance(p, dict) and str(p.get("output_type") or "").strip()
                }
                for row in run_todos:
                    rid = str(row.get("id") or "")
                    if not rid.startswith("out:"):
                        continue
                    ot = rid[4:]
                    st = str((by_ot.get(ot) or {}).get("status") or "").lower()
                    if st == "failed":
                        row["status"] = "failed"
                    elif st == "skipped":
                        row["status"] = "skipped"
                    elif st == "completed":
                        row["status"] = "done"
                    else:
                        row["status"] = "failed" if failed_workers else "done"
            else:
                for row in run_todos:
                    if str(row.get("id") or "").startswith("out:"):
                        row["status"] = "failed" if failed_workers else "done"
            emit_run_todo_snapshot(emit_event, run_todos)

            _coordinator_poll_abort()
            if bool(getattr(_coordinator_module.settings, "swarm_execute_custom_tasks_enabled", False)):
                from app.services.swarm_custom_tasks import execute_custom_swarm_tasks_sync

                execute_custom_swarm_tasks_sync(
                    project_id=str(project_id or state.get("project_id") or ""),
                    run_id=str(state.get("run_id") or ""),
                    emit_event=emit_event,
                )

            outputs = self._outputs_from_state(state, wanted)
            unified_reports, outputs = self._run_unified_quality_framework(state, outputs, wanted, emit_event=emit_event)
            state["deliverable_quality_report"] = None
            state["unified_quality_reports"] = unified_reports
            qa_threshold = float(state.get("qa_threshold", 0.8))
            max_qa_loops = max(1, min(5, int(state.get("max_qa_loops", 2) or 2)))
            todo_set_status(run_todos, "qa", "running")
            emit_run_todo_snapshot(emit_event, run_todos)
            _coordinator_poll_abort()
            qa_report = self.qa_loop.run(
                outputs,
                threshold=qa_threshold,
                project_id=state.get("project_id"),
                max_loops=max_qa_loops,
            )
            if not qa_report.get("passed", False):
                remediation = qa_report.get("remediation_instructions", {})
                if isinstance(remediation, dict) and remediation:
                    _coordinator_poll_abort()
                    pre_scores = qa_report.get("scores", {})
                    outputs = self._apply_qa_remediation(state, wanted, remediation)
                    post_qa = self.qa_loop.run(
                        outputs,
                        threshold=qa_threshold,
                        project_id=state.get("project_id"),
                        max_loops=max_qa_loops,
                    )
                    post_qa["pre_remediation_scores"] = pre_scores
                    post_qa["remediation_applied"] = True
                    post_qa["remediation_converged"] = bool(post_qa.get("passed", False))
                    qa_report = post_qa

            todo_set_status(run_todos, "qa", "done")
            emit_run_todo_snapshot(emit_event, run_todos)
            todo_set_status(run_todos, "guardrails", "running")
            emit_run_todo_snapshot(emit_event, run_todos)
            _coordinator_poll_abort()
            guardrail_report = self.guardrails.evaluate(outputs, dpdp_gate7=True)
            todo_set_status(run_todos, "guardrails", "done")
            emit_run_todo_snapshot(emit_event, run_todos)
            state["qa_report"] = qa_report
            state["guardrail_report"] = guardrail_report
            state["run_todos"] = run_todos
            if emit_event:
                hook_results = _coordinator_module.run_hooks_sync(
                    "post_output_generation",
                    {"state": state, "project_id": project_id, "run_id": state.get("run_id")},
                    project_id=str(project_id) if project_id else None,
                )
                for h in hook_results:
                    emit_event(
                        "hook_result",
                        {
                            "hook_point": "post_output_generation",
                            "hook_name": h.hook_name,
                            "outcome": h.outcome,
                            "message": h.message,
                        },
                    )
                    if h.outcome == "ABORT":
                        raise RuntimeError(f"hook_abort:{h.hook_name}:{h.message}")
                emit_event("fanout_complete", {"stages": ["context_assembly", "skill_selection", "plan_validation"]})

            # Phase 2: Cleanup subprocess workers
            if self.teammate_integration:
                self.teammate_integration.terminate_all_subprocesses()

            return state

    async def coordinate(
        self,
        state: ProcessDocState,
        *,
        abort_check: Callable[[], bool] | None = None,
    ):
        """
        Async generator wrapper for run orchestration events.
        Keeps compatibility by reusing `run()` while yielding typed events.
        """
        emitted: list[tuple[str, dict[str, Any]]] = []

        def _emit(event_type: str, payload: dict[str, Any]) -> None:
            emitted.append((event_type, payload if isinstance(payload, dict) else {"value": str(payload)}))

        run_id = str(state.get("run_id") or "")
        _emit("coordinator_started", {"status": "running"})
        final_state = self.run(state, emit_event=_emit, abort_check=abort_check)
        for et, pl in emitted:
            yield {
                "event_type": et,
                "payload": build_event_payload(run_id=run_id, event_type=et, payload_obj=pl),
            }
        yield {
            "event_type": "coordinator_completed",
            "payload": build_event_payload(
                run_id=run_id,
                event_type="coordinator_completed",
                payload_obj={"status": "done"},
            ),
        }
        yield {"event_type": "coordinator_state", "payload": {"state": final_state}}
