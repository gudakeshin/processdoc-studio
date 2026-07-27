import asyncio
import contextlib
import json
import logging
import shutil
import threading
import time
import uuid
from datetime import datetime
from app.core.tz import IST
from pathlib import Path

import redis
from fastapi import APIRouter, Depends, HTTPException, Query, Request

logger = logging.getLogger(__name__)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.formats import _load_output_types
from app.core.auth import get_current_user, get_current_user_sse, require_project_role
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.models import Conversation, ConversationMessage, MemoryEvent, Run, RunEvent, RunTask, ScheduledTaskRun, User, utcnow
from app.db.session import SessionLocal, get_db
from app.schemas.common import RunSummary
from app.services.claude import claude_generate_json, is_claude_enabled
from app.services.output_format_detection import (
    detect_deliverable_keyword_formats,
    detect_explicit_output_formats,
    resolve_output_formats,
)
from app.services.hooks import disable_hook, list_registered_hooks, sync_disabled_hooks_from_db, upsert_hook_control
from app.services.observability import increment
from app.services.permission_pipeline import evaluate_permission_pipeline
from app.services.run_budget import get_live_usage
from app.services.run_events import lifecycle_event
from app.services.run_tasks import serialize_run_task
from app.services.run_worker import (
    admission_status,
    append_memory_event,
    append_run_event,
    enqueue_run_execution,
    list_dead_letter_items,
    maybe_start_run_execution,
    replay_dead_letter_item,
    reset_dead_letter_attempts,
)
from app.services.storage import workspace_path
from app.services.swarm import persist_instruction_broadcast_swarm_event_payload

router = APIRouter()
_log = logging.getLogger(__name__)

# Shared Redis connection pool for SSE pub/sub subscriptions.
# Created lazily on first SSE request so the pool is not allocated when Redis is unused.
# All concurrent streams share this pool; each active subscription borrows one connection.
_sse_redis_pool: redis.ConnectionPool | None = None
_sse_redis_pool_lock = threading.Lock()


def _get_or_create_sse_redis_pool() -> redis.ConnectionPool | None:
    global _sse_redis_pool
    if settings.run_queue_backend != "redis":
        return None
    if _sse_redis_pool is not None:
        return _sse_redis_pool
    with _sse_redis_pool_lock:
        if _sse_redis_pool is None:
            try:
                _sse_redis_pool = redis.ConnectionPool.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    max_connections=settings.sse_redis_max_connections,
                )
            except Exception as exc:
                _log.warning("%s: suppressed error: %s", '_get_or_create_sse_redis_pool', exc)
                return None
    return _sse_redis_pool


def _run_create_rate_limit() -> str:
    return (settings.run_create_rate_limit or "20/minute").strip() or "20/minute"


def _run_approve_rate_limit() -> str:
    return (settings.run_approve_rate_limit or "20/minute").strip() or "20/minute"


def _run_recommend_rate_limit() -> str:
    return (settings.run_recommend_rate_limit or "30/minute").strip() or "30/minute"


def _run_regenerate_rate_limit() -> str:
    return (settings.run_regenerate_rate_limit or "10/minute").strip() or "10/minute"


def _ensure_run_enqueued(project_id: str, run_id: str, *, context: str) -> None:
    if enqueue_run_execution(project_id, run_id):
        return
    _log.error(
        "%s: enqueue_run_execution returned False (project_id=%s run_id=%s)",
        context,
        project_id,
        run_id,
    )
    raise HTTPException(
        status_code=503,
        detail={
            "message": "Run could not be queued for execution. Retry shortly or check server logs.",
            "run_id": run_id,
            "context": context,
        },
    )


def _session_debug_log(*, run_id: str | None, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    raw = (settings.processdoc_runs_debug_log or "").strip()
    if not raw:
        return
    try:
        path = Path(raw)
        payload = {
            "runId": str(run_id or ""),
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:  # noqa: S110 — best-effort, non-fatal
        pass


def _detail(code: str, message: str, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _debug_log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    raw = (settings.processdoc_runs_debug_log or "").strip()
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
    except Exception:  # noqa: S110 — best-effort, non-fatal
        pass


class CreateRunRequest(BaseModel):
    project_id: str
    output_types: list[str] = []
    custom_output_types: list[str] = []
    output_type_representations: dict[str, str] = {}
    instruction: str = "Create deliverables"
    conversation_id: str | None = None
    plan_hash: str | None = None


class UpdatePlanRequest(BaseModel):
    instruction: str
    output_types: list[str]
    custom_output_types: list[str] = []
    output_type_representations: dict[str, str] = {}


class RunTaskActionRequest(BaseModel):
    action: str
    reason: str | None = None


def _normalize_custom_output_types(raw: list[str] | None) -> list[str]:
    # Keep custom formats bounded/deterministic for storage and display.
    normalized: list[str] = []
    for item in raw or []:
        value = str(item or "").strip()
        if not value:
            continue
        if len(value) > 120:
            value = value[:120]
        if value not in normalized:
            normalized.append(value)
        if len(normalized) >= 12:
            break
    return normalized


def _infer_output_types_for_confirmation(
    *,
    instruction: str,
    available_output_types: list[dict],
) -> tuple[list[str], list[str], dict[str, str], str]:
    """
    Best-effort inference used only when output selection is missing.
    We surface this as an advisory suggestion; caller must still confirm.
    """
    try:
        return _recommend_output_types(instruction, available_output_types)
    except Exception:
        return [], [], {}, "Unable to infer outputs automatically. Please select output types.", None


def _build_plan_payload(
    *,
    project_id: str,
    instruction: str,
    output_types: list[str],
    custom_output_types: list[str],
    output_type_representations: dict[str, str],
    content_skill_targets: dict[str, str] | None = None,
    regeneration_directive: str | None = None,
) -> dict:
    from app.services.storage import workspace_path

    parsed_dir = workspace_path(project_id) / "parsed_docs"
    source_dir = workspace_path(project_id) / "source_docs"
    doc_count = len(list(source_dir.glob("*"))) if source_dir.exists() else 0
    parsed_count = len(list(parsed_dir.glob("*.json"))) if parsed_dir.exists() else 0
    parsed_chunk_count = 0
    if parsed_dir.exists():
        for parsed_file in parsed_dir.glob("*.json"):
            try:
                # Estimate chunk count from file size; avoids reading every parsed document
                # at run-start time (major I/O bottleneck under concurrent load).
                # Parsed JSON is ~1–3 KB per text chunk including metadata.
                parsed_chunk_count += max(1, parsed_file.stat().st_size // 1500)
            except OSError:
                parsed_chunk_count += 3
    estimated_tokens = max(800, min(12000, len(instruction.split()) * 6 + (parsed_count * 120)))
    canonical_outputs = list(dict.fromkeys(output_types))
    contract_nodes: list[dict] = []
    for idx, output_key in enumerate(canonical_outputs):
        output_name = str(output_key or "").strip()
        if not output_name:
            continue
        contract_nodes.append(
            {
                "id": f"node_{idx+1}_{output_name}",
                "output_type": output_name,
                "depends_on": [] if idx == 0 else [contract_nodes[-1]["id"]],
                "acceptance_criteria": [
                    "output_is_non_empty",
                    "qa_score_gte_threshold",
                    "guardrails_status_pass",
                ],
                "retry_policy": {"max_retries": 1, "timeout_sec": 180},
                "budget": {
                    "token_estimate": max(200, int(estimated_tokens / max(1, len(canonical_outputs)))),
                },
            }
        )
    return {
        "skill_card": "auto_selected",
        "context_summary": {
            "doc_count": doc_count,
            "parsed_doc_count": parsed_count,
            "parsed_chunk_count": parsed_chunk_count,
            "instruction_chars": len(instruction),
        },
        "sub_agents": canonical_outputs,
        "custom_output_types": custom_output_types,
        "output_type_representations": output_type_representations,
        "content_skill_targets": {
            str(k).strip(): str(v).strip()
            for k, v in (content_skill_targets or {}).items()
            if str(k).strip() and str(v).strip()
        },
        "regeneration_directive": str(regeneration_directive or "").strip(),
        "estimated_tokens": estimated_tokens,
        "run_contract": {
            "version": "v1",
            "objective": instruction[:1000],
            "nodes": contract_nodes,
            "global_retry_policy": {"max_retries_per_node": 1, "backoff_sec": 2},
            "evaluator_gates": ["qa_report", "visual_qa_report", "guardrail_report"],
            "ready_gate": "all_evaluators_pass",
        },
    }


def _normalize_output_type_representations(raw: dict[str, str] | None) -> dict[str, str]:
    allowed: dict[str, set[str]] = {
        "process_map": {"drawio_xml", "mermaid"},
        "docx": {"docx"},
        "pptx": {"pptx"},
        "xlsx": {"xlsx"},
        "pdf": {"pdf"},
        "brand_guidelines": {"markdown", "md"},
    }
    out: dict[str, str] = {}
    for key, value in (raw or {}).items():
        output_type = str(key or "").strip().lower()
        representation = str(value or "").strip().lower()
        if output_type in allowed and representation in allowed[output_type]:
            out[output_type] = representation
    return out


def _load_confirmed_plan(
    *,
    project_id: str,
    user_id: str,
    conversation_id: str | None,
    plan_hash: str | None,
    db: Session,
) -> dict:
    conv_query = select(Conversation).where(Conversation.project_id == project_id, Conversation.user_id == user_id)
    if conversation_id:
        conv_query = conv_query.where(Conversation.id == conversation_id)
    conv_query = conv_query.order_by(Conversation.updated_at.desc()).limit(1)
    conv = db.scalar(conv_query)
    if not conv:
        raise HTTPException(
            status_code=409,
            detail=_detail("confirmed_plan_conversation_missing", "No conversation found for confirmed plan"),
        )

    msg_query = (
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conv.id)
        .order_by(ConversationMessage.id.desc())
    )
    rows = db.scalars(msg_query).all()
    for row in rows:
        try:
            metadata = json.loads(row.metadata_json or "{}")
        except Exception:  # noqa: S112 — best-effort, non-fatal
            continue
        if not isinstance(metadata, dict) or not metadata.get("plan_confirmed"):
            continue
        confirmed_hash = str(metadata.get("plan_hash") or "")
        if plan_hash and plan_hash != confirmed_hash:
            continue
        template_output_types = metadata.get("template_output_types")
        custom_output_types = metadata.get("custom_output_types")
        reps = metadata.get("output_type_representations")
        return {
            "conversation_id": conv.id,
            "plan_hash": confirmed_hash,
            "instruction": str(metadata.get("instruction") or ""),
            "template_output_types": template_output_types if isinstance(template_output_types, list) else [],
            "custom_output_types": custom_output_types if isinstance(custom_output_types, list) else [],
            "output_type_representations": reps if isinstance(reps, dict) else {},
            "content_skill_targets": metadata.get("content_skill_targets")
            if isinstance(metadata.get("content_skill_targets"), dict)
            else {},
            "regeneration_directive": str(metadata.get("regeneration_directive") or ""),
            "decision_answers": metadata.get("decision_answers") if isinstance(metadata.get("decision_answers"), dict) else {},
            "strategy_dossier": metadata.get("strategy_dossier") if isinstance(metadata.get("strategy_dossier"), dict) else None,
            "selected_strategy": metadata.get("selected_strategy") if isinstance(metadata.get("selected_strategy"), dict) else None,
            "deck_outline_preview": metadata.get("deck_outline_preview") if isinstance(metadata.get("deck_outline_preview"), dict) else None,
            "document_outline_preview": metadata.get("document_outline_preview") if isinstance(metadata.get("document_outline_preview"), dict) else None,
            "wiki_context_refs": metadata.get("wiki_context_refs") if isinstance(metadata.get("wiki_context_refs"), list) else [],
        }
    raise HTTPException(
        status_code=409,
        detail=_detail(
            "confirmed_plan_missing",
            "Run creation requires latest confirmed plan",
            conversation_id=conv.id,
            requested_plan_hash=plan_hash or "",
        ),
    )


class ReplayDeadLetterRequest(BaseModel):
    item_id: str


class PermissionSimulationRequest(BaseModel):
    run_status: str = "approved"
    requested_outputs: list[str] = []
    has_approval: bool = True
    enforce_policy: bool = True
    plan_payload: dict[str, object] | None = None


class ResetDeadLetterRequest(BaseModel):
    item_id: str


class FinalApproveRequest(BaseModel):
    notes: str | None = None


class ControlRunRequest(BaseModel):
    action: str


class RegenerateSlideRequest(BaseModel):
    instruction: str
    scope: str = "slide"
    element_path: str | None = None


class PatchSlideElementRequest(BaseModel):
    element_path: str
    value: str | int | float | bool | None = None


class RecommendOutputTypesRequest(BaseModel):
    project_id: str
    instruction: str


def _recommend_output_types(
    instruction: str, available_output_types: list[dict]
) -> tuple[list[str], list[str], dict[str, str], str, dict | None]:
    if not is_claude_enabled():
        raise HTTPException(status_code=503, detail="LLM recommendations unavailable: missing ANTHROPIC_API_KEY")
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
        "You are an output-type recommender for process deliverables. "
        "Return only JSON with keys: template_output_types (string[]), custom_output_types (string[]), "
        "output_type_representations (object), rationale (string), "
        "content_skill_hint (object|null). "
        "Only choose template_output_types from the provided catalog.\n\n"
        "content_skill_hint: If the instruction indicates a specific deliverable domain, "
        "return {\"domain\": <domain_label>, \"confidence\": <0.0-1.0>} where domain_label "
        "is one of: \"proposal_finance_transformation\", \"proposal_operations\", "
        "\"proposal_product\", \"proposal_generic\", \"approach_note\", \"process_documentation\", "
        "\"training\", or null if no clear domain. confidence is your certainty (0.0-1.0). "
        "Use proposal_finance_transformation for finance, CFO, FP&A, close acceleration, "
        "treasury, controllership, record-to-report, order-to-cash, procure-to-pay topics. "
        "Use proposal_operations for supply chain, logistics, manufacturing, quality. "
        "Use proposal_generic for proposals without a clear domain specialization."
    )
    lowered = (instruction or "").lower()
    explicit_formats_requested = detect_explicit_output_formats(lowered)
    desired_types = detect_deliverable_keyword_formats(lowered)

    # ── Short-circuit: format intent fully determines the answer ──────────────
    _catalog_ids = {str(item.get("output_type_id")) for item in catalog}
    resolved_formats, resolved_reps, resolved_rationale = resolve_output_formats(instruction, _catalog_ids)
    if resolved_formats:
        return resolved_formats, [], resolved_reps, resolved_rationale, None

    deliverable_constraints_text = (
        "Deliverable intent -> preferred output types/representations:\n"
        "- Proposal -> docx|pptx\n"
        "- Approach Note -> docx|pptx\n"
        "- Process Flow -> docx|pptx\n"
        "- Narratives -> docx|pptx\n"
        "- RACI -> xlsx\n"
        "- SOP -> docx|pptx\n"
        "- Business Requirement Document (BRD) -> docx|pptx\n"
        "- Improvement Report -> docx|pptx\n"
        "- Financial Model -> xlsx\n"
        "- Training Deck -> pptx\n\n"
        "If the instruction clearly matches any deliverable intent above, prefer the mapped output types."
    )

    user = (
        f"Instruction:\n{instruction}\n\n"
        f"Template catalog JSON:\n{json.dumps(catalog)}\n\n"
        "Select the best template output types and suggest additional custom output types if needed.\n"
        f"\n{deliverable_constraints_text}\n"
        "For output_type_representations choose representations by output type from:\n"
        "- process_map: drawio_xml|mermaid\n"
        "- docx: docx\n"
        "- pptx: pptx\n"
        "- xlsx: xlsx\n"
        "- pdf: pdf\n"
        "Only include keys that are present in chosen template_output_types."
    )
    payload = claude_generate_json(system=system, user=user, temperature=0.2, max_tokens=700)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Invalid LLM recommendation payload")
    template_ids = payload.get("template_output_types")
    custom = payload.get("custom_output_types")
    prefs = payload.get("output_type_representations")
    rationale = str(payload.get("rationale") or "Recommended by LLM analysis.")
    allowed = {str(item.get("output_type_id")) for item in catalog}
    out_ids = [str(x) for x in (template_ids if isinstance(template_ids, list) else []) if str(x) in allowed]
    if not out_ids and catalog:
        out_ids = [str(catalog[0]["output_type_id"])]
    out_custom = _normalize_custom_output_types(custom if isinstance(custom, list) else [])
    normalized_prefs = _normalize_output_type_representations(prefs if isinstance(prefs, dict) else {})
    chosen = list(dict.fromkeys(out_ids))

    # Only auto-include process maps for explicit map intent.
    lowered_instruction = (instruction or "").lower()
    explicit_process_map_signals = ("process map", "swimlane", "flowchart", "draw.io", "drawio", "bpmn")
    if (
        any(sig in lowered_instruction for sig in explicit_process_map_signals)
        and "process_map" in allowed
        and "process_map" not in chosen
    ):
        chosen.append("process_map")

    # Post-process with deliverable constraints when we clearly detected intent keywords.
    if desired_types:
        allowed_desired = [t for t in desired_types if t in allowed]
        if allowed_desired:
            chosen = [t for t in chosen if t in set(allowed_desired)] or []
            for t in allowed_desired:
                if t not in chosen:
                    chosen.append(t)

    # CRITICAL: If explicit format constraints were detected, FORCE output to be only those formats
    # This overrides any LLM recommendations that tried to add additional formats
    if explicit_formats_requested:
        allowed_explicit = [t for t in explicit_formats_requested if t in allowed]
        if allowed_explicit:
            # Remove any formats not in the explicit constraint list
            chosen = [t for t in chosen if t in set(allowed_explicit)]
            # Add explicit formats that should be included
            for t in allowed_explicit:
                if t not in chosen:
                    chosen.append(t)

    normalized_prefs = {k: v for k, v in normalized_prefs.items() if k in set(chosen)}
    if "process_map" in chosen and "process_map" not in normalized_prefs:
        normalized_prefs["process_map"] = "drawio_xml"
    if "docx" in chosen and "docx" not in normalized_prefs:
        normalized_prefs["docx"] = "docx"
    if "pptx" in chosen and "pptx" not in normalized_prefs:
        normalized_prefs["pptx"] = "pptx"
    if "xlsx" in chosen and "xlsx" not in normalized_prefs:
        normalized_prefs["xlsx"] = "xlsx"
    if "pdf" in chosen and "pdf" not in normalized_prefs:
        normalized_prefs["pdf"] = "pdf"

    # Extract LLM-based skill classification hint (folded into same call — zero extra cost)
    content_skill_hint = payload.get("content_skill_hint")
    if isinstance(content_skill_hint, dict):
        domain = str(content_skill_hint.get("domain") or "").strip()
        confidence = float(content_skill_hint.get("confidence") or 0)
        if domain and confidence >= 0.6:
            content_skill_hint = {"domain": domain, "confidence": confidence}
        else:
            content_skill_hint = None
    else:
        content_skill_hint = None

    return chosen, out_custom, normalized_prefs, rationale, content_skill_hint


@router.get("", response_model=dict[str, list[RunSummary]])
def list_runs(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    rows = db.scalars(
        select(Run).where(Run.project_id == project_id).order_by(Run.created_at.desc())
    ).all()
    return {
        "items": [
            {
                "id": r.id,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "instruction": r.instruction[:200] + ("…" if len(r.instruction) > 200 else ""),
                "tokens_input": r.tokens_input,
                "tokens_output": r.tokens_output,
                "tokens_cache_read": r.tokens_cache_read,
                "tokens_cache_creation": r.tokens_cache_creation,
                "cost_usd": r.cost_usd,
            }
            for r in rows
        ]
    }


# In-flight run states surfaced by the agentops health endpoint.
_ACTIVE_RUN_STATES = ("approved", "running", "plan_ready", "plan_blocked")


@router.get("/{project_id}/active")
def list_active_runs(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """AgentOps health view: in-flight runs with staleness so an operator can tell a hung run
    from one merely awaiting approval or queued behind a busy worker.

    state: working | hung | awaiting_approval | blocked | queued.
    """
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    rows = db.scalars(
        select(Run)
        .where(Run.project_id == project_id, Run.status.in_(_ACTIVE_RUN_STATES))
        .order_by(Run.created_at.desc())
    ).all()
    run_ids = [r.id for r in rows]
    latest_event: dict[str, tuple[datetime, str]] = {}
    if run_ids:
        latest_ids = (
            select(func.max(RunEvent.id).label("max_id"))
            .where(RunEvent.run_id.in_(run_ids))
            .group_by(RunEvent.run_id)
            .subquery()
        )
        for rid, created_at, et in db.execute(
            select(RunEvent.run_id, RunEvent.created_at, RunEvent.event_type).join(
                latest_ids, RunEvent.id == latest_ids.c.max_id
            )
        ).all():
            latest_event[rid] = (created_at, et)
    now = utcnow()
    timeout_sec = int(getattr(settings, "run_stuck_timeout_sec", 0) or 0)
    items = []
    for r in rows:
        ev = latest_event.get(r.id)
        last_at = ev[0] if ev else (r.approved_at or r.created_at)
        secs = (now - last_at).total_seconds() if last_at else None
        stale = bool(r.status == "running" and timeout_sec > 0 and secs is not None and secs > timeout_sec)
        if r.status == "running":
            state = "hung" if stale else "working"
        elif r.status == "plan_ready":
            state = "awaiting_approval"
        elif r.status == "plan_blocked":
            state = "blocked"
        else:  # approved → admitted but not yet executing
            state = "queued"
        live = get_live_usage(r.id) or {}
        items.append(
            {
                "id": r.id,
                "status": r.status,
                "state": state,
                "stale": stale,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "approved_at": r.approved_at.isoformat() if r.approved_at else None,
                "latest_event_at": last_at.isoformat() if last_at else None,
                "latest_event_type": ev[1] if ev else None,
                "seconds_since_last_event": int(secs) if secs is not None else None,
                "instruction": r.instruction[:200] + ("…" if len(r.instruction) > 200 else ""),
                "tokens_input": live.get("input_tokens", r.tokens_input),
                "tokens_output": live.get("output_tokens", r.tokens_output),
                "cost_usd": r.cost_usd,
            }
        )
    return {"project_id": project_id, "stuck_timeout_sec": timeout_sec, "items": items}


@router.delete("/{project_id}")
def clear_runs(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    run_ids = db.scalars(select(Run.id).where(Run.project_id == project_id)).all()
    if not run_ids:
        return {"project_id": project_id, "deleted_runs": 0}

    db.execute(delete(RunEvent).where(RunEvent.run_id.in_(run_ids)))
    db.execute(delete(MemoryEvent).where(MemoryEvent.run_id.in_(run_ids)))
    db.execute(delete(ScheduledTaskRun).where(ScheduledTaskRun.run_id.in_(run_ids)))
    deleted_runs = db.execute(delete(Run).where(Run.id.in_(run_ids))).rowcount or 0
    db.commit()

    runs_dir = workspace_path(project_id) / "runs"
    for run_id in run_ids:
        run_dir = runs_dir / run_id
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)
    return {"project_id": project_id, "deleted_runs": int(deleted_runs)}


@router.delete("/{project_id}/{run_id}")
def delete_run(
    project_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    db.execute(delete(RunEvent).where(RunEvent.run_id == run_id))
    db.execute(delete(MemoryEvent).where(MemoryEvent.run_id == run_id))
    db.execute(delete(ScheduledTaskRun).where(ScheduledTaskRun.run_id == run_id))
    db.delete(run)
    db.commit()

    run_dir = workspace_path(project_id) / "runs" / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir, ignore_errors=True)
    return {"project_id": project_id, "run_id": run_id, "deleted": True}


@router.post("/recommend-output-types")
@limiter.limit(_run_recommend_rate_limit)
def recommend_output_types(
    request: Request,
    body: RecommendOutputTypesRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(body.project_id, {"Owner", "Editor", "Viewer"}, user, db)
    available_output_types = [
        item
        for item in _load_output_types()
        if isinstance(item, dict) and isinstance(item.get("output_type_id"), str)
    ]
    template_ids, custom_output_types, output_type_representations, rationale, _skill_hint = _recommend_output_types(
        body.instruction, available_output_types
    )
    return {
        "project_id": body.project_id,
        "template_output_types": template_ids,
        "custom_output_types": custom_output_types,
        "output_type_representations": output_type_representations,
        "rationale": rationale,
    }


@router.post("")
@limiter.limit(_run_create_rate_limit)
def start_run(
    request: Request,
    body: CreateRunRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    # region agent log
    _session_debug_log(
        run_id=None,
        hypothesis_id="H6",
        location="runs.py:start_run:entry",
        message="start_run endpoint entered",
        data={
            "project_id": body.project_id,
            "requested_output_types": list(body.output_types or []),
            "instruction_chars": len(str(body.instruction or "")),
        },
    )
    # endregion
    require_project_role(body.project_id, {"Owner", "Editor"}, user, db)
    confirmed_plan = _load_confirmed_plan(
        project_id=body.project_id,
        user_id=user.id,
        conversation_id=body.conversation_id,
        plan_hash=body.plan_hash,
        db=db,
    )
    available_output_types = [
        item
        for item in _load_output_types()
        if isinstance(item, dict) and isinstance(item.get("output_type_id"), str)
    ]
    if not body.output_types:
        body.output_types = [str(x) for x in confirmed_plan.get("template_output_types") or [] if str(x).strip()]
    if not body.output_types:
        inferred_types, inferred_custom, inferred_reps, inferred_rationale, _hint = _infer_output_types_for_confirmation(
            instruction=str(body.instruction or confirmed_plan.get("instruction") or ""),
            available_output_types=available_output_types,
        )
        raise HTTPException(
            status_code=400,
            detail=_detail(
                "output_selection_required",
                "Select at least one output type before creating a run.",
                inferred_template_output_types=inferred_types,
                inferred_custom_output_types=inferred_custom,
                inferred_output_type_representations=inferred_reps,
                inferred_rationale=inferred_rationale,
            ),
        )
    allowed = {
        str(item.get("output_type_id")) for item in available_output_types
    }
    # region agent log
    _debug_log(
        "H1",
        "runs.py:start_run:allowed",
        "Allowed output type ids loaded",
        {"project_id": body.project_id, "allowed_output_types": sorted(list(allowed)), "requested_output_types": body.output_types},
    )
    # endregion
    invalid = [output_type for output_type in body.output_types if output_type not in allowed]
    if invalid:
        # region agent log
        _debug_log(
            "H2",
            "runs.py:start_run:invalid",
            "Run rejected due to invalid output types",
            {"project_id": body.project_id, "invalid_output_types": invalid, "requested_output_types": body.output_types},
        )
        # endregion
        raise HTTPException(status_code=400, detail=f"Invalid output_types: {', '.join(invalid)}")
    if not body.custom_output_types:
        body.custom_output_types = [str(x) for x in confirmed_plan.get("custom_output_types") or [] if str(x).strip()]
    if not body.output_type_representations:
        body.output_type_representations = {
            str(k): str(v) for k, v in (confirmed_plan.get("output_type_representations") or {}).items()
        }
    if (body.instruction or "").strip() == "Create deliverables":
        body.instruction = str(confirmed_plan.get("instruction") or body.instruction)
    custom_output_types = _normalize_custom_output_types(body.custom_output_types)
    output_type_representations = _normalize_output_type_representations(body.output_type_representations)
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    # region agent log
    _session_debug_log(
        run_id=run_id,
        hypothesis_id="H6",
        location="runs.py:start_run:run_id_assigned",
        message="run_id created in start_run",
        data={"project_id": body.project_id, "output_types": list(body.output_types or [])},
    )
    # endregion
    plan = _build_plan_payload(
        project_id=body.project_id,
        instruction=body.instruction,
        output_types=body.output_types,
        custom_output_types=custom_output_types,
        output_type_representations=output_type_representations,
        content_skill_targets=confirmed_plan.get("content_skill_targets")
        if isinstance(confirmed_plan.get("content_skill_targets"), dict)
        else {},
        regeneration_directive=str(confirmed_plan.get("regeneration_directive") or ""),
    )
    plan = dict(plan)
    sel = confirmed_plan.get("selected_strategy")
    if isinstance(sel, dict) and sel.get("option_id"):
        plan["selected_strategy"] = sel
    deck_outline = confirmed_plan.get("deck_outline_preview")
    if isinstance(deck_outline, dict) and deck_outline.get("slides"):
        plan["deck_outline_preview"] = deck_outline
    document_outline = confirmed_plan.get("document_outline_preview")
    if isinstance(document_outline, dict) and document_outline.get("sections"):
        plan["document_outline_preview"] = document_outline
    wiki_refs = confirmed_plan.get("wiki_context_refs")
    if isinstance(wiki_refs, list) and wiki_refs:
        plan["wiki_context_refs"] = [str(r).strip() for r in wiki_refs if str(r).strip()][:20]
    if body.conversation_id and str(body.conversation_id).strip():
        plan["conversation_id"] = str(body.conversation_id).strip()
    if body.plan_hash and str(body.plan_hash).strip():
        plan["plan_hash"] = str(body.plan_hash).strip()
    preflight = evaluate_permission_pipeline(
        run_status="plan_ready",
        has_approval=True,
        requested_outputs=list(body.output_types or []),
        workspace_ready=bool(workspace_path(body.project_id).exists()),
        classifier_score=1.0,
        classifier_threshold=float(settings.policy_classifier_threshold),
        enforce_policy=bool(settings.policy_enforce_enabled),
        plan_payload=plan,
        include_human_gate=False,
        agentic_loop_enabled=bool(settings.coordinator_agentic_loop_enabled),
    )
    blocked = [d for d in preflight if not d.allowed]
    initial_status = "plan_blocked" if blocked else "plan_ready"
    run = Run(
        id=run_id,
        project_id=body.project_id,
        status=initial_status,
        output_types=json.dumps(body.output_types),
        instruction=body.instruction,
        plan_payload=json.dumps(plan),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    append_run_event(db, run.id, "plan_ready" if initial_status == "plan_ready" else "plan_blocked", plan)
    for d in preflight:
        append_run_event(
            db,
            run.id,
            "permission_stage",
            {"stage": d.stage, "allowed": d.allowed, "code": d.code, "reason": d.reason, "metadata": d.metadata or {}},
        )
    if initial_status == "plan_ready":
        append_run_event(db, run.id, "step", {"status": "awaiting_hitl_approval"})
    else:
        first_block = blocked[0]
        append_run_event(
            db,
            run.id,
            "step",
            {"status": "plan_blocked", "blocked_stage": first_block.stage, "blocked_reason": first_block.reason, "blocked_code": first_block.code},
        )
    append_memory_event(
        db,
        project_id=body.project_id,
        run_id=run.id,
        event_type="user_intent_updated",
        payload_obj={"summary": body.instruction[:400]},
    )
    swarm_instr = persist_instruction_broadcast_swarm_event_payload(
        db,
        project_id=body.project_id,
        run_id=run.id,
        instruction=body.instruction,
    )
    if swarm_instr:
        append_run_event(db, run.id, "swarm_message", swarm_instr)
    db.commit()
    # region agent log
    _debug_log(
        "H3",
        "runs.py:start_run:created",
        "Run created with output_types",
        {
            "project_id": body.project_id,
            "run_id": run.id,
            "output_types": body.output_types,
            "custom_output_types": custom_output_types,
            "output_type_representations": output_type_representations,
        },
    )
    # endregion
    return {"run_id": run.id, "project_id": run.project_id, "status": run.status, "plan": plan}


@router.post("/{project_id}/{run_id}/approve")
@limiter.limit(_run_approve_rate_limit)
def approve_run(
    request: Request,
    project_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    admission = admission_status(project_id, user_id=user.id)
    if not admission.get("allowed", False):
        retry_after = str(int(admission.get("retry_after_sec") or 5))
        raise HTTPException(
            status_code=429,
            detail={
                "message": "Run admission limit reached. Retry later.",
                "admission": admission,
            },
            headers={
                "Retry-After": retry_after,
                "X-Admission-Project-Limit": str(admission.get("project_limit", "")),
                "X-Admission-Global-Limit": str(admission.get("global_limit", "")),
                "X-Admission-User-Limit": str(admission.get("user_limit", "")),
                "X-Admission-Queue-Depth": str(admission.get("queue_depth", "")),
            },
        )
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "plan_ready":
        raise HTTPException(status_code=409, detail="Run is not awaiting approval")
    run.status = "approved"
    run.approved_by = user.id
    run.approved_at = datetime.now(IST).replace(tzinfo=None)
    db.commit()
    append_run_event(
        db,
        run_id,
        "step",
        {"status": "plan_approved", "approved_by": user.email},
    )
    db.commit()
    _ensure_run_enqueued(project_id, run_id, context="approve_run")
    return {"run_id": run.id, "status": run.status, "approved_by": user.email}


@router.patch("/{project_id}/{run_id}/plan")
def update_run_plan(
    project_id: str,
    run_id: str,
    body: UpdatePlanRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != "plan_ready":
        raise HTTPException(status_code=409, detail="Run is not awaiting plan edits")

    if not body.output_types:
        raise HTTPException(status_code=400, detail="output_types must not be empty")
    allowed = {
        str(item.get("output_type_id"))
        for item in _load_output_types()
        if isinstance(item, dict) and isinstance(item.get("output_type_id"), str)
    }
    invalid = [output_type for output_type in body.output_types if output_type not in allowed]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid output_types: {', '.join(invalid)}")
    custom_output_types = _normalize_custom_output_types(body.custom_output_types)
    output_type_representations = _normalize_output_type_representations(body.output_type_representations)
    run.instruction = body.instruction
    run.output_types = json.dumps(list(dict.fromkeys(body.output_types)))
    try:
        existing_plan = json.loads(run.plan_payload) if run.plan_payload else {}
        if not isinstance(existing_plan, dict):
            existing_plan = {}
    except Exception:
        existing_plan = {}

    plan = dict(
        _build_plan_payload(
            project_id=project_id,
            instruction=body.instruction,
            output_types=list(dict.fromkeys(body.output_types)),
            custom_output_types=custom_output_types,
            output_type_representations=output_type_representations,
            content_skill_targets=existing_plan.get("content_skill_targets")
            if isinstance(existing_plan.get("content_skill_targets"), dict)
            else {},
            regeneration_directive=str(existing_plan.get("regeneration_directive") or ""),
        )
    )
    for _key in ("conversation_id", "plan_hash"):
        _v = existing_plan.get(_key)
        if isinstance(_v, str) and _v.strip():
            plan[_key] = _v.strip()
    _prev_ss = existing_plan.get("selected_strategy")
    if isinstance(_prev_ss, dict) and _prev_ss.get("option_id"):
        plan["selected_strategy"] = _prev_ss
    run.plan_payload = json.dumps(plan)
    run.approved_by = None
    run.approved_at = None
    db.commit()

    append_run_event(db, run_id, "plan_ready", plan)
    append_run_event(db, run_id, "step", {"status": "awaiting_hitl_approval"})
    append_memory_event(
        db,
        project_id=project_id,
        run_id=run_id,
        event_type="user_intent_updated",
        payload_obj={"summary": body.instruction[:400]},
    )
    db.commit()

    return {"run_id": run.id, "status": run.status, "plan": plan}


@router.get("/{project_id}/{run_id}/usage")
def get_run_usage(
    project_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return live token usage for an executing run, or final values from the DB."""
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    from app.services.run_budget import get_live_usage
    from app.services.llm_pricing import calculate_run_cost_usd

    live = get_live_usage(run_id)
    if live is not None:
        cost = calculate_run_cost_usd(**live)
        return {"run_id": run_id, "live": True, **live, "cost_usd": cost}

    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "run_id": run_id,
        "live": False,
        "input_tokens": run.tokens_input or 0,
        "output_tokens": run.tokens_output or 0,
        "cache_read_tokens": run.tokens_cache_read or 0,
        "cache_creation_tokens": run.tokens_cache_creation or 0,
        "cost_usd": run.cost_usd,
    }


@router.get("/{project_id}/{run_id}/events")
def list_run_events(
    project_id: str,
    run_id: str,
    after_event_id: int = Query(0, ge=0),
    user: User = Depends(get_current_user_sse),
    db: Session = Depends(get_db),
) -> dict:
    """Polling fallback / debugging: persisted events after id (Bearer or ?token= like /stream)."""
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    rows = db.scalars(
        select(RunEvent)
        .where(RunEvent.run_id == run_id, RunEvent.id > after_event_id)
        .order_by(RunEvent.id)
    ).all()
    plan = None
    if run.plan_payload:
        try:
            plan = json.loads(run.plan_payload)
        except json.JSONDecodeError:
            plan = run.plan_payload

    return {
        "run_id": run_id,
        "status": run.status,
        "plan": plan,
        "items": [{"id": e.id, "event_type": e.event_type, "payload": e.payload_json} for e in rows],
    }


@router.get("/{project_id}/{run_id}/context_trace")
def get_run_context_trace(
    project_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return latest persisted context trace payload for this run."""
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    rows = db.scalars(
        select(RunEvent)
        .where(RunEvent.run_id == run_id, RunEvent.event_type == "context_trace")
        .order_by(RunEvent.id.desc())
        .limit(1)
    ).all()
    if not rows:
        return {"run_id": run_id, "context_trace": None}
    return {"run_id": run_id, "context_trace": rows[0].payload_json}


@router.get("/{project_id}/{run_id}/tasks")
def list_run_tasks(
    project_id: str,
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    rows = db.scalars(select(RunTask).where(RunTask.run_id == run_id).order_by(RunTask.created_at.asc())).all()
    return {"run_id": run_id, "project_id": project_id, "items": [serialize_run_task(r) for r in rows]}


@router.post("/{project_id}/{run_id}/tasks/{task_id}/actions")
def apply_run_task_action(
    project_id: str,
    run_id: str,
    task_id: str,
    body: RunTaskActionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    task = db.scalar(select(RunTask).where(RunTask.id == task_id, RunTask.run_id == run_id))
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    action = str(body.action or "").strip().lower()
    reason = (body.reason or "").strip()
    if action == "retry":
        if task.status != "failed":
            raise HTTPException(status_code=409, detail="Only failed tasks can be retried")
        task.status = "queued"
        task.retry_count = int(task.retry_count or 0) + 1
        task.completed_at = None
        task.duration_ms = None
        append_run_event(
            db,
            run_id,
            "task.retrying",
            {"task_id": task.id, "title": task.title, "phase": task.phase, "retry_count": task.retry_count, "reason": reason},
        )
    elif action == "skip":
        if task.status in {"completed", "skipped"}:
            raise HTTPException(status_code=409, detail="Task is already terminal")
        task.status = "skipped"
        task.completed_at = datetime.now(IST).replace(tzinfo=None)
        append_run_event(db, run_id, "task.skipped", {"task_id": task.id, "title": task.title, "phase": task.phase, "reason": reason})
    elif action == "approve":
        task.requires_approval = False
        append_run_event(db, run_id, "task.intervention_applied", {"task_id": task.id, "title": task.title, "phase": task.phase, "action": "approve", "reason": reason})
    elif action == "modify":
        payload = {"feedback": reason, "task_id": task.id, "title": task.title, "phase": task.phase}
        task.output_json = json.dumps({"user_feedback": reason})
        append_run_event(db, run_id, "task.intervention_requested", payload)
        append_run_event(db, run_id, "task.intervention_applied", {"action": "modify", **payload})
    else:
        raise HTTPException(status_code=400, detail="Unsupported action")
    task.updated_at = datetime.now(IST).replace(tzinfo=None)
    db.commit()
    return {"run_id": run_id, "project_id": project_id, "task": serialize_run_task(task)}


@router.get("/{project_id}/{run_id}/stream")
def stream_run(
    project_id: str,
    run_id: str,
    after_event_id: int = Query(0, ge=0, description="Resume SSE after this persisted event id"),
    user: User = Depends(get_current_user_sse),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if after_event_id > 0:
        increment("sse_replay_continuity_check_total")

    async def event_stream():
        # Async generator: runs in the event loop (not a thread), so 500 concurrent
        # SSE streams do not consume 500 threads. DB calls are dispatched via
        # asyncio.to_thread so they don't block other streams during polling.
        pubsub = None
        if settings.run_queue_backend == "redis":
            def _setup_pubsub():
                try:
                    pool = _get_or_create_sse_redis_pool()
                    if pool is None:
                        return None
                    _rc = redis.Redis(connection_pool=pool)
                    _rc.ping()
                    _ps = _rc.pubsub(ignore_subscribe_messages=True)
                    _ps.subscribe(f"{settings.run_events_channel_prefix}:{run_id}")
                    return _ps
                except Exception as exc:
                    _log.warning("%s: suppressed error: %s", '_setup_pubsub', exc)
                    return None
            pubsub = await asyncio.to_thread(_setup_pubsub)

        # Initial DB check: verify run exists, emit legacy plan_ready burst if no events yet.
        def _initial_check():
            _sess = SessionLocal()
            try:
                _row = _sess.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
                if not _row:
                    return None
                if after_event_id == 0:
                    _has_events = (
                        _sess.scalar(select(RunEvent.id).where(RunEvent.run_id == run_id).limit(1))
                        is not None
                    )
                    if not _has_events and _row.status == "plan_ready":
                        return ("plan_ready_no_events", _row.plan_payload)
                if _row.status == "approved":
                    maybe_start_run_execution(project_id, run_id)
                return ("stream", _row.status)
            finally:
                _sess.close()

        init_result = await asyncio.to_thread(_initial_check)
        if init_result is None:
            return
        if init_result[0] == "plan_ready_no_events":
            yield f"event: plan_ready\ndata: {init_result[1]}\n\n"
            yield 'event: step\ndata: {"status": "awaiting_hitl_approval"}\n\n'
            return

        last_id = after_event_id
        deadline = time.monotonic() + 600.0
        idle_cycles = 0
        try:
            while time.monotonic() < deadline:
                # Fast path: Redis pub/sub delivers events without a DB round-trip.
                if pubsub is not None:
                    try:
                        ps_msg = await asyncio.to_thread(pubsub.get_message, timeout=0.1)
                        if ps_msg and ps_msg.get("type") == "message":
                            raw = ps_msg.get("data")
                            if isinstance(raw, str):
                                ps_payload = json.loads(raw)
                                ev_id = int(ps_payload.get("id", 0) or 0)
                                if ev_id > last_id:
                                    last_id = ev_id
                                    yield (
                                        f"id: {ev_id}\n"
                                        f"event: {ps_payload.get('event_type', 'step')}\n"
                                        f"data: {ps_payload.get('payload', '{}')}\n\n"
                                    )
                                    if ps_payload.get("event_type") in ("done", "failed"):
                                        return
                    except Exception:
                        pubsub = None

                # DB poll: authoritative fallback and run-status termination check.
                # One session per poll cycle, closed immediately after use.
                def _poll_db(lid=last_id):
                    _sess = SessionLocal()
                    try:
                        _row = _sess.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
                        if not _row:
                            return None, []
                        _events = list(
                            _sess.scalars(
                                select(RunEvent)
                                .where(RunEvent.run_id == run_id, RunEvent.id > lid)
                                .order_by(RunEvent.id)
                            ).all()
                        )
                        return _row.status, _events
                    finally:
                        _sess.close()

                row_status, events = await asyncio.to_thread(_poll_db)
                if row_status is None:
                    return
                for ev in events:
                    last_id = ev.id
                    yield f"id: {ev.id}\nevent: {ev.event_type}\ndata: {ev.payload}\n\n"
                    if ev.event_type in ("done", "failed"):
                        return
                if row_status in ("review_ready", "done", "failed") and not events:
                    return
                # Stay connected while awaiting HITL: closing here caused immediate EventSource
                # reconnect loops and false "stream error" + poll-only UX in the browser.
                idle_cycles = 0 if events else min(idle_cycles + 1, 20)
                sleep_sec = 0.5 if idle_cycles < 8 else 1.5
                await asyncio.sleep(sleep_sec)
        finally:
            if pubsub is not None:
                with contextlib.suppress(Exception):
                    pubsub.close()  # returns connection to the shared pool

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{project_id}/queue/dead-letter")
def list_queue_dead_letter(
    project_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
    return {"project_id": project_id, "items": list_dead_letter_items(project_id=project_id, limit=limit)}


@router.post("/{project_id}/queue/dead-letter/replay")
def replay_queue_dead_letter(
    project_id: str,
    body: ReplayDeadLetterRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    item = replay_dead_letter_item(body.item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Dead-letter item not found")
    if item.get("project_id") not in {None, project_id}:
        raise HTTPException(status_code=400, detail="Dead-letter item does not belong to this project")
    if item.get("status") != "replayed":
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Dead-letter item is not replayable",
                "item": item,
            },
        )
    return {"project_id": project_id, "item": item}


@router.post("/{project_id}/queue/dead-letter/reset-attempts")
def reset_queue_dead_letter_attempts(
    project_id: str,
    body: ResetDeadLetterRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner"}, user, db)
    item = reset_dead_letter_attempts(body.item_id, actor=user.email)
    if not item:
        raise HTTPException(status_code=404, detail="Dead-letter item not found")
    if item.get("project_id") not in {None, project_id}:
        raise HTTPException(status_code=400, detail="Dead-letter item does not belong to this project")
    return {"project_id": project_id, "item": item}


@router.post("/{project_id}/{run_id}/final-approve")
def final_approve_run_deliverable(
    project_id: str,
    run_id: str,
    body: FinalApproveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in {"review_ready", "done"}:
        raise HTTPException(status_code=409, detail="Run is not awaiting final deliverable approval")

    run_dir = workspace_path(project_id) / "runs" / run_id

    # Content-level HITL: every unsupported numeric claim must be accepted or rejected.
    from app.services.evidence_claims import (
        load_claims_dossier,
        pending_unsupported_count,
        write_claims_dossier,
    )

    claims_dossier = load_claims_dossier(run_dir)
    if not claims_dossier.get("claims"):
        qa = {}
        qa_path = run_dir / "pptx_render_quality.json"
        if qa_path.is_file():
            try:
                qa = json.loads(qa_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                qa = {}
        if isinstance(qa, dict) and isinstance(qa.get("evidence"), dict):
            claims_dossier = write_claims_dossier(run_dir, qa["evidence"], source="pptx")
    pending = pending_unsupported_count(claims_dossier)
    if pending > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    f"{pending} unsupported numeric claim(s) still need accept/reject "
                    "before final approval."
                ),
                "pending_claims": pending,
                "summary": claims_dossier.get("summary"),
            },
        )

    visual_qa_path = run_dir / "visual_qa_report.json"
    if not visual_qa_path.exists():
        raise HTTPException(status_code=409, detail="Visual QA report is not available yet")
    try:
        visual_qa_report = json.loads(visual_qa_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Visual QA report is invalid") from exc
    vstatus = str(visual_qa_report.get("status") or "").lower()
    if vstatus != "pass":
        raw_f = visual_qa_report.get("findings") or []
        findings_list: list[str] = []
        if isinstance(raw_f, list):
            findings_list = [str(x).strip() for x in raw_f if str(x).strip()][:30]
        summary = str(visual_qa_report.get("summary") or "").strip()
        msg = "Visual QA did not pass. Please refine deliverables first."
        if summary:
            msg = f"{msg} {summary}"
        if findings_list:
            msg = f"{msg} Details: " + "; ".join(findings_list[:10])
            if len(findings_list) > 10:
                msg += f" (+{len(findings_list) - 10} more)"
        raise HTTPException(
            status_code=409,
            detail={
                "message": msg,
                "status": vstatus,
                "summary": visual_qa_report.get("summary"),
                "findings": findings_list,
            },
        )

    guardrail_path = run_dir / "guardrail_report.json"
    if not guardrail_path.exists():
        raise HTTPException(status_code=409, detail="Guardrail report is not available yet")
    try:
        guardrail_report = json.loads(guardrail_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Guardrail report is invalid") from exc
    append_memory_event(
        db,
        project_id=project_id,
        run_id=run_id,
        event_type="guardrail_outcome",
        payload_obj={
            "summary": str(guardrail_report.get("status", "unknown")),
            "notes": (body.notes or "").strip()[:500],
        },
    )
    if guardrail_report.get("status") == "pass":
        run.status = "done"
        run.error_message = None
        append_run_event(db, run_id, "done", {"status": "done"})
    else:
        run.status = "review_ready"
    db.commit()
    return {
        "run_id": run_id,
        "status": run.status,
        "guardrail_status": guardrail_report.get("status"),
        "guardrail_report": guardrail_report,
    }


@router.post("/{project_id}/{run_id}/control")
def control_run(
    project_id: str,
    run_id: str,
    body: ControlRunRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    action = str(body.action or "").strip().lower()
    if action not in {"pause", "resume", "stop", "abort"}:
        raise HTTPException(status_code=400, detail="Invalid action; expected pause|resume|stop|abort")

    if action == "pause":
        if run.status != "approved":
            raise HTTPException(status_code=409, detail="Pause is allowed only before execution starts")
        run.status = "plan_ready"
        run.pause_requested = True
        run.resume_requested = False
        run.abort_requested = False
        try:
            pp = json.loads(run.plan_payload) if run.plan_payload else {}
        except Exception:
            pp = {}
        if not isinstance(pp, dict):
            pp = {}
        cs = pp.get("control_state") if isinstance(pp.get("control_state"), dict) else {}
        cs.update({"pause_requested": True, "resume_requested": False, "abort_requested": False})
        pp["control_state"] = cs
        run.plan_payload = json.dumps(pp)
        db.commit()
        append_run_event(db, run_id, "run_paused", lifecycle_event(run_id=run_id, event_type="run_paused", action="pause", actor=user.id))
        db.commit()
        return {"run_id": run_id, "status": run.status, "action": action}

    if action == "resume":
        if run.status != "plan_ready":
            raise HTTPException(status_code=409, detail="Resume requires a paused plan_ready run")
        run.status = "approved"
        run.pause_requested = False
        run.resume_requested = True
        run.abort_requested = False
        try:
            pp = json.loads(run.plan_payload) if run.plan_payload else {}
        except Exception:
            pp = {}
        if not isinstance(pp, dict):
            pp = {}
        cs = pp.get("control_state") if isinstance(pp.get("control_state"), dict) else {}
        cs.update({"pause_requested": False, "resume_requested": True, "abort_requested": False})
        pp["control_state"] = cs
        run.plan_payload = json.dumps(pp)
        db.commit()
        append_run_event(db, run_id, "run_resumed", lifecycle_event(run_id=run_id, event_type="run_resumed", action="resume", actor=user.id))
        db.commit()
        _ensure_run_enqueued(project_id, run_id, context="control_run resume")
        return {"run_id": run_id, "status": run.status, "action": action}

    if run.status in {"done", "failed"}:
        raise HTTPException(status_code=409, detail="Run is already terminal")
    run.status = "failed"
    run.error_message = "Stopped by user request."
    run.pause_requested = False
    run.resume_requested = False
    run.abort_requested = True
    try:
        pp = json.loads(run.plan_payload) if run.plan_payload else {}
    except Exception:
        pp = {}
    if not isinstance(pp, dict):
        pp = {}
    cs = pp.get("control_state") if isinstance(pp.get("control_state"), dict) else {}
    cs.update({"pause_requested": False, "resume_requested": False, "abort_requested": True})
    pp["control_state"] = cs
    run.plan_payload = json.dumps(pp)
    db.commit()
    append_run_event(
        db,
        run_id,
        "run_aborted" if action == "abort" else "failed",
        lifecycle_event(run_id=run_id, event_type="run_aborted", action="abort", actor=user.id)
        if action == "abort"
        else {"error": "Stopped by user request."},
    )
    db.commit()
    return {"run_id": run_id, "status": run.status, "action": action}


@router.post("/{project_id}/{run_id}/slides/{slide_index}/regenerate")
@limiter.limit(_run_regenerate_rate_limit)
def regenerate_run_slide(
    request: Request,
    project_id: str,
    run_id: str,
    slide_index: int,
    body: RegenerateSlideRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if slide_index < 1:
        raise HTTPException(status_code=400, detail="slide_index must be >= 1")
    instruction = str(body.instruction or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction is required")
    scope = str(body.scope or "slide").strip().lower()
    if scope not in {"slide", "element"}:
        raise HTTPException(status_code=400, detail="scope must be 'slide' or 'element'")
    element_path = str(body.element_path or "").strip()
    if scope == "element" and not element_path:
        raise HTTPException(status_code=400, detail="element_path is required when scope='element'")
    try:
        output_types = json.loads(run.output_types or "[]")
    except Exception:
        output_types = []
    if "pptx" not in output_types:
        raise HTTPException(status_code=409, detail="Run does not include pptx output")
    run_dir = workspace_path(project_id) / "runs" / run_id
    slides_path = run_dir / "pptx_slides.json"
    if not slides_path.exists():
        raise HTTPException(status_code=409, detail="pptx_slides.json is not available for this run")
    try:
        prior_slides = json.loads(slides_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Could not read pptx slide state") from exc
    if not isinstance(prior_slides, list) or not prior_slides:
        raise HTTPException(status_code=409, detail="pptx slide state is empty")
    if slide_index > len(prior_slides):
        raise HTTPException(status_code=400, detail=f"slide_index out of range (1-{len(prior_slides)})")
    try:
        plan_payload = json.loads(run.plan_payload) if run.plan_payload else {}
    except Exception:
        plan_payload = {}
    if not isinstance(plan_payload, dict):
        plan_payload = {}
    feedback_instruction = f"Slide {slide_index}: {instruction}"
    if scope == "element" and element_path:
        feedback_instruction = (
            f"Slide {slide_index}, element '{element_path}': {instruction}. "
            "Update only this element and preserve all other slide content/layout."
        )
    feedback_entry = {
        "slide_index": slide_index,
        "instruction": feedback_instruction,
    }
    if element_path:
        feedback_entry["element_path"] = element_path
    plan_payload["prior_pptx_slides"] = prior_slides
    plan_payload["pptx_visual_feedback"] = [feedback_entry]
    inline_comments = plan_payload.get("pptx_inline_comments")
    if not isinstance(inline_comments, list):
        inline_comments = []
    inline_comments.append(
        {
            "slide_index": slide_index,
            "scope": scope,
            "element_path": element_path or None,
            "instruction": instruction[:1000],
            "requested_by": str(user.id),
            "requested_at": datetime.now(IST).isoformat() + "Z",
        }
    )
    plan_payload["pptx_inline_comments"] = inline_comments[-200:]
    prev_regen = str(plan_payload.get("regeneration_directive") or "").strip()
    if scope == "element" and element_path:
        regen_line = (
            f"Targeted element regeneration requested for slide {slide_index} at '{element_path}'. "
            "Preserve all other elements and slides unchanged."
        )
    else:
        regen_line = f"Targeted slide regeneration requested for slide {slide_index}. Preserve all other slides unchanged."
    plan_payload["regeneration_directive"] = f"{prev_regen}\n\n{regen_line}".strip() if prev_regen else regen_line
    run.plan_payload = json.dumps(plan_payload)
    run.status = "approved"
    run.error_message = f"Targeted slide regeneration queued for slide {slide_index}."
    db.commit()
    append_run_event(
        db,
        run_id,
        "slide_regeneration_requested",
        {
            "project_id": project_id,
            "run_id": run_id,
            "slide_index": slide_index,
            "scope": scope,
            "element_path": element_path or None,
            "instruction": instruction[:1000],
            "status": "approved",
        },
    )
    db.commit()
    _ensure_run_enqueued(project_id, run_id, context="regenerate_run_slide")
    return {
        "project_id": project_id,
        "run_id": run_id,
        "slide_index": slide_index,
        "scope": scope,
        "element_path": element_path or None,
        "queued": True,
        "status": "approved",
    }


@router.patch("/{project_id}/{run_id}/slides/{slide_index}/elements")
def patch_run_slide_element(
    project_id: str,
    run_id: str,
    slide_index: int,
    body: PatchSlideElementRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Deterministic in-place slide mutation — no LLM re-queue."""
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    element_path = str(body.element_path or "").strip()
    if not element_path:
        raise HTTPException(status_code=400, detail="element_path is required")
    if slide_index < 1:
        raise HTTPException(status_code=400, detail="slide_index must be >= 1")

    run_dir = workspace_path(project_id) / "runs" / run_id
    slides_path = run_dir / "pptx_slides.json"
    if not slides_path.is_file():
        raise HTTPException(status_code=409, detail="pptx_slides.json is not available for this run")
    try:
        prior_slides = json.loads(slides_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Could not read pptx slide state") from exc
    if not isinstance(prior_slides, list) or not prior_slides:
        raise HTTPException(status_code=409, detail="pptx slide state is empty")

    from app.core.pptx_slide_patch import patch_slide_element

    try:
        updated = patch_slide_element(
            prior_slides,
            slide_index,
            element_path=element_path,
            value=body.value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    slides_path.write_text(json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")

    # Re-render PPTX from mutated JSON so downloads stay in sync.
    regenerated = False
    try:
        from app.core.deliverable import DeliverableRegistry, _init_default_deliverables
        from app.services.branding_service import BrandingService

        _init_default_deliverables()
        branding = BrandingService(db).get_branding_for_run(project_id)
        process_model = {}
        pm_path = run_dir / "process_model.json"
        if pm_path.is_file():
            try:
                process_model = json.loads(pm_path.read_text(encoding="utf-8"))
            except Exception:
                process_model = {}
        payload = {
            "pptx_slides": updated,
            "process_model": process_model if isinstance(process_model, dict) else {},
            "requested_outputs": ["pptx"],
            "compaction_snapshot": {},
        }
        snap_path = run_dir / "compaction_snapshot.json"
        if snap_path.is_file():
            try:
                payload["compaction_snapshot"] = json.loads(snap_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        out = DeliverableRegistry.get("pptx").render(payload, run_dir, branding=branding)
        regenerated = out is not None
    except Exception as exc:
        logger.warning("deterministic slide patch render failed for %s: %s", run_id, exc)

    try:
        from app.services.run_events import append_run_event

        append_run_event(
            db,
            run_id,
            "slide_element_patched",
            {
                "slide_index": slide_index,
                "element_path": element_path,
                "regenerated": regenerated,
            },
        )
        db.commit()
    except Exception:
        pass

    return {
        "project_id": project_id,
        "run_id": run_id,
        "slide_index": slide_index,
        "element_path": element_path,
        "queued": False,
        "deterministic": True,
        "regenerated": regenerated,
        "pptx_slides": updated,
    }


@router.post("/{project_id}/permission/simulate")
def simulate_permission_pipeline(
    project_id: str,
    body: PermissionSimulationRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    decisions = evaluate_permission_pipeline(
        run_status=body.run_status,
        has_approval=bool(body.has_approval),
        requested_outputs=list(body.requested_outputs or []),
        workspace_ready=True,
        enforce_policy=bool(body.enforce_policy),
        plan_payload=body.plan_payload if isinstance(body.plan_payload, dict) else None,
        agentic_loop_enabled=bool(settings.coordinator_agentic_loop_enabled),
    )
    return {
        "project_id": project_id,
        "allowed": all(d.allowed for d in decisions),
        "stages": [
            {
                "stage": d.stage,
                "allowed": d.allowed,
                "code": d.code,
                "reason": d.reason,
                "metadata": d.metadata or {},
            }
            for d in decisions
        ],
    }


class HookDisableRequest(BaseModel):
    hook_name: str
    reason: str | None = None


@router.get("/{project_id}/hooks")
def list_hooks(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    sync_disabled_hooks_from_db(db, project_id=project_id)
    hooks = list_registered_hooks()
    visible = [h for h in hooks if h.get("project_id") in {None, project_id}]
    return {"project_id": project_id, "hooks": visible}


@router.post("/{project_id}/hooks/disable")
def disable_hook_endpoint(
    project_id: str,
    body: HookDisableRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(project_id, {"Owner", "Editor"}, user, db)
    hook_name = str(body.hook_name or "").strip()
    if not hook_name:
        raise HTTPException(status_code=400, detail="hook_name is required")
    upsert_hook_control(
        db,
        hook_name=hook_name,
        disabled=True,
        actor=str(user.email or user.id),
        reason=(body.reason or "").strip() or None,
        project_id=project_id,
    )
    db.commit()
    disable_hook(hook_name)
    return {"project_id": project_id, "hook_name": hook_name, "disabled": True, "reason": body.reason}
