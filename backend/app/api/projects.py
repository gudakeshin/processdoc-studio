import json
import logging
import re
import shutil
import uuid
from datetime import datetime, timedelta
from app.core.tz import IST
from time import perf_counter

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.formats import _load_output_types
from app.api.runs import (
    _build_plan_payload,
    _ensure_run_enqueued,
    _normalize_custom_output_types,
    _normalize_output_type_representations,
    _recommend_output_types,
)
from app.services.permission_pipeline import evaluate_permission_pipeline
from app.services.swarm import persist_instruction_broadcast_swarm_event_payload
from app.core.auth import get_current_user, require_project_role
from app.core.config import settings
from app.core.db_checkpoints import checkpoint_scope
from app.db.models import (
    ConsentLedger,
    Conversation,
    ConversationMessage,
    DPDPRightsRequest,
    Membership,
    MemoryEvent,
    MemoryItem,
    Project,
    ProjectMemoryProfile,
    Run,
    RunEvent,
    ScheduledTask,
    ScheduledTaskRun,
    User,
    UserProjectPreference,
)
from app.db.session import get_db
from app.schemas.common import ProjectSummary
from app.services.proposal_policy import (
    derive_proposal_skill_targets,
    generate_deck_outline_preview,
    generate_document_outline_preview,
    has_proposal_intent,
    is_finance_proposal_intent,
)
from app.services.conversation_router import fallback_decision, route_turn
from app.services.conversation_state import ConversationState, load_state, save_state, stamp_router
from app.services.memory_event_service import (
    get_aggregated_profile,
    record_discovery_answer,
    record_routing_decision,
)
from app.services.retrieval import TieredContextEngine
from app.services.run_worker import append_memory_event, append_run_event, enqueue_run_execution
from app.services.storage import ensure_workspace, workspace_path

router = APIRouter()
_LOG = logging.getLogger(__name__)


def _is_contextual_followup(content: str, prior_messages: list[dict]) -> bool:
    """Check if message is a follow-up question that should be answered contextually.

    Rather than treating every message as a deliverable request, recognize when
    a user is asking a follow-up question about recent context.
    """
    lowered = (content or "").lower().strip()

    # Follow-up question patterns
    followup_patterns = [
        "what refinements",
        "which should",
        "how should",
        "what should",
        "should we",
        "which of",
        "how do we",
        "what about",
        "can we fix",
        "fix the",
        "address the",
        "resolve the",
        "improve the",
        "tell me more",
        "elaborate",
        "expand on",
        "more details",
        "more information",
    ]

    # Check if message matches follow-up patterns
    if any(pattern in lowered for pattern in followup_patterns):
        # Check if there's recent context (messages in last 3 containing findings/issues)
        recent = prior_messages[-3:] if len(prior_messages) >= 3 else prior_messages
        for msg in recent:
            msg_content = str(msg.get("content") or "").lower()
            if any(
                keyword in msg_content
                for keyword in ["found", "issue", "fail", "deficien", "structural", "refined", "fix"]
            ):
                return True

    return False


def _is_vague_instruction(content: str) -> bool:
    """Check if user message is too vague to generate a plan for.

    Returns True if the message is just a greeting or asks about capabilities
    without requesting something specific.
    """
    lowered = (content or "").lower().strip()

    # Simple greetings that don't warrant a plan
    vague_patterns = [
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "got it",
        "thanks",
        "what's up",
        "what up",
        "sup",
        "good morning",
        "good afternoon",
        "good evening",
        "good night",
    ]

    # Questions about capabilities without specific request
    capability_questions = [
        "what can you do",
        "what can i do",
        "how does this work",
        "how do i use this",
        "what is this",
        "who are you",
        "tell me about yourself",
        "help",
        "how does it work",
        "what do you do",
    ]

    # Check if message is just a vague greeting
    if lowered in vague_patterns:
        return True

    # Check if it's a capability question without specific request
    for question in capability_questions:
        if (
            lowered.startswith(question)
            and len(lowered) < 50
            and not any(
                keyword in lowered
                for keyword in ["proposal", "create", "generate", "build", "make", "send", "give me", "need", "want"]
            )
        ):
            return True

    return False


# ── Intent classification for natural conversation flow ──────────────────

# Deliverable nouns that signal the user is talking about a specific output
_DELIVERABLE_NOUNS = {
    "proposal", "deck", "presentation", "pptx", "powerpoint", "ppt",
    "document", "report", "docx", "word",
    "model", "spreadsheet", "excel", "xlsx",
    "process map", "process flow", "flowchart", "diagram",
    "sop", "standard operating procedure",
    "narrative", "brief", "memo", "analysis",
    "raci", "matrix",
}

# Verbs that signal a clear creation request (commit intent)
_COMMIT_VERBS = {
    "create", "build", "generate", "make", "draft", "write", "produce",
    "design", "prepare", "develop", "construct", "deliver",
}

# Phrases that indicate the user wants to proceed / confirm / execute
_GO_AHEAD_PHRASES = [
    "go ahead", "let's do it", "proceed", "let's build", "let's go",
    "ship it", "let's make it", "do it", "yes build", "yes create",
    "confirmed", "let's proceed", "start building", "start creating",
    "kick it off", "let's roll", "get started", "begin",
]

# Hedging / exploratory phrases that signal the user is NOT committing yet
_EXPLORATORY_PHRASES = [
    "thinking about", "considering", "what if", "should i",
    "should we", "could we", "what do you think", "what would",
    "how should", "would it be", "is it possible", "can we discuss",
    "let's discuss", "let's talk about", "i want to talk",
    "i want to discuss", "help me think", "brainstorm",
    "explore", "any suggestions", "what options", "what approach",
    "how would you", "what's the best way", "advise", "recommend",
    "your thoughts", "your opinion", "weigh in",
    "not sure", "i'm unsure", "haven't decided",
    "can you explain", "tell me about", "walk me through",
    "what are the", "which would be", "pros and cons",
]

# Simple acknowledgments (responding to agent, not requesting anything)
_ACKNOWLEDGMENT_PATTERNS = [
    "that makes sense", "makes sense", "good point", "i see", "understood",
    "interesting", "great", "nice", "perfect", "sounds good",
    "fair enough", "agree", "i agree", "right", "exactly",
    "yep", "yup", "yeah", "yes", "no", "nope",
    "cool", "awesome", "love it", "works for me",
    "hmm", "hm", "ah", "oh",
]


def _is_commit_intent(content: str) -> bool:
    """Fast pattern check: Does user clearly want to create/build a specific deliverable?

    Returns True only when there's a clear action verb + deliverable noun,
    or an explicit go-ahead phrase. Designed to catch unambiguous commit signals
    without false positives on exploratory language.
    """
    lowered = (content or "").lower().strip()
    if not lowered:
        return False

    # Explicit go-ahead phrases
    for phrase in _GO_AHEAD_PHRASES:
        if phrase in lowered:
            return True

    # Redo requests are commits (user wants something rebuilt)
    if _is_redo_followup(lowered):
        return True

    # Check for hedging language — if present, NOT a commit even if verb+noun match
    for hedge in _EXPLORATORY_PHRASES:
        if hedge in lowered:
            return False

    # Check for clear verb + noun pattern
    has_commit_verb = any(verb in lowered for verb in _COMMIT_VERBS)
    has_deliverable_noun = any(noun in lowered for noun in _DELIVERABLE_NOUNS)

    if has_commit_verb and has_deliverable_noun:
        return True

    # Strong request patterns: "I need a ...", "Give me a ...", "I want a ..."
    strong_request_starters = [
        "i need a ", "i need you to ", "give me a ", "give me the ",
        "i want a ", "i want you to ", "please create", "please build",
        "please make", "please generate", "can you create", "can you build",
        "can you make", "can you generate",
    ]
    return any(lowered.startswith(starter) and has_deliverable_noun for starter in strong_request_starters)


def _is_acknowledgment(content: str) -> bool:
    """Check if the message is a simple acknowledgment / response to agent."""
    lowered = (content or "").lower().strip()
    if not lowered:
        return False
    # Exact match or very short acknowledgments
    if lowered in _ACKNOWLEDGMENT_PATTERNS:
        return True
    # Short messages that are just acknowledgments (under 20 chars)
    if len(lowered) < 20:
        for pattern in _ACKNOWLEDGMENT_PATTERNS:
            if lowered == pattern or lowered == pattern + "!":
                return True
    return False


_EXECUTE_NOW_PATTERNS = frozenset({
    "go", "go ahead", "build it", "build it now", "draft it", "draft it now",
    "proceed", "yes proceed", "please proceed", "ship it", "make it", "do it", "do it now",
    "execute", "execute it", "run it", "start it", "start the run",
    "let's go", "lets go", "let's build", "lets build", "let's do it", "lets do it",
    "create it", "create it now", "generate it", "generate it now",
})

# Substrings that unambiguously mean "start executing" wherever they appear in the message.
_EXECUTE_NOW_SUBSTRINGS = (
    "go ahead and draft", "go ahead and build", "go ahead and create",
    "go ahead and generate", "go ahead and start", "go ahead and make",
    "please go ahead", "please draft", "please build the", "please create the",
    "please generate the", "start building", "start drafting", "start creating",
    "start generating", "begin building", "begin drafting", "begin creating",
    "kick it off", "kick off the", "get it started", "get started on",
)


def _is_execute_now_intent(content: str) -> bool:
    lowered = (content or "").lower().strip().rstrip("!.")
    if not lowered:
        return False
    if lowered in _EXECUTE_NOW_PATTERNS:
        return True
    # Allow "ok go ahead", "yes go ahead", "please proceed" etc.
    for phrase in _EXECUTE_NOW_PATTERNS:
        if len(phrase) >= 4 and lowered.endswith(phrase):
            prefix = lowered[: -len(phrase)].strip()
            if prefix in {"ok", "okay", "yes", "yeah", "yep", "sure", "please", "alright", "great"}:
                return True
    # Substring match for unambiguous execute phrases.
    return any(sub in lowered for sub in _EXECUTE_NOW_SUBSTRINGS)


def _generate_and_execute_plan(
    *,
    db: Session,
    conv: Conversation,
    pid: str,
    user: "User",
    state: "ConversationState",
    content: str,
    instruction: str,
    template_ids: list[str],
    custom_output_types: list[str],
    output_type_representations: dict[str, str],
    content_skill_hint: object,
    prior_messages: list[dict],
) -> dict:
    """Generate a plan from state context then execute immediately (no second 'go' needed)."""
    from app.core.db_checkpoints import checkpoint_scope as _cp_scope

    with _cp_scope(db, "auto_plan_and_execute", metadata={"project_id": pid, "conversation_id": conv.id}):
        state.state = "ready_to_plan"
        state.pending_questions = []
        save_state(conv, state)
        db.flush()

        content_skill_targets = _derive_content_skill_targets(
            instruction=instruction,
            template_ids=template_ids,
            prior_plan_meta=None,
            llm_skill_hint=content_skill_hint,
        )
        discovery = _normalize_discovery(state.slots if isinstance(state.slots, dict) else {})
        _persist_assistant_plan_message(
            db=db,
            conv=conv,
            content=content,
            instruction=instruction,
            template_ids=template_ids,
            custom_output_types=custom_output_types,
            output_type_representations=output_type_representations,
            rationale="User requested immediate execution",
            content_skill_targets=content_skill_targets,
            discovery=discovery,
        )
        state.state = "plan_proposed"
        save_state(conv, state)
        db.commit()

    # Read the freshly committed plan and execute it.
    fresh_messages = _serialize_messages(db, conv.id)
    fresh_plan_meta = _latest_assistant_plan_metadata(fresh_messages)
    if not fresh_plan_meta or not fresh_plan_meta.get("plan_hash"):
        return {
            "conversation_id": conv.id,
            "messages": fresh_messages,
            "open_questions": [],
            "ready_for_confirmation": False,
            "plan_hash": None,
        }
    return _execute_plan_now(
        db=db, conv=conv, pid=pid, user=user,
        plan_meta=fresh_plan_meta, state=state,
    )


def _execute_plan_now(
    *,
    db: Session,
    conv: Conversation,
    pid: str,
    user: "User",
    plan_meta: dict,
    state: "ConversationState",
) -> dict:
    """Inline confirm + create Run (approved) + enqueue — called when user says 'go'."""
    from app.services.strategy_plan import resolve_selected_strategy

    instruction = str(plan_meta.get("instruction") or "").strip() or "Create deliverables"
    template_ids: list[str] = [str(x) for x in (plan_meta.get("template_output_types") or []) if str(x).strip()]
    custom_output_types = _normalize_custom_output_types(
        [str(x) for x in (plan_meta.get("custom_output_types") or []) if str(x).strip()]
    )
    output_type_representations = _normalize_output_type_representations(
        {str(k): str(v) for k, v in (plan_meta.get("output_type_representations") or {}).items()}
    )
    content_skill_targets: dict[str, str] = {
        str(k).strip(): str(v).strip()
        for k, v in (plan_meta.get("content_skill_targets") or {}).items()
        if str(k).strip() and str(v).strip()
    }
    plan_hash = str(plan_meta.get("plan_hash") or "")
    da = _sanitize_decision_answers(plan_meta.get("decision_answers"))
    dossier = plan_meta.get("strategy_dossier") if isinstance(plan_meta.get("strategy_dossier"), dict) else None
    selected_strategy = resolve_selected_strategy(dossier, da)
    discovery = _normalize_discovery(plan_meta.get("discovery"))

    # Guard: don't create a duplicate run for the same conversation.
    existing_run = db.scalar(
        select(Run)
        .where(Run.project_id == pid)
        .where(Run.status.in_({"plan_ready", "approved", "running", "review_ready"}))
        .order_by(Run.id.desc())
        .limit(1)
    )
    if existing_run:
        assistant_msg = ConversationMessage(
            conversation_id=conv.id,
            role="assistant",
            content="A run is already in progress — check the Activity panel for status.",
            metadata_json=json.dumps({"kind": "auto_execute_skipped", "run_id": existing_run.id}),
        )
        db.add(assistant_msg)
        conv.updated_at = datetime.now(IST).replace(tzinfo=None)
        db.commit()
        return {
            "conversation_id": conv.id,
            "messages": _serialize_messages(db, conv.id),
            "run_id": existing_run.id,
            "auto_executed": False,
            "open_questions": [],
            "ready_for_confirmation": False,
            "plan_hash": plan_hash,
        }

    # Persist plan_confirmed message (mirrors confirm_project_conversation_plan).
    confirm_msg = ConversationMessage(
        conversation_id=conv.id,
        role="user",
        content="Confirmed plan for execution.",
        metadata_json=json.dumps({
            "plan_confirmed": True,
            "plan_hash": plan_hash,
            "instruction": instruction,
            "template_output_types": template_ids,
            "custom_output_types": custom_output_types,
            "output_type_representations": output_type_representations,
            "content_skill_targets": content_skill_targets,
            "regeneration_directive": str(plan_meta.get("regeneration_directive") or "").strip(),
            "confirmed_at": datetime.now(IST).isoformat(),
            "decision_answers": da,
            "strategy_dossier": dossier,
            "selected_strategy": selected_strategy,
            "discovery": discovery,
            "deck_outline_preview": plan_meta.get("deck_outline_preview")
            if isinstance(plan_meta.get("deck_outline_preview"), dict) else None,
            "document_outline_preview": plan_meta.get("document_outline_preview")
            if isinstance(plan_meta.get("document_outline_preview"), dict) else None,
            "wiki_context_refs": plan_meta.get("wiki_context_refs")
            if isinstance(plan_meta.get("wiki_context_refs"), list) else [],
        }),
    )
    db.add(confirm_msg)
    db.flush()

    # Build plan payload and run permission pipeline.
    plan = dict(_build_plan_payload(
        project_id=pid,
        instruction=instruction,
        output_types=template_ids,
        custom_output_types=custom_output_types,
        output_type_representations=output_type_representations,
        content_skill_targets=content_skill_targets,
        regeneration_directive=str(plan_meta.get("regeneration_directive") or "").strip(),
    ))
    if isinstance(selected_strategy, dict) and selected_strategy.get("option_id"):
        plan["selected_strategy"] = selected_strategy
    deck_outline = plan_meta.get("deck_outline_preview")
    if isinstance(deck_outline, dict) and deck_outline.get("slides"):
        plan["deck_outline_preview"] = deck_outline
    document_outline = plan_meta.get("document_outline_preview")
    if isinstance(document_outline, dict) and document_outline.get("sections"):
        plan["document_outline_preview"] = document_outline
    wiki_refs = plan_meta.get("wiki_context_refs")
    if isinstance(wiki_refs, list) and wiki_refs:
        plan["wiki_context_refs"] = [str(r).strip() for r in wiki_refs if str(r).strip()][:20]
    plan["conversation_id"] = conv.id
    if plan_hash:
        plan["plan_hash"] = plan_hash

    preflight = evaluate_permission_pipeline(
        run_status="plan_ready",
        has_approval=True,
        requested_outputs=list(template_ids),
        workspace_ready=bool(__import__("app.services.storage", fromlist=["workspace_path"]).workspace_path(pid).exists()),
        classifier_score=1.0,
        classifier_threshold=float(settings.policy_classifier_threshold),
        enforce_policy=bool(settings.policy_enforce_enabled),
        plan_payload=plan,
        include_human_gate=False,
        agentic_loop_enabled=bool(settings.coordinator_agentic_loop_enabled),
    )
    blocked = [d for d in preflight if not d.allowed]

    if blocked:
        first_block = blocked[0]
        assistant_msg = ConversationMessage(
            conversation_id=conv.id,
            role="assistant",
            content=f"Can't start the run — blocked by policy ({first_block.stage}: {first_block.reason}). Fix the issue and try again.",
            metadata_json=json.dumps({
                "kind": "auto_execute_blocked",
                "blocked_stage": first_block.stage,
                "blocked_reason": first_block.reason,
                "blocked_code": first_block.code,
            }),
        )
        db.add(assistant_msg)
        conv.updated_at = datetime.now(IST).replace(tzinfo=None)
        db.commit()
        return {
            "conversation_id": conv.id,
            "messages": _serialize_messages(db, conv.id),
            "open_questions": [],
            "ready_for_confirmation": False,
            "plan_hash": plan_hash,
        }

    # Create Run directly in 'approved' status (skip plan_ready → approve cycle).
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    now = datetime.now(IST).replace(tzinfo=None)
    run = Run(
        id=run_id,
        project_id=pid,
        status="approved",
        output_types=json.dumps(template_ids),
        instruction=instruction,
        plan_payload=json.dumps(plan),
        approved_by=user.id,
        approved_at=now,
    )
    db.add(run)
    db.flush()

    append_run_event(db, run_id, "plan_ready", plan)
    for d in preflight:
        append_run_event(db, run_id, "permission_stage", {
            "stage": d.stage, "allowed": d.allowed, "code": d.code,
            "reason": d.reason, "metadata": d.metadata or {},
        })
    append_run_event(db, run_id, "step", {"status": "plan_approved", "approved_by": user.email})
    append_memory_event(
        db,
        project_id=pid,
        run_id=run_id,
        event_type="user_intent_updated",
        payload_obj={"summary": instruction[:400]},
    )
    swarm_instr = persist_instruction_broadcast_swarm_event_payload(
        db, project_id=pid, run_id=run_id, instruction=instruction,
    )
    if swarm_instr:
        append_run_event(db, run_id, "swarm_message", swarm_instr)

    # Enqueue — catch 503 so chat endpoint doesn't fail.
    try:
        if not enqueue_run_execution(pid, run_id):
            raise RuntimeError("enqueue returned False")
        enqueued = True
    except Exception as exc:
        _LOG.error("auto_execute: enqueue failed for run %s project %s: %s", run_id, pid, exc)
        enqueued = False

    state.state = "run_queued"
    save_state(conv, state)

    queue_msg = (
        "Queued — watch the Activity panel for progress."
        if enqueued
        else "Run created but couldn't be queued right now. Use the Activity panel to retry."
    )
    assistant_msg = ConversationMessage(
        conversation_id=conv.id,
        role="assistant",
        content=queue_msg,
        metadata_json=json.dumps({
            "kind": "auto_executed",
            "run_id": run_id,
            "auto_executed": True,
            "enqueued": enqueued,
        }),
    )
    db.add(assistant_msg)
    conv.updated_at = datetime.now(IST).replace(tzinfo=None)
    db.commit()

    return {
        "conversation_id": conv.id,
        "messages": _serialize_messages(db, conv.id),
        "run_id": run_id,
        "auto_executed": True,
        "open_questions": [],
        "ready_for_confirmation": False,
        "plan_hash": plan_hash,
    }


_PROPOSAL_DISCOVERY_OUTPUT_TYPES = {"pptx", "docx"}


def _is_proposal_instruction(content: str, template_ids: list[str]) -> bool:
    targets = {str(x).strip().lower() for x in (template_ids or []) if str(x).strip()}
    if targets & _PROPOSAL_DISCOVERY_OUTPUT_TYPES:
        return True
    lowered = (content or "").strip()
    if not lowered:
        return False
    return bool(is_finance_proposal_intent(lowered) or has_proposal_intent(lowered) or "rfp" in lowered.lower())


def _has_proposal_slot_signal(slots: dict | None) -> bool:
    """Return True when captured discovery slots look like proposal context.

    Two of {client.name, audience, win_themes} being present is treated as
    strong evidence the user is in a proposal discovery, even without the
    word "proposal" / "create" in the latest message.
    """
    if not isinstance(slots, dict):
        return False
    present = 0
    client = slots.get("client") if isinstance(slots.get("client"), dict) else {}
    if str(client.get("name") or "").strip():
        present += 1
    if str(slots.get("audience") or "").strip():
        present += 1
    themes = slots.get("win_themes") if isinstance(slots.get("win_themes"), list) else []
    if themes:
        present += 1
    outcome = slots.get("outcome") if isinstance(slots.get("outcome"), dict) else {}
    if str(outcome.get("primary") or "").strip():
        present += 1
    return present >= 2


def _grounded_conversational_fallback(*, slots: dict | None, missing_slots: list[str] | None) -> str:
    """Deterministic slot-aware reply used only when the LLM call fails.

    Avoids the old generic 'Great topic!' template by referencing captured facts
    and asking only for the missing pieces.
    """
    slots = slots or {}
    missing_slots = [s for s in (missing_slots or []) if s]
    known_parts: list[str] = []
    client = slots.get("client") if isinstance(slots.get("client"), dict) else {}
    name = str(client.get("name") or "").strip()
    if name:
        known_parts.append(f"client **{name}**")
    audience = str(slots.get("audience") or "").strip()
    if audience:
        known_parts.append(f"audience **{audience}**")
    themes = slots.get("win_themes") if isinstance(slots.get("win_themes"), list) else []
    if themes:
        known_parts.append("win themes: " + ", ".join(str(t) for t in themes))
    outcome = slots.get("outcome") if isinstance(slots.get("outcome"), dict) else {}
    primary_outcome = str(outcome.get("primary") or "").strip()
    if primary_outcome:
        known_parts.append(f"outcome: {primary_outcome}")

    if known_parts and not missing_slots:
        return (
            "Got it — I have "
            + "; ".join(known_parts)
            + ". Do you want this as a PPTX deck, a DOCX document, or both? I can draft a plan as soon as you pick."
        )
    if known_parts and missing_slots:
        friendly = {
            "client": "the client name",
            "audience": "the primary audience",
            "win_themes": "1–3 win themes we want to land",
            "outcome": "the headline outcome/problem we're solving",
        }
        asks = [friendly.get(s, s) for s in missing_slots]
        return (
            "Captured "
            + "; ".join(known_parts)
            + ". To move on I still need " + ", ".join(asks) + "."
        )
    return (
        "Tell me the client, the primary audience, and 1–3 win themes you want to land. "
        "Once I have those I'll sketch the deliverable structure."
    )


def _normalize_discovery(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, object] = {}
    client = raw.get("client")
    if isinstance(client, str) and client.strip():
        client = {"name": client.strip()}
    if isinstance(client, dict):
        name = str(client.get("name") or "").strip()
        industry = str(client.get("industry") or "").strip()
        if name or industry:
            out["client"] = {"name": name, "industry": industry}
    outcome = raw.get("outcome")
    if isinstance(outcome, str) and outcome.strip():
        outcome = {"primary": outcome.strip()}
    if isinstance(outcome, dict):
        primary = str(outcome.get("primary") or "").strip()
        decision = str(outcome.get("decision") or "").strip()
        if primary or decision:
            out["outcome"] = {"primary": primary, "decision": decision}
    themes = raw.get("win_themes")
    if isinstance(themes, str) and themes.strip():
        themes = [t.strip() for t in re.split(r"[,;]|\band\b", themes) if t.strip()]
    if isinstance(themes, list):
        vals = [str(x).strip() for x in themes if str(x).strip()]
        if vals:
            out["win_themes"] = vals[:3]
    audience = str(raw.get("audience") or "").strip().lower()
    if audience:
        out["audience"] = audience
    narrative_arc = str(raw.get("narrative_arc") or "").strip().lower()
    if narrative_arc:
        out["narrative_arc"] = narrative_arc
    tone = str(raw.get("tone") or "").strip().lower()
    if tone:
        out["tone"] = tone
    length_budget = raw.get("length_budget")
    if isinstance(length_budget, dict):
        lb: dict[str, int] = {}
        try:
            pptx = int(length_budget.get("pptx")) if length_budget.get("pptx") is not None else None
            if pptx and 4 <= pptx <= 30:
                lb["pptx"] = pptx
        except Exception:
            pass
        try:
            docx_pages = int(length_budget.get("docx_pages")) if length_budget.get("docx_pages") is not None else None
            if docx_pages and 2 <= docx_pages <= 120:
                lb["docx_pages"] = docx_pages
        except Exception:
            pass
        if lb:
            out["length_budget"] = lb
    edited_by_user = raw.get("edited_by_user")
    if isinstance(edited_by_user, bool):
        out["edited_by_user"] = edited_by_user
    return out


def _merge_discovery(base: object, incoming: object) -> dict:
    merged = _normalize_discovery(base)
    extra = _normalize_discovery(incoming)
    if not extra:
        return merged
    for key in ("client", "outcome", "length_budget"):
        if key in extra:
            b = merged.get(key) if isinstance(merged.get(key), dict) else {}
            i = extra.get(key) if isinstance(extra.get(key), dict) else {}
            # Keep prior non-empty values when a new extraction only provides
            # partial fields (e.g. outcome.decision without outcome.primary).
            next_obj = dict(b)
            for fk, fv in i.items():
                if isinstance(fv, str):
                    if fv.strip():
                        next_obj[fk] = fv
                elif fv is not None:
                    next_obj[fk] = fv
            merged[key] = next_obj
    for key in ("audience", "narrative_arc", "tone", "edited_by_user"):
        if key in extra:
            merged[key] = extra[key]
    if "win_themes" in extra:
        existing = merged.get("win_themes")
        cur = existing if isinstance(existing, list) else []
        nxt = extra.get("win_themes") if isinstance(extra.get("win_themes"), list) else []
        merged["win_themes"] = (cur + [x for x in nxt if x not in cur])[:3]
    return merged


def _has_sufficient_discovery(discovery: object) -> bool:
    data = _normalize_discovery(discovery)
    client = data.get("client") if isinstance(data.get("client"), dict) else {}
    outcome = data.get("outcome") if isinstance(data.get("outcome"), dict) else {}
    themes = data.get("win_themes") if isinstance(data.get("win_themes"), list) else []
    has_outcome = bool(str(outcome.get("primary") or "").strip() or str(outcome.get("decision") or "").strip())
    return bool(str(client.get("name") or "").strip() and has_outcome and themes)


def _required_discovery_missing_slots(discovery: object) -> list[str]:
    """Compute required discovery gaps from canonical merged slots."""
    data = _normalize_discovery(discovery)
    client = data.get("client") if isinstance(data.get("client"), dict) else {}
    outcome = data.get("outcome") if isinstance(data.get("outcome"), dict) else {}
    themes = data.get("win_themes") if isinstance(data.get("win_themes"), list) else []
    missing: list[str] = []
    if not str(client.get("name") or "").strip():
        missing.append("client")
    if not (str(outcome.get("primary") or "").strip() or str(outcome.get("decision") or "").strip()):
        missing.append("outcome")
    if not [str(x).strip() for x in themes if str(x).strip()]:
        missing.append("win_themes")
    return missing


def _extract_entity_tokens(text: str) -> list[str]:
    candidates = re.findall(r"\b[A-Z][A-Za-z0-9&.\-]{2,}\b", str(text or ""))
    out: list[str] = []
    seen: set[str] = set()
    for token in candidates:
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
        if len(out) >= 8:
            break
    return out


def _top_parsed_doc_chunks_for_query(project_id: str, query_text: str, max_chunks: int = 2) -> list[dict]:
    try:
        engine = TieredContextEngine()
        chunks = engine._load_all_parsed_chunks(project_id)  # noqa: SLF001
        if not chunks:
            return []
        scores = engine._bm25_scores(chunks, query_text)  # noqa: SLF001
        ranked = [chunks[i] for i, score in sorted(enumerate(scores), key=lambda x: x[1], reverse=True) if score > 0]
        return ranked[:max_chunks]
    except Exception as exc:
        _LOG.warning("wiki slot extractor: parsed doc retrieval failed for project %s: %s", project_id, exc)
        return []


def _extract_discovery_answers_from_wiki(
    *,
    project_id: str,
    user_message: str,
    prior_messages: list[dict],
) -> tuple[dict[str, object], list[str]]:
    from app.services.claude import claude_generate_json
    from app.services.wiki_query import _get_wiki_index, _search_wiki_pages

    seed_query = "client name industry primary audience outcome decision win themes proof points"
    entity_tokens = _extract_entity_tokens(user_message)
    query = f"{seed_query} {' '.join(entity_tokens)}".strip()
    wiki_refs: list[str] = []
    wiki_pages: list[dict] = []
    try:
        index = _get_wiki_index("project", project_id)
        wiki_pages = _search_wiki_pages(query, index or {"pages": []}, "project", project_id)[:6]
    except Exception:
        wiki_pages = []
    wiki_excerpt: list[str] = []
    for page in wiki_pages:
        if not isinstance(page, dict):
            continue
        title = str(page.get("title") or page.get("page_id") or "").strip()
        if title:
            wiki_refs.append(title)
        body = str(page.get("content") or "").strip()
        if title and body:
            wiki_excerpt.append(f"[Wiki: {title}]\n{body[:700]}")
    doc_chunks = _top_parsed_doc_chunks_for_query(project_id, query, max_chunks=2)
    doc_excerpt = []
    for chunk in doc_chunks:
        if not isinstance(chunk, dict):
            continue
        source = str(chunk.get("source") or chunk.get("title") or "parsed_doc").strip()
        text = str(chunk.get("text") or "").strip()
        if text:
            doc_excerpt.append(f"[Doc: {source}]\n{text[:700]}")
    if not wiki_excerpt and not doc_excerpt:
        return {}, []

    prior_context = "\n".join(
        f"{m.get('role', 'user')}: {str(m.get('content') or '').strip()}"
        for m in prior_messages[-6:]
        if str(m.get("content") or "").strip()
    )
    evidence = "\n\n".join(wiki_excerpt + doc_excerpt)[:5000]
    try:
        payload = claude_generate_json(
            system=(
                "Extract proposal discovery details from evidence snippets. "
                "Return JSON only with keys: "
                "client{name,industry}, outcome{primary,decision}, win_themes[array max 3], audience, source_refs[array]. "
                "Use only explicit evidence. Leave unknown fields empty or omitted."
            ),
            user=(
                f"Recent chat context:\n{prior_context}\n\n"
                f"Latest user message:\n{user_message}\n\n"
                f"Evidence:\n{evidence}"
            ),
            temperature=0.1,
            max_tokens=500,
        )
    except Exception:
        return {}, wiki_refs[:6]
    normalized = _normalize_discovery(payload)
    source_refs_raw = payload.get("source_refs") if isinstance(payload, dict) else []
    source_refs = []
    if isinstance(source_refs_raw, list):
        for item in source_refs_raw:
            text = str(item or "").strip()
            if text and text in wiki_refs and text not in source_refs:
                source_refs.append(text)
    return normalized, (source_refs or wiki_refs[:6])


def _propose_discovery_questions(
    db: Session,
    conv: Conversation,
    instruction: str,
    prior_messages: list[dict],
    *,
    missing_slots: list[str] | None = None,
    wiki_context: str | None = None,
    wiki_prefilled_slots: list[str] | None = None,
    conv_slots: dict | None = None,
) -> dict:
    from app.services.claude import claude_generate_json

    prior_context = "\n".join(
        f"{m.get('role', 'user')}: {str(m.get('content') or '').strip()}"
        for m in prior_messages[-15:]
        if str(m.get("content") or "").strip()
    )
    slot_questions = {
        "client": "Who is the client (name + industry), and what transformation problem are we solving?",
        "outcome": "Who is the primary audience, and what decision should this proposal help them make?",
        "win_themes": "What 2-3 win themes or proof points must we emphasize?",
    }
    wiki_prefilled = {str(x).strip() for x in (wiki_prefilled_slots or []) if str(x).strip()}
    normalized_missing = [s for s in (missing_slots or []) if s in slot_questions and s not in wiki_prefilled]

    known_slots = {k: v for k, v in (conv_slots or {}).items() if v and str(v).strip()}
    known_context = (
        "Already captured — do NOT ask about these:\n"
        + "\n".join(f"- {k}: {v}" for k, v in known_slots.items())
        if known_slots else ""
    )

    questions: list[str] = []
    if normalized_missing:
        questions = [slot_questions[s] for s in normalized_missing]
    if normalized_missing:
        try:
            payload = claude_generate_json(
                system=(
                    "Generate concise discovery questions for a consulting proposal kickoff. "
                    + (known_context + "\n" if known_context else "")
                    + (
                        "Use wiki context as hints and phrase questions as confirmation when possible. "
                        if wiki_context else ""
                    )
                    + "Ask ONLY for listed missing_slots. Return JSON: {\"questions\": [\"...\", ...]}."
                ),
                user=(
                    f"Instruction:\n{instruction}\n\n"
                    f"Missing slots: {normalized_missing}\n\n"
                    f"Recent context:\n{prior_context}\n\n"
                    + (f"Wiki context excerpt:\n{str(wiki_context)[:2500]}" if wiki_context else "")
                ),
                temperature=0.2,
                max_tokens=300,
            )
            raw_q = payload.get("questions") if isinstance(payload, dict) else None
            if isinstance(raw_q, list):
                questions = [str(q).strip() for q in raw_q if str(q).strip()][: max(1, len(normalized_missing))]
        except Exception:
            questions = []
    if len(questions) < len(normalized_missing or []) or (not normalized_missing and not questions):
        still_missing = [s for s in slot_questions if s not in known_slots]
        questions = [slot_questions[s] for s in still_missing] if still_missing else list(slot_questions.values())

    # Build a contextual, grounded message rather than the generic "3 quick inputs" template.
    # Reference what's already captured so Sheldon sounds like a colleague, not a form.
    from app.services.claude import claude_generate as _cg

    known_bits: list[str] = []
    _client = known_slots.get("client") if isinstance(known_slots.get("client"), dict) else {}
    if str(_client.get("name") or "").strip():
        known_bits.append(f"Client: {_client['name']}" + (f" ({_client['industry']})" if _client.get("industry") else ""))
    _outcome = known_slots.get("outcome") if isinstance(known_slots.get("outcome"), dict) else {}
    if str(_outcome.get("primary") or "").strip():
        known_bits.append(f"Outcome: {_outcome['primary']}")
    if known_slots.get("audience"):
        known_bits.append(f"Audience: {known_slots['audience']}")
    _themes = known_slots.get("win_themes") if isinstance(known_slots.get("win_themes"), list) else []
    if _themes:
        known_bits.append(f"Win themes: {', '.join(str(t) for t in _themes)}")
    known_summary = "; ".join(known_bits) if known_bits else ""

    try:
        message = _cg(
            system=(
                "You are Sheldon, a consulting copilot. Be a thoughtful colleague, not a form.\n"
                "Acknowledge what the user just shared (do NOT re-ask anything already captured).\n"
                "Then ask ONLY the single most important missing question from the list below.\n"
                "Keep it to 2-3 sentences. No numbered lists. One emoji max.\n"
                + (f"Already established: {known_summary}\n" if known_summary else "")
            ),
            user=(
                f"User said: {instruction}\n\n"
                f"Still need (ask for ONE, the most important): {questions}\n\n"
                f"Recent context:\n{prior_context}"
            ),
            temperature=0.4,
            max_tokens=200,
        ).strip()
    except Exception:
        q_count = len(questions)
        lead = "One more thing" if q_count == 1 else f"{q_count} things still needed"
        message = f"{lead}:\n- " + "\n- ".join(questions)
    msg = ConversationMessage(
        conversation_id=conv.id,
        role="assistant",
        content=message,
        metadata_json=json.dumps({"kind": "discovery_questions", "discovery_questions": questions}),
    )
    db.add(msg)
    conv.updated_at = datetime.now(IST).replace(tzinfo=None)
    db.commit()
    return {
        "conversation_id": conv.id,
        "messages": _serialize_messages(db, conv.id),
        "open_questions": questions,
        "ready_for_confirmation": False,
        "plan_hash": None,
    }


def _extract_discovery_answers(user_message: str, prior_messages: list[dict]) -> dict:
    from app.services.claude import claude_generate_json

    context = "\n".join(
        f"{m.get('role', 'user')}: {str(m.get('content') or '').strip()}"
        for m in prior_messages[-15:]
        if str(m.get("content") or "").strip()
    )
    try:
        payload = claude_generate_json(
            system=(
                "Extract proposal discovery details from a user's response. "
                "Return JSON with this exact structure (omit fields with no evidence): "
                '{"client": {"name": "...", "industry": "..."}, '
                '"outcome": {"primary": "...", "decision": "..."}, '
                '"win_themes": ["...", "..."], "audience": "..."}. '
                "client.name = company name. outcome.primary = the problem/goal being solved. "
                "win_themes = key differentiators or proof points. Never return empty strings."
            ),
            user=f"Recent chat context:\n{context}\n\nLatest user response:\n{user_message}",
            temperature=0.1,
            max_tokens=300,
        )
        return _normalize_discovery(payload)
    except Exception:
        return {}


def _extract_discovery_answers_fast(user_message: str) -> dict:
    """Best-effort deterministic extraction for common discovery answer phrasings."""
    text = str(user_message or "").strip()
    lowered = text.lower()
    out: dict[str, object] = {}

    client_match = re.search(r"\bclient\s+is\s+([^\-.,\n]+)", text, re.IGNORECASE)
    if client_match:
        client_name = client_match.group(1).strip()
        if client_name:
            out["client"] = {"name": client_name}

    industry_match = re.search(r"\bindustry\s*(?:is|:)\s*([^.\n]+)", text, re.IGNORECASE)
    if industry_match:
        industry = industry_match.group(1).strip()
        cur = out.get("client") if isinstance(out.get("client"), dict) else {}
        out["client"] = {**cur, "industry": industry}

    audience_match = re.search(
        r"\b(?:primary\s+audience|audience)\s*(?:is|:)\s*([^.\n]+)",
        text,
        re.IGNORECASE,
    )
    if audience_match:
        out["audience"] = audience_match.group(1).strip().lower()

    theme_matches = re.findall(r"\b(?:key\s+)?win\s+theme(?:s)?\s*(?:is|are|:)\s*([^.\n]+)", text, re.IGNORECASE)
    if theme_matches:
        themes: list[str] = []
        for m in theme_matches:
            parts = [p.strip(" -") for p in re.split(r",| and ", m) if p.strip()]
            themes.extend(parts)
        if themes:
            out["win_themes"] = themes[:3]

    outcome_match = re.search(
        r"\btransformation\s+problem\s*(?:is|:)\s*([^.\n]+)",
        text,
        re.IGNORECASE,
    )
    if outcome_match:
        out["outcome"] = {"primary": outcome_match.group(1).strip()}
    else:
        # Common natural phrasing in chat: "proposal should help them decide X"
        # or "should help decide X". Capture that as the decision and derive a
        # primary outcome so we don't re-ask the same slot every turn.
        decision_match = re.search(
            r"\b(?:proposal|document|deck)?\s*should\s+help(?:\s+\w+){0,3}\s+decide\s*(?:on|whether|to)?\s*([^.\n]+)",
            text,
            re.IGNORECASE,
        )
        if decision_match:
            decision = decision_match.group(1).strip(" :,-")
            if decision:
                out["outcome"] = {
                    "primary": f"Support decision-making on {decision}",
                    "decision": decision,
                }
    if "outcome" not in out:
        decision_is_match = re.search(
            r"\bdecision\s*(?:is|:)\s*([^.\n]+)",
            text,
            re.IGNORECASE,
        )
        if decision_is_match:
            decision = decision_is_match.group(1).strip(" :,-")
            if decision:
                out["outcome"] = {
                    "primary": f"Support decision-making on {decision}",
                    "decision": decision,
                }
    if "outcome" not in out and "driving transformation" in lowered:
        out["outcome"] = {"primary": "Drive transformation across processes"}

    return _normalize_discovery(out)


_WIKI_REF_PATTERN = re.compile(r"\[Wiki:\s*([^\]\n]+?)\]")


def _extract_wiki_titles(excerpt: str) -> list[str]:
    """Pull out unique wiki page titles referenced in a planner excerpt."""
    if not excerpt:
        return []
    seen: list[str] = []
    for match in _WIKI_REF_PATTERN.finditer(excerpt):
        title = match.group(1).strip()
        if title and title not in seen:
            seen.append(title)
    return seen[:12]


def _load_project_context_snapshot(db: Session, project_id: str, instruction: str) -> str:
    snap = _load_project_context_bundle(db, project_id, instruction)
    return snap["text"]


def _load_project_context_bundle(db: Session, project_id: str, instruction: str) -> dict:
    """Load the project context snapshot plus the list of wiki pages it cited.

    Returns {"text": str, "wiki_refs": list[str]} — the text is what already
    powered the router, and wiki_refs exposes the titles of wiki pages that
    actually landed in the excerpt so the UI can surface "grounded in:" citations.
    """
    engine = TieredContextEngine()
    excerpt = engine.planner_excerpt(project_id, instruction, char_cap=6000)
    profile_row = db.scalar(select(ProjectMemoryProfile).where(ProjectMemoryProfile.project_id == project_id))
    profile_text = ""
    if profile_row and profile_row.summary_json:
        try:
            parsed = json.loads(profile_row.summary_json)
            if isinstance(parsed, dict):
                profile_text = json.dumps(parsed)[:2500]
        except Exception:
            profile_text = ""
    combined_parts: list[str] = []
    if profile_text:
        combined_parts.append(f"[ProjectMemoryProfile]\n{profile_text}")
    if excerpt:
        combined_parts.append(excerpt)
    text = "\n\n".join(combined_parts)[:9000]
    return {"text": text, "wiki_refs": _extract_wiki_titles(excerpt)}


def _contains_deliverable_signal(text: str) -> bool:
    lowered = (text or "").lower()
    signals = [
        "proposal",
        "deck",
        "presentation",
        "report",
        "financial model",
        "sop",
        "process map",
        "raci",
        "docx",
        "pptx",
        "xlsx",
    ]
    return any(sig in lowered for sig in signals)


def _persist_conversational_response(
    db: Session,
    conv: Conversation,
    user_message: str,
    prior_messages: list[dict],
    *,
    slots: dict | None = None,
    project_context: str | None = None,
    missing_slots: list[str] | None = None,
    wiki_refs: list[str] | None = None,
    already_surfaced_refs: list[str] | None = None,
    router_intent: str | None = None,
    router_confidence: float | None = None,
    project_id: str | None = None,
    history_summary: str = "",
) -> dict:
    """Generate a natural, colleague-like conversational response grounded in captured context.

    The LLM prompt always receives currently known slots and project context (wiki/memory)
    so responses reference actual facts (e.g. client name, audience, win themes) rather than
    asking for information the user has already supplied.
    """
    from app.services.claude import claude_generate

    recent_context = "\n".join(
        f"{m.get('role', 'user').upper()}: {str(m.get('content') or '')[:600]}"
        for m in prior_messages[-15:]
        if str(m.get("content") or "").strip()
    )
    slots = slots or {}
    missing_slots = [s for s in (missing_slots or []) if s]
    project_context = (project_context or "").strip()
    wiki_refs = [str(x).strip() for x in (wiki_refs or []) if str(x).strip()]
    already_surfaced_refs = [str(x).strip() for x in (already_surfaced_refs or []) if str(x).strip()]
    unsurfaced_refs = [x for x in wiki_refs if x not in already_surfaced_refs]
    routed_intent = str(router_intent or "").strip().lower()
    routed_confidence = float(router_confidence or 0.0)

    known_bits: list[str] = []
    client = slots.get("client") if isinstance(slots.get("client"), dict) else {}
    if str(client.get("name") or "").strip():
        known_bits.append(f"- Client: {client.get('name')}" + (f" ({client.get('industry')})" if client.get("industry") else ""))
    outcome = slots.get("outcome") if isinstance(slots.get("outcome"), dict) else {}
    if str(outcome.get("primary") or "").strip():
        known_bits.append(f"- Outcome/Problem: {outcome.get('primary')}")
    if slots.get("audience"):
        known_bits.append(f"- Audience: {slots.get('audience')}")
    themes = slots.get("win_themes") if isinstance(slots.get("win_themes"), list) else []
    if themes:
        known_bits.append(f"- Win themes: {', '.join(str(t) for t in themes)}")
    known_block = "\n".join(known_bits) if known_bits else "(none captured yet)"
    missing_block = ", ".join(missing_slots) if missing_slots else "(none — all required inputs captured)"

    system_prompt = (
        "You are Sheldon, a consulting copilot. Respond as a thoughtful colleague, NOT a vending machine.\n"
        "You MUST ground every response in the captured context below. Do NOT ask the user for information "
        "that is already present. When context contains client, audience, outcome, or win themes, "
        "acknowledge them explicitly and move the conversation forward.\n"
        "If missing_slots is non-empty, ask ONLY for those. If missing_slots is empty, confirm readiness "
        "and offer to create a specific deliverable (e.g. propose PPTX vs DOCX) — but do NOT say 'Plan Ready'.\n"
        "Keep replies concise (2-4 sentences). Use at most 1 emoji. Never return the generic 'Great topic!' template.\n"
        "When using facts sourced from the project wiki, cite inline as '(source: [Wiki: Title])'. "
        "Only cite titles from allowed_wiki_refs.\n"
        "HARD RULE: You are a text-only interface. You CANNOT execute, build, draft, or create anything. "
        "NEVER claim to be starting work, drafting slides, building a document, or promise delivery by a "
        "specific time (e.g. 'in 90 minutes', 'shortly', 'now'). If the user says 'go ahead' or asks you "
        "to start, respond: 'Type \"go\" to queue the run and I will start immediately.' Nothing else."
    )
    if unsurfaced_refs:
        system_prompt += (
            "\nIf relevant, start with a one-line 'Heads up:' insight grounded in a wiki fact "
            "from allowed_wiki_refs, then continue the normal reply."
        )
    if routed_intent in {"clarify", "discovery_answer"} and routed_confidence < 0.6 and project_id and settings.wiki_aware_discovery_enabled:
        # Phase 2: lightweight, budgeted wiki lookup before response generation.
        from app.services.wiki_query import _get_wiki_index, _search_wiki_pages

        lookup_budget_sec = 1.5
        lookup_start = perf_counter()
        lookups = [
            str(user_message or "").strip(),
            "client name industry audience outcome decision win themes",
        ]
        extra_refs: list[str] = []
        snippets: list[str] = []
        for query in lookups[:2]:
            if perf_counter() - lookup_start > lookup_budget_sec:
                break
            try:
                index = _get_wiki_index("project", project_id)
                pages = _search_wiki_pages(query[:400], index or {"pages": []}, "project", project_id)[:3]
            except Exception:
                pages = []
            for page in pages:
                title = str(page.get("title") or page.get("page_id") or "").strip()
                body = str(page.get("content") or "").strip()
                if not title or not body:
                    continue
                if title not in extra_refs:
                    extra_refs.append(title)
                snippets.append(f"[Wiki: {title}]\n{body[:500]}")
        if snippets:
            project_context = (project_context + "\n\n[Live wiki lookup]\n" + "\n\n".join(snippets))[:5500]
            for ref in extra_refs:
                if ref not in wiki_refs:
                    wiki_refs.append(ref)
            unsurfaced_refs = [x for x in wiki_refs if x not in already_surfaced_refs]
    summary_block = (
        f"Conversation summary (prior turns):\n{history_summary}\n\n"
        if history_summary.strip()
        else ""
    )
    user_prompt = (
        f"{summary_block}"
        f"Captured context (known_slots):\n{known_block}\n\n"
        f"Missing slots: {missing_block}\n\n"
        f"Allowed wiki refs: {unsurfaced_refs[:8]}\n\n"
        f"Project context excerpt (wiki/memory):\n{project_context[:4000] or '(none)'}\n\n"
        f"Conversation so far:\n{recent_context}\n\n"
        f"Latest user message:\n{user_message}\n\n"
        "Write the reply now."
    )

    try:
        response_text = claude_generate(
            system=system_prompt,
            user=user_prompt,
            temperature=0.4,
            max_tokens=400,
        ).strip()
    except Exception:
        response_text = _grounded_conversational_fallback(slots=slots, missing_slots=missing_slots)

    msg = ConversationMessage(
        conversation_id=conv.id,
        role="assistant",
        content=response_text,
        metadata_json=json.dumps({"kind": "conversational_response", "wiki_refs": wiki_refs[:10]}),
    )
    db.add(msg)
    db.commit()

    messages = _serialize_messages(db, conv.id)
    return {
        "conversation_id": conv.id,
        "messages": messages,
        "open_questions": [],
        "ready_for_confirmation": False,
        "plan_hash": None,
    }


def _persist_acknowledgment_response(
    db: Session,
    conv: Conversation,
    user_message: str,
    prior_messages: list[dict],
    *,
    slots: dict | None = None,
    project_context: str | None = None,
) -> dict:
    """Generate a brief, grounded response to a simple acknowledgment.

    Grounds the reply in captured slots and project context so responses
    remain coherent mid-conversation rather than generic.
    """
    from app.services.claude import claude_generate

    recent_context = "\n".join(
        f"{m.get('role', 'user').upper()}: {str(m.get('content') or '')[:400]}"
        for m in prior_messages[-15:]
        if str(m.get("content") or "").strip()
    )

    slots = slots or {}
    project_context = (project_context or "").strip()

    known_bits: list[str] = []
    client = slots.get("client") if isinstance(slots.get("client"), dict) else {}
    if str(client.get("name") or "").strip():
        known_bits.append(f"- Client: {client.get('name')}" + (f" ({client.get('industry')})" if client.get("industry") else ""))
    outcome = slots.get("outcome") if isinstance(slots.get("outcome"), dict) else {}
    if str(outcome.get("primary") or "").strip():
        known_bits.append(f"- Outcome/Problem: {outcome.get('primary')}")
    if slots.get("audience"):
        known_bits.append(f"- Audience: {slots.get('audience')}")
    themes = slots.get("win_themes") if isinstance(slots.get("win_themes"), list) else []
    if themes:
        known_bits.append(f"- Win themes: {', '.join(str(t) for t in themes)}")
    known_block = "\n".join(known_bits) if known_bits else "(none captured yet)"

    system_prompt = """You are Sheldon, an energetic creative partner.
The user just sent a brief acknowledgment (like "sounds good", "makes sense", "great").

You MUST ground your reply in the captured context below. Reference the client, outcome,
or win themes by name if they are known. Do not ask for information already captured.

Respond with 1-2 sentences that:
1. Acknowledge their response warmly, referencing what was just discussed
2. Either continue the discussion naturally OR gently ask what they'd like to do next
3. Keep Sheldon's personality (energetic, supportive)

Keep it SHORT — 1-2 sentences max. Don't be verbose.

HARD RULE: You are a text-only interface. You CANNOT execute, build, draft, or create anything.
NEVER say you are starting work, drafting, building, or promise delivery by a specific time.
If the user wants to proceed, tell them to type "go" — that is the only way to queue a run."""

    user_prompt = f"""Captured context (known slots):
{known_block}

Project context excerpt:
{project_context[:2000] if project_context else "(none)"}

Recent conversation:
{recent_context}

User's acknowledgment: {user_message}

Respond briefly, referencing the captured context above."""

    try:
        response_text = claude_generate(
            system=system_prompt,
            user=user_prompt,
            temperature=0.4,
            max_tokens=150
        ).strip()
    except Exception:
        response_text = "Great! What would you like to tackle next? 🎯"

    msg = ConversationMessage(
        conversation_id=conv.id,
        role="assistant",
        content=response_text,
        metadata_json=json.dumps({"kind": "acknowledgment_response"}),
    )
    db.add(msg)
    db.commit()

    messages = _serialize_messages(db, conv.id)
    return {
        "conversation_id": conv.id,
        "messages": messages,
        "open_questions": [],
        "ready_for_confirmation": False,
        "plan_hash": None,
    }


def _update_conversation_summary(
    conv: "Conversation",
    state: "ConversationState",
    messages: list[dict],
) -> bool:
    """Generate and store a rolling summary of older conversation turns.

    Triggers at 10 messages (first summary) and refreshes at every 10th message
    thereafter (20, 30, …). Summarizes everything except the last 6 messages so
    the normal recent-history window remains verbatim.

    Returns True if the summary was updated; caller must call save_state() afterward.
    Non-blocking: failures are swallowed and return False.
    """
    from app.services.claude import claude_generate

    n = len(messages)
    if n < 10:
        return False
    if state.history_summary and n % 10 != 0:
        return False

    messages_to_summarize = messages[:-6]
    if not messages_to_summarize:
        return False

    transcript = "\n".join(
        f"{m.get('role', 'user').upper()}: {str(m.get('content') or '')[:800]}"
        for m in messages_to_summarize
        if str(m.get("content") or "").strip()
    )
    if not transcript.strip():
        return False

    system = (
        "You are a concise summarizer for a consulting copilot conversation. "
        "Produce a factual, third-person summary (max 200 words) covering: "
        "what the user is trying to accomplish, any client/outcome/audience/win-theme facts stated, "
        "key decisions made, and the current stage of the conversation. "
        "Do not include pleasantries or filler. Output plain prose."
    )
    user = f"Conversation transcript to summarize:\n\n{transcript}\n\nSummary:"

    try:
        summary = claude_generate(
            system=system,
            user=user,
            temperature=0.2,
            max_tokens=300,
        ).strip()
    except Exception:
        return False

    if not summary:
        return False

    state.history_summary = summary
    return True


def _extract_user_name(email: str) -> str:
    """Extract a friendly name from email address.

    Examples:
        john.doe@company.com → John Doe
        jane_smith@company.co.uk → Jane Smith
        user+tag@domain.com → User
    """
    if not email:
        return "there"

    # Get the part before @
    local_part = email.split("@")[0].lower()

    # Replace dots and underscores with spaces
    name_part = local_part.replace(".", " ").replace("_", " ")

    # Remove any +tag suffix
    if "+" in name_part:
        name_part = name_part.split("+")[0]

    # Title case and clean up
    words = [w for w in name_part.split() if w]
    if not words:
        return "there"

    # Capitalize first word
    return words[0].capitalize()


def _generate_greeting_message(user_name: str) -> str:
    """Generate a personalized greeting message using Sheldon's personality.

    Args:
        user_name: First name of the user

    Returns:
        Personalized greeting message with personality
    """
    return f"""👋 Hey {user_name}! Welcome to **Creative Studio**.

I'm Sheldon — think of me as your strategic thought partner. Not a vending machine that spits out decks, but a colleague who'll actually think through the problem with you.

**How I work best:**
💬 **Tell me about your project** — context, audience, goals. The more I understand, the sharper the output.
🎯 **We'll figure out the approach together** — I'll ask questions, suggest angles, debate trade-offs.
🚀 **When you're ready, say the word** — I'll build exactly what you need with quality checks built in.

So — what are you working on? I'm all ears."""


class CreateProjectRequest(BaseModel):
    name: str


class UpdateProjectSettingsRequest(BaseModel):
    qa_threshold: float | None = None
    max_qa_loops: int | None = None
    hard_gate_enabled: bool | None = None
    web_search_provider: str | None = None
    tavily_enabled: bool | None = None
    tavily_api_key: str | None = None


class ConversationMessageRequest(BaseModel):
    content: str


class DecisionAnswer(BaseModel):
    prompt_id: str
    selected_values: list[str]
    free_text: str | None = None


class ConversationDecisionRequest(BaseModel):
    conversation_id: str | None = None
    plan_hash: str | None = None
    answers: list[DecisionAnswer]


class ConversationConfirmRequest(BaseModel):
    conversation_id: str | None = None
    plan_hash: str | None = None


class OutlineSlideUpdate(BaseModel):
    title: str
    slide_type: str
    purpose: str | None = None


class ConversationOutlineUpdateRequest(BaseModel):
    conversation_id: str | None = None
    plan_hash: str | None = None
    slides: list[OutlineSlideUpdate]


class UserProjectPreferencesBody(BaseModel):
    """Lines merged into coordinator NonNegotiables (assemble_v2) for this user+project."""

    context_lines: list[str] | None = None
    # Optional counters for future behavioral-learning (v4 §5.1.1); stored opaque in JSON.
    learning_signals: dict[str, int] | None = None


class ScheduledTaskCreateBody(BaseModel):
    name: str
    instruction: str
    output_types: list[str] = []
    custom_output_types: list[str] = []
    output_type_representations: dict[str, str] = {}
    trigger_type: str = "interval"
    cadence_minutes: int = 60
    run_at: str | None = None
    timezone: str = "UTC"
    retry_limit: int = 3


class ScheduledTaskUpdateBody(BaseModel):
    name: str | None = None
    instruction: str | None = None
    output_types: list[str] | None = None
    custom_output_types: list[str] | None = None
    output_type_representations: dict[str, str] | None = None
    trigger_type: str | None = None
    cadence_minutes: int | None = None
    run_at: str | None = None
    timezone: str | None = None
    retry_limit: int | None = None
    status: str | None = None


def _detail(code: str, message: str, **extra: object) -> dict[str, object]:
    payload: dict[str, object] = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _build_plan_hash(
    *,
    instruction: str,
    template_ids: list[str],
    custom_output_types: list[str],
    reps: dict[str, str],
    content_skill_targets: dict[str, str] | None = None,
    regeneration_directive: str | None = None,
    discovery: dict | None = None,
) -> str:
    payload = json.dumps(
        {
            "instruction": instruction.strip(),
            "template_output_types": template_ids,
            "custom_output_types": custom_output_types,
            "output_type_representations": reps,
            "content_skill_targets": content_skill_targets or {},
            "regeneration_directive": (regeneration_directive or "").strip(),
            "discovery": _normalize_discovery(discovery or {}),
        },
        sort_keys=True,
    )
    return uuid.uuid5(uuid.NAMESPACE_URL, payload).hex


def _latest_assistant_plan_metadata(messages: list[dict]) -> dict | None:
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        metadata = msg.get("metadata")
        if isinstance(metadata, dict) and metadata.get("plan_hash"):
            return metadata
    return None


def _find_prior_plan_instruction(db: Session, project_id: str, exclude_conv_id: str | None = None) -> str | None:
    """
    Search the most recent conversations for this project for a plan message
    that has a stored instruction. Used to recover context for cross-session
    "generate again" requests when the current conversation has no prior plan.

    Returns the instruction string, or None if not found.
    """
    try:
        recent_convs = db.scalars(
            select(Conversation)
            .where(Conversation.project_id == project_id)
            .order_by(Conversation.updated_at.desc())
            .limit(5)
        ).all()
        for conv in recent_convs:
            if exclude_conv_id and conv.id == exclude_conv_id:
                continue
            msgs = _serialize_messages(db, conv.id)
            meta = _latest_assistant_plan_metadata(msgs)
            if meta:
                instruction = str(meta.get("instruction") or "").strip()
                if instruction:
                    return instruction
    except Exception:  # noqa: S110 — best-effort, non-fatal
        pass
    return None


def _sanitize_decision_answers(raw: object) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for k, v in raw.items():
        key = str(k or "").strip()
        if not key:
            continue
        values = [str(x).strip() for x in (v if isinstance(v, list) else []) if str(x).strip()]
        out[key] = values[:5]
    return out


def _build_decision_prompts(
    *,
    content: str,
    template_ids: list[str],
    custom_output_types: list[str],
    current_answers: dict[str, list[str]],
) -> tuple[list[dict], list[str], list[str], list[str]]:
    """Return (decision_prompts, unresolved_ids, blocking_questions, soft_hints).

    ``blocking_questions`` are tied 1-to-1 with ``unresolved_ids`` and gate
    confirmation.  ``soft_hints`` are advisory messages shown to the user but
    they never prevent plan confirmation.
    """
    is_proposal = bool({str(x).strip().lower() for x in (template_ids or [])} & _PROPOSAL_DISCOVERY_OUTPUT_TYPES)
    if not settings.instruction_decision_prompts_enabled and not (
        settings.proposal_discovery_prompts_enabled and is_proposal
    ):
        return [], [], [], []
    prompts: list[dict] = []
    unresolved: list[str] = []
    open_questions: list[str] = []
    soft_hints: list[str] = []
    deliverable_opts = [
        {"value": "proposal", "label": "Proposal"},
        {"value": "report", "label": "Report"},
        {"value": "sop", "label": "SOP"},
        {"value": "deck", "label": "Deck / presentation"},
    ]
    selected_primary = current_answers.get("primary_deliverable", [])
    prompts.append(
        {
            "id": "primary_deliverable",
            "label": "🎯 What's the primary deliverable?",
            "mode": "single_select",
            "required": True,
            "options": deliverable_opts,
            "selected_values": selected_primary[:1],
        }
    )
    if not selected_primary:
        unresolved.append("primary_deliverable")
        open_questions.append(
            "🎯 What's the primary deliverable? (This shapes everything—proposal, report, SOP, or deck?)"
        )

    if not template_ids and not custom_output_types:
        format_opts = [
            {"value": "process_map", "label": "Process map"},
            {"value": "docx", "label": "Word (DOCX)"},
            {"value": "pptx", "label": "Slides (PPTX)"},
            {"value": "xlsx", "label": "Spreadsheet (XLSX)"},
            {"value": "pdf", "label": "PDF"},
        ]
        selected_formats = current_answers.get("preferred_outputs", [])
        prompts.append(
            {
                "id": "preferred_outputs",
                "label": "✨ Which formats should we deliver?",
                "mode": "multi_select",
                "required": True,
                "options": format_opts,
                "selected_values": selected_formats[:5],
                "min_select": 1,
            }
        )
        if not selected_formats:
            unresolved.append("preferred_outputs")
            open_questions.append("✨ Which output formats work best for you? (Pick one or more: slides, Word, spreadsheet, PDF, or process map)")

    if len(content.split()) < 8:
        soft_hints.append("💡 Quick tip: More detail on scope, audience, and depth = better results. Worth adding?")

    if settings.proposal_discovery_prompts_enabled and is_proposal:
        narrative_selected = current_answers.get("narrative_arc", [])
        prompts.append(
            {
                "id": "narrative_arc",
                "label": "Story arc",
                "description": "How should the narrative unfold for this audience?",
                "mode": "single_select",
                "required": True,
                "allow_custom": True,
                "custom_placeholder": "Or describe your own storyline in 1–2 sentences…",
                "options": [
                    {
                        "value": "scqa",
                        "label": "Situation → Complication → Question → Answer",
                        "description": "Classic consulting arc. Frame today's state, the problem, the key question, then the recommendation.",
                    },
                    {
                        "value": "pyramid",
                        "label": "Recommendation-first (Pyramid)",
                        "description": "Lead with the answer, then back it up with supporting evidence. Best for senior, time-poor audiences.",
                    },
                    {
                        "value": "case_led",
                        "label": "Case-led story",
                        "description": "Anchor the narrative around a client case or success story and draw lessons for this client.",
                    },
                    {
                        "value": "compare",
                        "label": "Compare options",
                        "description": "Walk through 2–3 alternatives side-by-side, then land on a recommended option.",
                    },
                ],
                "selected_values": narrative_selected[:1],
            }
        )
        if not narrative_selected:
            unresolved.append("narrative_arc")
            open_questions.append(
                "Pick a story arc — or type your own — so Sheldon knows how to unfold the narrative."
            )

        audience_selected = current_answers.get("audience_role", [])
        prompts.append(
            {
                "id": "audience_role",
                "label": "Primary audience",
                "description": "Who will be reading this first? Sheldon tailors depth and tone to them.",
                "mode": "single_select",
                "required": True,
                "allow_custom": True,
                "custom_placeholder": "Or describe the audience (e.g. COO + transformation office)",
                "options": [
                    {
                        "value": "cfo",
                        "label": "CFO / Finance leadership",
                        "description": "Finance-led buyer: case for value, risk, and payback.",
                    },
                    {
                        "value": "board",
                        "label": "Board / ExCo",
                        "description": "Top-of-house: strategic narrative, 5-year arc, board-ready summaries.",
                    },
                    {
                        "value": "buying_committee",
                        "label": "Buying committee",
                        "description": "Mixed procurement / sponsor / IT committee evaluating vendors.",
                    },
                    {
                        "value": "mixed",
                        "label": "Mixed stakeholders",
                        "description": "Broad audience — Sheldon will balance depth across functions.",
                    },
                ],
                "selected_values": audience_selected[:1],
            }
        )
        if not audience_selected:
            unresolved.append("audience_role")
            open_questions.append("Who is the primary audience for this proposal?")

        length_selected = current_answers.get("slide_length_budget", [])
        prompts.append(
            {
                "id": "slide_length_budget",
                "label": "Deck length",
                "description": "How long should the first draft be? You can still edit slides later.",
                "mode": "single_select",
                "required": True,
                "allow_custom": True,
                "custom_placeholder": "Or type a specific slide count (e.g. 18)",
                "options": [
                    {"value": "8", "label": "8 slides (tight, exec summary style)"},
                    {"value": "10", "label": "10 slides (balanced, default)"},
                    {"value": "12", "label": "12 slides (room for detail + case study)"},
                    {"value": "15", "label": "15 slides (full narrative + appendix)"},
                ],
                "selected_values": length_selected[:1],
            }
        )
        if not length_selected:
            unresolved.append("slide_length_budget")
            open_questions.append("How many slides should the initial draft target?")

        tone_selected = current_answers.get("tone", [])
        prompts.append(
            {
                "id": "tone",
                "label": "Narrative tone",
                "description": "Pick the voice Sheldon should write in.",
                "mode": "single_select",
                "required": True,
                "allow_custom": False,
                "options": [
                    {
                        "value": "formal",
                        "label": "Formal",
                        "description": "Measured, reserved, full sentences. Board-room appropriate.",
                    },
                    {
                        "value": "consultative",
                        "label": "Consultative",
                        "description": "Structured and advisory — balanced between authority and dialogue.",
                    },
                    {
                        "value": "punchy",
                        "label": "Punchy",
                        "description": "Short, direct, impact-first — fewer words, sharper verbs.",
                    },
                ],
                "selected_values": tone_selected[:1],
            }
        )
        if not tone_selected:
            unresolved.append("tone")
            open_questions.append("Select the tone style for the proposal narrative.")

    return prompts, unresolved, open_questions, soft_hints


def _instruction_may_warrant_strategy_options(text: str) -> bool:
    s = (text or "").strip()
    if len(s.split()) < 8:
        return False
    t = s.lower()
    keys = (
        "analy",
        "dataset",
        "excel",
        "csv",
        "spreadsheet",
        "client data",
        "approach",
        "tradeoff",
        "evaluate",
        "hypothesis",
        "segment",
        "scenario",
    )
    return any(k in t for k in keys)


def _is_redo_followup(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    keys = ("redo", "regenerate", "rework", "rewrite", "revise", "try again", "again")
    return any(k in t for k in keys)


def _derive_content_skill_targets(
    *,
    instruction: str,
    template_ids: list[str],
    prior_plan_meta: dict | None = None,
    llm_skill_hint: dict | None = None,
) -> dict[str, str]:
    targets = derive_proposal_skill_targets(
        instruction=instruction, output_types=template_ids, base_targets=None, llm_skill_hint=llm_skill_hint
    )
    if prior_plan_meta and _is_redo_followup(instruction):
        prior_targets = prior_plan_meta.get("content_skill_targets")
        if isinstance(prior_targets, dict):
            for out in template_ids:
                prev = str(prior_targets.get(out) or "").strip()
                if prev:
                    targets[out] = prev
    return targets


def _build_regeneration_directive(content: str) -> str:
    if not _is_redo_followup(content):
        return ""
    return (
        "Regeneration directive: produce a materially different draft while preserving factual consistency. "
        "Change at least three dimensions: (1) storyline framing, (2) value-case structure and levers, "
        "(3) risk/mitigation articulation. Avoid near-verbatim reuse of prior section wording."
    )


def _persist_contextual_response(db: Session, conv: Conversation, user_message: str, prior_context: str) -> dict:
    """Generate a contextual response to a follow-up question based on prior messages.

    Instead of generating a plan, provide a direct answer to the user's question
    using the conversation history for context.
    """
    from app.services.claude import claude_generate

    system_prompt = """You are Sheldon, a helpful execution partner in an active project discussion.
The user has asked a follow-up question about previous context in the conversation.

Provide a direct, helpful response that:
1. References the recent context/findings mentioned
2. Answers their specific question directly
3. Offers next steps or recommendations if appropriate
4. Maintains Sheldon's personality (helpful, strategic, professional)

Keep it concise (2-3 sentences) unless the question requires more detail.
Do NOT offer generic recommendations - be specific to what was just discussed.
"""

    user_prompt = f"""Prior context from conversation:
{prior_context}

User's follow-up question: {user_message}

Provide a direct, contextual response to their question based on what was just discussed."""

    try:
        response_text = claude_generate(
            system=system_prompt,
            user=user_prompt,
            temperature=0.6,
            max_tokens=300
        ).strip()
    except Exception:
        # Fallback response
        response_text = (
            "Great question! Based on what we just discussed, let me help you tackle "
            "the key issues. Which area would you like to address first?"
        )

    msg = ConversationMessage(
        conversation_id=conv.id,
        role="assistant",
        content=response_text,
        metadata_json=json.dumps({"kind": "contextual_response"}),
    )
    db.add(msg)
    db.commit()

    messages = _serialize_messages(db, conv.id)
    return {
        "conversation_id": conv.id,
        "messages": messages,
        "open_questions": [],
        "ready_for_confirmation": False,
        "plan_hash": None,
    }


def _persist_out_of_scope_message(db: Session, conv: Conversation, user_request: str) -> dict:
    """Generate an LLM-based response for out-of-scope requests.

    Creates a funny yet professional message saying we don't support this yet,
    but they can log feedback for future features.
    """
    from app.services.claude import claude_generate

    system_prompt = """You are Sheldon, a helpful and witty digital teammate.
A user has asked for something outside your current capabilities.

Generate a SHORT (2-3 sentences max) response that:
1. Acknowledges what they asked for with humor and understanding
2. Explains it's not in your wheelhouse today in a funny, professional way
3. Suggests they log feedback for future features
4. Offers what you CAN help with (proposals, models, reports, documentation, etc.)

Keep it light and entertaining while maintaining professionalism. Use personality and wit.
Do NOT be apologetic or negative - be confident and fun about it.

Examples of great tone:
- "Love the ambition! 🚀 Flight booking isn't our jam yet, but we'd love to add it someday.
  For now, I'm your go-to for proposals, reports, and process documentation—log your feature request and we'll get working on it!"
- "That's a creative one! 😄 We're still building that superpower. How about I help you with something in our current toolkit instead—proposals, models, documentation?"
"""

    user_prompt = f"User request: {user_request}\n\nGenerate a short, witty response acknowledging this request is out of scope (no quotes, just the message):"

    try:
        response_text = claude_generate(
            system=system_prompt,
            user=user_prompt,
            temperature=0.7,
            max_tokens=200
        ).strip()
    except Exception:
        # Fallback if LLM unavailable
        response_text = (
            "That's a creative request! 😄 We don't support that just yet, but we'd love to hear your feedback. "
            "For now, I specialize in creating proposals, financial models, process documentation, and reports. "
            "What can I help you build today?"
        )

    msg = ConversationMessage(
        conversation_id=conv.id,
        role="assistant",
        content=response_text,
        metadata_json=json.dumps({"kind": "out_of_scope_response"}),
    )
    db.add(msg)
    db.commit()

    messages = _serialize_messages(db, conv.id)
    return {
        "conversation_id": conv.id,
        "messages": messages,
        "open_questions": [],
        "ready_for_confirmation": False,
        "plan_hash": None,
    }


def _persist_clarification_message(db: Session, conv: Conversation, user_message: str) -> dict:
    """Return a friendly clarification request without generating a plan."""

    clarification_content = """Hey! 👋 Looks like you're just getting warmed up.

I'm ready to dive into whatever you're working on. Just give me some context — for example:

💬 *"We're pitching a finance transformation to a mid-size bank"*
💬 *"I need to document our procurement process for an audit"*
💬 *"The CFO wants a cost-benefit analysis for the new ERP"*

Or if you already know what you want built, just say the word — *"Create a proposal in PPT"* and I'll get straight to it.

What's on your plate?"""

    msg = ConversationMessage(
        conversation_id=conv.id,
        role="assistant",
        content=clarification_content,
        metadata_json=json.dumps({"kind": "clarification_request"}),
    )
    db.add(msg)
    db.commit()

    messages = _serialize_messages(db, conv.id)
    return {
        "conversation_id": conv.id,
        "messages": messages,
        "open_questions": [],
        "ready_for_confirmation": False,
        "plan_hash": None,
    }


def _persist_assistant_plan_message(
    *,
    db: Session,
    conv: Conversation,
    content: str,
    instruction: str,
    template_ids: list[str],
    custom_output_types: list[str],
    output_type_representations: dict[str, str],
    rationale: str,
    decision_answers: dict[str, list[str]] | None = None,
    content_skill_targets: dict[str, str] | None = None,
    regeneration_directive: str | None = None,
    discovery: dict | None = None,
) -> dict:
    decision_answers = decision_answers or {}
    content_skill_targets = {
        str(k).strip(): str(v).strip()
        for k, v in (content_skill_targets or {}).items()
        if str(k).strip() and str(v).strip()
    }
    regeneration_directive = (regeneration_directive or "").strip()
    discovery = _normalize_discovery(discovery or {})
    if decision_answers:
        mapped: dict[str, object] = {}
        if decision_answers.get("audience_role"):
            mapped["audience"] = str(decision_answers.get("audience_role", [""])[0] or "").strip().lower()
        if decision_answers.get("narrative_arc"):
            mapped["narrative_arc"] = str(decision_answers.get("narrative_arc", [""])[0] or "").strip().lower()
        if decision_answers.get("tone"):
            mapped["tone"] = str(decision_answers.get("tone", [""])[0] or "").strip().lower()
        if decision_answers.get("slide_length_budget"):
            try:
                mapped["length_budget"] = {"pptx": int(str(decision_answers["slide_length_budget"][0]))}
            except Exception:
                pass
        discovery = _merge_discovery(discovery, mapped)

    # Backfill decision_answers from discovery for any fields not yet explicitly
    # answered. Discovery accumulates slot values from the whole conversation
    # (slot extraction, wiki enrichment, prior decisions) so anything already
    # identified there should count as resolved without re-asking the user.
    _backfill: dict[str, list[str]] = {}
    if not decision_answers.get("audience_role") and discovery.get("audience"):
        _backfill["audience_role"] = [str(discovery["audience"])]
    if not decision_answers.get("tone") and discovery.get("tone"):
        _backfill["tone"] = [str(discovery["tone"])]
    if not decision_answers.get("narrative_arc") and discovery.get("narrative_arc"):
        _backfill["narrative_arc"] = [str(discovery["narrative_arc"])]
    _lb = discovery.get("length_budget")
    if not decision_answers.get("slide_length_budget") and isinstance(_lb, dict) and _lb.get("pptx"):
        _backfill["slide_length_budget"] = [str(_lb["pptx"])]
    # For non-PPTX deliverables (docx/pdf) there are no "slides"; default to 10
    # pages so this prompt never blocks readiness when PPTX isn't in the output set.
    if not decision_answers.get("slide_length_budget") and "slide_length_budget" not in _backfill:
        _has_pptx = "pptx" in {str(t).strip().lower() for t in (template_ids or [])}
        if not _has_pptx:
            _backfill["slide_length_budget"] = ["10"]
    # Infer primary_deliverable from instruction keywords when not yet answered.
    if not decision_answers.get("primary_deliverable"):
        _instr_lower = (content or "").lower()
        if "proposal" in _instr_lower:
            _backfill["primary_deliverable"] = ["proposal"]
        elif "report" in _instr_lower:
            _backfill["primary_deliverable"] = ["report"]
        elif "sop" in _instr_lower or "standard operating" in _instr_lower:
            _backfill["primary_deliverable"] = ["sop"]
        elif "deck" in _instr_lower or "presentation" in _instr_lower or "slides" in _instr_lower:
            _backfill["primary_deliverable"] = ["deck"]
    if _backfill:
        decision_answers = {**decision_answers, **_backfill}

    decision_prompts, unresolved_prompt_ids, open_questions, soft_hints = _build_decision_prompts(
        content=content,
        template_ids=template_ids,
        custom_output_types=custom_output_types,
        current_answers=decision_answers,
    )
    strategy_dossier: dict | None = None
    # Skip strategy generation if the user already selected an approach — regenerating
    # produces new option IDs that never match the stored selection, causing an infinite loop.
    _strategy_already_selected = bool(decision_answers.get("execution_strategy"))
    if settings.strategy_options_planning_enabled and not _strategy_already_selected and _instruction_may_warrant_strategy_options(instruction):
        try:
            from app.services.strategy_plan import generate_strategy_options

            strategy_dossier = generate_strategy_options(instruction=instruction)
        except Exception:
            strategy_dossier = None
        opts = strategy_dossier.get("options") if isinstance(strategy_dossier, dict) else None
        if isinstance(opts, list) and len(opts) >= 2:
            strat_prompt = {
                "id": "execution_strategy",
                "label": "Choose an execution approach",
                "mode": "single_select",
                "required": True,
                "options": [
                    {"value": str(o["id"]), "label": str(o["title"])[:280]}
                    for o in opts
                    if isinstance(o, dict) and str(o.get("id") or "").strip() and str(o.get("title") or "").strip()
                ],
                "selected_values": (decision_answers.get("execution_strategy") or [])[:1],
            }
            if strat_prompt["options"]:
                decision_prompts = [strat_prompt] + decision_prompts
                # execution_strategy is advisory: shown in the panel so the user can
                # pick an approach, but it must NOT block ready_for_confirmation.
                # The user's preferred approach is already captured in the conversation
                # rationale/instruction, and is not required for generation.
    # When decision prompts are disabled, proposal discovery can still gate readiness.
    ready_for_confirmation = True if not settings.instruction_decision_prompts_enabled else len(unresolved_prompt_ids) == 0
    proposal_targets = {str(x).strip().lower() for x in (template_ids or []) if str(x).strip()}
    if settings.proposal_discovery_enabled and (proposal_targets & _PROPOSAL_DISCOVERY_OUTPUT_TYPES):
        ready_for_confirmation = ready_for_confirmation and _has_sufficient_discovery(discovery)
    display_open_questions = open_questions + soft_hints

    # ── Wiki-grounded project context (shared across outline generators) ──
    context_bundle: dict = {"text": "", "wiki_refs": []}
    try:
        context_bundle = _load_project_context_bundle(db, conv.project_id, instruction)
    except Exception:
        context_bundle = {"text": "", "wiki_refs": []}
    project_context_text: str = context_bundle.get("text") or ""
    wiki_context_refs: list[str] = list(context_bundle.get("wiki_refs") or [])

    template_set = {str(t).strip().lower() for t in template_ids}

    # ── Deck outline preview (PPTX proposals) ──
    deck_outline_preview: dict | None = None
    pptx_skill = (content_skill_targets or {}).get("pptx", "")
    if "pptx" in template_set and pptx_skill:
        try:
            deck_outline_preview = generate_deck_outline_preview(
                instruction=instruction,
                output_type="pptx",
                skill_id=pptx_skill or None,
                discovery=discovery,
                project_context=project_context_text or None,
            )
        except Exception:
            deck_outline_preview = None

    # ── Document outline preview (DOCX proposals) ──
    document_outline_preview: dict | None = None
    docx_skill = (content_skill_targets or {}).get("docx", "")
    if "docx" in template_set and docx_skill:
        try:
            document_outline_preview = generate_document_outline_preview(
                instruction=instruction,
                skill_id=docx_skill or None,
                discovery=discovery,
                project_context=project_context_text or None,
            )
        except Exception:
            document_outline_preview = None

    plan_hash = _build_plan_hash(
        instruction=instruction,
        template_ids=template_ids,
        custom_output_types=custom_output_types,
        reps=output_type_representations,
        content_skill_targets=content_skill_targets,
        regeneration_directive=regeneration_directive,
        discovery=discovery,
    )
    approval_reason = "Plan is ready for confirmation." if ready_for_confirmation else "Clarification required before confirmation."

    # Format plan with personality
    from app.services.agent_personality import format_plan_with_personality
    plan_with_personality = format_plan_with_personality(
        plan_summary=rationale,
        outputs=template_ids,
        custom_outputs=custom_output_types if custom_output_types else None,
        rationale=None,  # rationale already in plan_summary
    )

    # Keep technical plan_summary for metadata
    plan_summary = (
        f"Draft plan: {rationale} | outputs={', '.join(template_ids) if template_ids else 'none'} | "
        f"custom={', '.join(custom_output_types) if custom_output_types else 'none'}"
    )
    strategy_md = ""
    if isinstance(strategy_dossier, dict) and strategy_dossier.get("options"):
        from app.services.strategy_plan import format_strategy_dossier_markdown

        strategy_md = "\n\n" + format_strategy_dossier_markdown(strategy_dossier)

    # Assistant message body: conversational plan + concise CTA. We no longer
    # list open_questions inline (the Plan Decisions panel is the single source
    # of truth) and we no longer spell out the technical template ids here —
    # the UI already renders those structurally from metadata.
    cta = (
        "\n\n✓ Plan is ready — review the decisions panel on the right, then confirm to start execution."
        if ready_for_confirmation
        else "\n\n→ Open decisions are waiting on the right. Pick from the dropdowns or type your own answer, then I'll refresh the plan."
    )
    assistant_content = plan_with_personality + cta + strategy_md

    metadata_obj = {
        "template_output_types": template_ids,
        "custom_output_types": custom_output_types,
        "output_type_representations": output_type_representations,
        "content_skill_targets": content_skill_targets,
        "regeneration_directive": regeneration_directive,
        "requires_output_type_confirmation": True,
        "requires_user_approval": True,
        "ready_to_run": False,
        "approval_reason": approval_reason,
        "rationale": rationale,
        "instruction": instruction,
        "plan_summary": plan_summary,
        "open_questions": display_open_questions,
        "soft_hints": soft_hints,
        "decision_prompts": decision_prompts,
        "decision_answers": decision_answers,
        "discovery": discovery,
        "unresolved_prompt_ids": unresolved_prompt_ids,
        "ready_for_confirmation": ready_for_confirmation,
        "requires_confirmation": True,
        "plan_hash": plan_hash,
        "strategy_dossier": strategy_dossier,
        "deck_outline_preview": deck_outline_preview,
        "document_outline_preview": document_outline_preview,
        "wiki_context_refs": wiki_context_refs,
    }
    assistant_msg = ConversationMessage(
        conversation_id=conv.id,
        role="assistant",
        content=assistant_content,
        metadata_json=json.dumps(metadata_obj),
    )
    db.add(assistant_msg)
    conv.updated_at = datetime.now(IST).replace(tzinfo=None)
    db.commit()
    return {
        "conversation_id": conv.id,
        "template_output_types": template_ids,
        "custom_output_types": custom_output_types,
        "output_type_representations": output_type_representations,
        "content_skill_targets": content_skill_targets,
        "regeneration_directive": regeneration_directive,
        "requires_output_type_confirmation": True,
        "requires_user_approval": True,
        "ready_to_run": False,
        "approval_reason": approval_reason,
        "rationale": rationale,
        "plan_summary": plan_summary,
        "open_questions": display_open_questions,
        "soft_hints": soft_hints,
        "decision_prompts": decision_prompts,
        "decision_answers": decision_answers,
        "discovery": discovery,
        "unresolved_prompt_ids": unresolved_prompt_ids,
        "ready_for_confirmation": ready_for_confirmation,
        "requires_confirmation": True,
        "plan_hash": plan_hash,
        "deck_outline_preview": deck_outline_preview,
        "document_outline_preview": document_outline_preview,
        "wiki_context_refs": wiki_context_refs,
        "messages": _serialize_messages(db, conv.id),
    }


def _get_or_create_conversation(db: Session, *, pid: str, user_id: str, user: User | None = None) -> Conversation:
    conv = db.scalar(
        select(Conversation)
        .where(Conversation.project_id == pid, Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    if conv:
        return conv

    # Create new conversation with greeting
    conv = Conversation(
        id=f"conv_{uuid.uuid4().hex[:10]}",
        project_id=pid,
        user_id=user_id,
        title="Creative Studio",
    )
    db.add(conv)
    db.flush()

    # Add greeting message
    if user:
        user_name = _extract_user_name(user.email)
        greeting_content = _generate_greeting_message(user_name)
    else:
        # Fallback if user not provided
        greeting_content = _generate_greeting_message("there")

    greeting_msg = ConversationMessage(
        conversation_id=conv.id,
        role="assistant",
        content=greeting_content,
        metadata_json=json.dumps({"kind": "greeting", "greeting_type": "initial"}),
    )
    db.add(greeting_msg)
    db.commit()
    db.refresh(conv)
    return conv


def _serialize_messages(db: Session, conversation_id: str) -> list[dict]:
    rows = db.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.id.asc())
    ).all()
    out: list[dict] = []
    for row in rows:
        try:
            metadata = json.loads(row.metadata_json) if row.metadata_json else {}
            if not isinstance(metadata, dict):
                metadata = {}
        except Exception:
            metadata = {}
        out.append(
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "metadata": metadata,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return out


def _ensure_workspace_safe(project_id: str) -> None:
    try:
        ensure_workspace(project_id)
    except Exception:  # noqa: S110 — best-effort, non-fatal
        # Workspace creation is retried by downstream endpoints that require it.
        pass


@router.get("", response_model=dict[str, list[ProjectSummary]])
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(
        select(Project).join(Membership, Membership.project_id == Project.id).where(Membership.user_id == user.id)
    ).all()
    return {"items": [{"id": p.id, "name": p.name} for p in rows]}


@router.post("")
def create_project(
    body: CreateProjectRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = Project(id=f"p_{uuid.uuid4().hex[:10]}", name=body.name, created_by=user.id)
    db.add(project)
    db.add(Membership(id=f"m_{uuid.uuid4().hex[:10]}", project_id=project.id, user_id=user.id, role="Owner"))
    db.commit()
    background_tasks.add_task(_ensure_workspace_safe, project.id)
    return {"id": project.id, "name": project.name, "roles": ["Owner", "Editor", "Viewer"]}


@router.delete("/{pid}")
def delete_project(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    project = db.scalar(select(Project).where(Project.id == pid))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    membership = db.scalar(select(Membership).where(Membership.project_id == pid, Membership.user_id == user.id))
    if membership is None or membership.role != "Owner":
        raise HTTPException(status_code=403, detail="Insufficient project permissions")

    run_ids = db.scalars(select(Run.id).where(Run.project_id == pid)).all()
    if run_ids:
        db.execute(delete(RunEvent).where(RunEvent.run_id.in_(run_ids)))
        db.execute(delete(MemoryEvent).where(MemoryEvent.run_id.in_(run_ids)))
        db.execute(delete(ScheduledTaskRun).where(ScheduledTaskRun.run_id.in_(run_ids)))

    task_ids = db.scalars(select(ScheduledTask.id).where(ScheduledTask.project_id == pid)).all()
    if task_ids:
        db.execute(delete(ScheduledTaskRun).where(ScheduledTaskRun.task_id.in_(task_ids)))

    conv_ids = db.scalars(select(Conversation.id).where(Conversation.project_id == pid)).all()
    if conv_ids:
        db.execute(delete(ConversationMessage).where(ConversationMessage.conversation_id.in_(conv_ids)))

    db.execute(delete(ScheduledTaskRun).where(ScheduledTaskRun.project_id == pid))
    db.execute(delete(ScheduledTask).where(ScheduledTask.project_id == pid))
    db.execute(delete(MemoryItem).where(MemoryItem.project_id == pid))
    db.execute(delete(UserProjectPreference).where(UserProjectPreference.project_id == pid))
    db.execute(delete(ProjectMemoryProfile).where(ProjectMemoryProfile.project_id == pid))
    db.execute(delete(Conversation).where(Conversation.project_id == pid))
    db.execute(delete(Membership).where(Membership.project_id == pid))
    db.execute(delete(Run).where(Run.project_id == pid))
    db.execute(delete(ConsentLedger).where(ConsentLedger.project_id == pid))
    db.execute(delete(DPDPRightsRequest).where(DPDPRightsRequest.project_id == pid))
    db.execute(delete(Project).where(Project.id == pid))
    db.commit()

    project_workspace = workspace_path(pid)
    if project_workspace.exists():
        shutil.rmtree(project_workspace, ignore_errors=True)
    return {"project_id": pid, "deleted": True}


@router.get("/{pid}/settings")
def get_project_settings(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    membership = db.scalar(
        select(Project).join(Membership, Membership.project_id == Project.id).where(
            Project.id == pid, Membership.user_id == user.id
        )
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Insufficient project permissions")
    settings_path = workspace_path(pid) / "settings.json"
    response = {"project_id": pid, "qa_threshold": 0.8, "max_qa_loops": 2, "hard_gate_enabled": True}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                response.update(data)
        except Exception:  # noqa: S110 — best-effort, non-fatal
            pass
    if response.get("tavily_api_key"):
        response["tavily_configured"] = True
        del response["tavily_api_key"]
    return response


@router.put("/{pid}/settings")
def update_project_settings(
    pid: str,
    body: UpdateProjectSettingsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    # Owner/Editor can edit settings.
    membership = db.scalar(
        select(Membership).where(Membership.project_id == pid, Membership.user_id == user.id)
    )
    if not membership or membership.role not in {"Owner", "Editor"}:
        raise HTTPException(status_code=403, detail="Insufficient project permissions")

    ensure_workspace(pid)
    current = {"qa_threshold": 0.8, "max_qa_loops": 2, "hard_gate_enabled": True}
    settings_path = workspace_path(pid) / "settings.json"
    if settings_path.exists():
        try:
            parsed = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                current.update(parsed)
        except Exception:  # noqa: S110 — best-effort, non-fatal
            pass
    if body.qa_threshold is not None:
        current["qa_threshold"] = max(0.0, min(1.0, float(body.qa_threshold)))
    if body.max_qa_loops is not None:
        current["max_qa_loops"] = max(1, min(5, int(body.max_qa_loops)))
    if body.hard_gate_enabled is not None:
        current["hard_gate_enabled"] = bool(body.hard_gate_enabled)
    if body.web_search_provider is not None:
        provider = body.web_search_provider.strip().lower() if body.web_search_provider else ""
        if provider in {"brave", "google", "tavily", ""}:
            current["web_search_provider"] = provider if provider else None
        else:
            raise HTTPException(status_code=400, detail="Invalid web_search_provider")
    if body.tavily_enabled is not None:
        current["tavily_enabled"] = bool(body.tavily_enabled)
    if body.tavily_api_key is not None:
        current["tavily_api_key"] = body.tavily_api_key.strip() if body.tavily_api_key else ""
    settings_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    response = {"project_id": pid}
    response.update({k: v for k, v in current.items() if k != "tavily_api_key"})
    if current.get("tavily_api_key"):
        response["tavily_configured"] = True
    return response


@router.get("/{pid}/conversation")
def get_project_conversation(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    conv = _get_or_create_conversation(db, pid=pid, user_id=user.id, user=user)
    return {"conversation_id": conv.id, "messages": _serialize_messages(db, conv.id)}


@router.post("/{pid}/conversation/messages")
def post_project_conversation_message(
    pid: str,
    body: ConversationMessageRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return _post_project_conversation_message_impl(pid, body, user, db)
    except HTTPException:
        raise
    except Exception as exc:
        _LOG.exception("conversation_message_failed project=%s user=%s err=%s", pid, getattr(user, "id", "?"), exc)
        raise HTTPException(status_code=500, detail=f"conversation_message_failed: {type(exc).__name__}: {str(exc)[:300]}")


def _handle_collaborative_building(
    *,
    db,
    conv,
    pid: str,
    content: str,
    prior_messages: list[dict],
    state,
    merged_discovery: dict,
    project_context: str,
    decision,
    template_ids: list[str],
    output_type_representations: dict,
    content_skill_hint,
    custom_output_types: list[str],
    combined_instruction: str,
    rationale: str,
    resolved_wiki_refs: list[str],
    canonical_missing_slots: list[str],
    prior_plan_meta,
    user,
) -> dict:
    """Route the conversation through the collaborative story-building states.

    States handled here:
      new / exploring / discovery (all slots captured) → storyline_building
      storyline_building → slide_negotiation
      slide_negotiation → structure_agreed
      structure_agreed → plan generation (same as original flow)
    """
    from app.services.storyline_builder import (
        ARC_LIBRARY,
        parse_arc_from_user_message,
        propose_arcs,
        save_agreed_arc,
    )
    from app.services.slide_negotiator import (
        ARC_BLUEPRINTS,
        assemble_outline_from_decisions,
        load_agreed_slides,
        parse_slide_feedback,
        propose_slide,
        save_agreed_slide,
    )

    current_state = state.state

    # ── 1. Enter storyline_building when discovery is freshly complete ────────
    if current_state not in {"storyline_building", "slide_negotiation", "structure_agreed"}:
        # All slots captured; start the arc proposal.
        state.state = "storyline_building"
        state.pending_questions = []
        state.deliverable = {
            "template_ids": template_ids,
            "representations": output_type_representations,
            "content_skill_hint": content_skill_hint,
        }
        stamp_router(state, intent=decision.intent, confidence=decision.confidence, rationale="collaborative_building_start")
        save_state(conv, state)
        db.flush()

        history_text = "\n".join(
            f"{m.get('role', 'user')}: {str(m.get('content') or '').strip()}"
            for m in prior_messages[-15:]
            if str(m.get("content") or "").strip()
        )
        proposal = propose_arcs(
            discovery_slots=merged_discovery,
            project_context=project_context,
            conversation_history=history_text,
        )
        msg = ConversationMessage(
            conversation_id=conv.id,
            role="assistant",
            content=proposal["message"],
            metadata_json=json.dumps(proposal["metadata"]),
        )
        db.add(msg)
        conv.updated_at = datetime.now(IST).replace(tzinfo=None)
        db.commit()
        return {
            "conversation_id": conv.id,
            "messages": _serialize_messages(db, conv.id),
            "open_questions": [],
            "ready_for_confirmation": False,
            "plan_hash": None,
            "collaborative_state": "storyline_building",
        }

    # ── 2. Handle arc agreement / redirection in storyline_building ──────────
    if current_state == "storyline_building":
        arc_key = parse_arc_from_user_message(content)
        if arc_key == "__agree_with_recommendation__":
            # Use whatever was stored in slots or default to scqa.
            arc_key = str(state.slots.get("storyline", {}).get("arc") or "scqa").strip()
            if arc_key not in ARC_LIBRARY:
                arc_key = "scqa"

        if arc_key and arc_key in ARC_LIBRARY:
            # User agreed on this arc — save and move to slide_negotiation.
            save_agreed_arc(db, project_id=pid, arc_key=arc_key, arc_rationale=f"user selected {arc_key}")
            state.slots["storyline"] = {"arc": arc_key, "agreed": True}
            # Determine total slides from blueprint.
            blueprint = ARC_BLUEPRINTS.get(arc_key, ARC_BLUEPRINTS["scqa"])
            total_slides = len(blueprint)
            state.slots["current_slide_index"] = 0
            state.slots["total_slides"] = total_slides
            state.slots["slide_decisions"] = []
            state.state = "slide_negotiation"
            stamp_router(state, intent=decision.intent, confidence=decision.confidence, rationale=f"arc_agreed_{arc_key}")
            save_state(conv, state)
            db.flush()

            # Confirm arc choice and propose slide 1.
            slide_result = propose_slide(
                slide_index=0,
                total_slides=total_slides,
                arc_key=arc_key,
                discovery_slots=merged_discovery,
                project_context=project_context,
                prior_slide_decisions=[],
            )
            arc_def = ARC_LIBRARY[arc_key]
            message = (
                f"Locked in — **{arc_def['name']}** it is.\n\n"
                f"Now let's build the slides together. I'll propose one at a time and we'll agree on each before moving on.\n\n"
                + slide_result["message"]
            )
            msg = ConversationMessage(
                conversation_id=conv.id,
                role="assistant",
                content=message,
                metadata_json=json.dumps({
                    "kind": "slide_proposal",
                    "arc_agreed": arc_key,
                    "slide": slide_result["slide"],
                }),
            )
            db.add(msg)
            conv.updated_at = datetime.now(IST).replace(tzinfo=None)
            db.commit()
            return {
                "conversation_id": conv.id,
                "messages": _serialize_messages(db, conv.id),
                "open_questions": [],
                "ready_for_confirmation": False,
                "plan_hash": None,
                "collaborative_state": "slide_negotiation",
            }

        # User gave feedback on the arc but didn't select one — re-engage conversationally.
        stamp_router(state, intent=decision.intent, confidence=decision.confidence, rationale="storyline_feedback")
        save_state(conv, state)
        db.flush()
        return _persist_conversational_response(
            db,
            conv,
            content,
            prior_messages,
            slots=merged_discovery,
            project_context=project_context,
            missing_slots=[],
            wiki_refs=resolved_wiki_refs,
            already_surfaced_refs=state.surfaced_wiki_refs,
            router_intent=decision.intent,
            router_confidence=decision.confidence,
            project_id=pid,
            history_summary=state.history_summary,
        )

    # ── 3. Handle slide agreement / modification ─────────────────────────────
    if current_state == "slide_negotiation":
        arc_key = str(state.slots.get("storyline", {}).get("arc") or "scqa").strip()
        if arc_key not in ARC_BLUEPRINTS:
            arc_key = "scqa"
        current_index = int(state.slots.get("current_slide_index") or 0)
        total_slides = int(state.slots.get("total_slides") or len(ARC_BLUEPRINTS.get(arc_key, [])))
        slide_decisions: list[dict] = state.slots.get("slide_decisions") if isinstance(state.slots.get("slide_decisions"), list) else []

        feedback = parse_slide_feedback(content)

        if feedback == "agree":
            # Load the last proposed slide from messages and save it.
            # _serialize_messages already parses metadata_json into a dict.
            last_proposal: dict = {}
            for m in reversed(prior_messages):
                meta = m.get("metadata")
                if isinstance(meta, dict) and meta.get("kind") == "slide_proposal":
                    last_proposal = meta.get("slide") or {}
                    break
            if not last_proposal:
                last_proposal = {"slide_num": current_index + 1, "title": f"Slide {current_index + 1}", "slide_type": "bullets", "key_message": ""}
            last_proposal["agreed"] = True
            save_agreed_slide(db, project_id=pid, slide=last_proposal)
            _LOG.info(f"DEBUG: appending to slide_decisions: {last_proposal}")
            slide_decisions.append(last_proposal)
            current_index += 1
            state.slots["current_slide_index"] = current_index
            state.slots["slide_decisions"] = slide_decisions

            if current_index >= total_slides:
                # All slides agreed — move to structure_agreed.
                state.state = "structure_agreed"
                stamp_router(state, intent=decision.intent, confidence=decision.confidence, rationale="all_slides_agreed")
                save_state(conv, state)
                db.flush()
                # Build a summary message.
                from app.services.slide_negotiator import SLIDE_TYPE_LABELS
                summary_lines = [f"All {total_slides} slides agreed! Here's the full deck structure — review before I render:\n"]
                for i, s in enumerate(slide_decisions):
                    slide_type = str(s.get("slide_type") or "bullets")
                    type_label = SLIDE_TYPE_LABELS.get(slide_type, slide_type)
                    evidence = str(s.get("evidence_source") or "").strip()
                    line = f"**{i+1}. {s.get('title', f'Slide {i+1}')}** _{type_label}_ — {s.get('key_message', '')}"
                    if evidence:
                        line += f" _(source: {evidence})_"
                    summary_lines.append(line)
                summary_lines.append(
                    "\nHappy with this structure? Say **'go'** or **'build it'** to render the deck, "
                    "or tell me what to change."
                )
                summary_message = "\n".join(summary_lines)
                _LOG.info(f"DEBUG: structure_summary slide_decisions: {slide_decisions}")
                msg = ConversationMessage(
                    conversation_id=conv.id,
                    role="assistant",
                    content=summary_message,
                    metadata_json=json.dumps({
                        "kind": "structure_summary",
                        "slides": slide_decisions,
                        "ready_to_build": True,
                    }),
                )
                db.add(msg)
                conv.updated_at = datetime.now(IST).replace(tzinfo=None)
                db.commit()
                return {
                    "conversation_id": conv.id,
                    "messages": _serialize_messages(db, conv.id),
                    "open_questions": [],
                    "ready_for_confirmation": True,
                    "plan_hash": None,
                    "collaborative_state": "structure_agreed",
                }

            # More slides to go — propose the next one.
            save_state(conv, state)
            db.flush()
            slide_result = propose_slide(
                slide_index=current_index,
                total_slides=total_slides,
                arc_key=arc_key,
                discovery_slots=merged_discovery,
                project_context=project_context,
                prior_slide_decisions=slide_decisions,
            )
            msg = ConversationMessage(
                conversation_id=conv.id,
                role="assistant",
                content=slide_result["message"],
                metadata_json=json.dumps(slide_result["metadata"]),
            )
            db.add(msg)
            conv.updated_at = datetime.now(IST).replace(tzinfo=None)
            db.commit()
            return {
                "conversation_id": conv.id,
                "messages": _serialize_messages(db, conv.id),
                "open_questions": [],
                "ready_for_confirmation": False,
                "plan_hash": None,
                "collaborative_state": "slide_negotiation",
            }

        # feedback == "modify" — re-propose the same slide incorporating user feedback.
        save_state(conv, state)
        db.flush()
        slide_result = propose_slide(
            slide_index=current_index,
            total_slides=total_slides,
            arc_key=arc_key,
            discovery_slots=merged_discovery,
            project_context=project_context,
            prior_slide_decisions=slide_decisions,
            user_feedback=content,
        )
        msg = ConversationMessage(
            conversation_id=conv.id,
            role="assistant",
            content="Revised — how does this look?\n\n" + slide_result["message"],
            metadata_json=json.dumps(slide_result["metadata"]),
        )
        db.add(msg)
        conv.updated_at = datetime.now(IST).replace(tzinfo=None)
        db.commit()
        return {
            "conversation_id": conv.id,
            "messages": _serialize_messages(db, conv.id),
            "open_questions": [],
            "ready_for_confirmation": False,
            "plan_hash": None,
            "collaborative_state": "slide_negotiation",
        }

    # ── 4. structure_agreed: user said 'go' / 'build it' → generate plan ────
    if current_state == "structure_agreed":
        # Assemble deck_outline_preview from agreed MemoryItems, then fall through
        # to the normal plan generation path below.
        from app.services.slide_negotiator import assemble_outline_from_decisions
        agreed_outline = assemble_outline_from_decisions(db, project_id=pid)
        # Store the assembled outline in deliverable so the plan builder picks it up.
        state.deliverable = {
            "template_ids": template_ids,
            "representations": output_type_representations,
            "content_skill_hint": content_skill_hint,
            "deck_outline_preview": {"slides": agreed_outline},
        }
        state.state = "ready_to_plan"
        stamp_router(state, intent=decision.intent, confidence=decision.confidence, rationale="structure_agreed_go")
        save_state(conv, state)
        db.flush()
        # Fall through to normal plan generation (checkpoint_scope block below).
        # We rebuild the local variables expected by that block.
        pass

    # Fall through to normal plan generation.
    with checkpoint_scope(
        db,
        "post_project_conversation_message.plan_commit",
        metadata={"project_id": pid, "conversation_id": conv.id},
    ) as cp_plan:
        state.state = "ready_to_plan"
        state.pending_questions = []
        state.deliverable = state.deliverable or {
            "template_ids": template_ids,
            "representations": output_type_representations,
            "content_skill_hint": content_skill_hint,
        }
        stamp_router(state, intent=decision.intent, confidence=decision.confidence, rationale=rationale)
        save_state(conv, state)
        db.flush()
        cp_plan.mark("state_ready_to_plan_flushed")

        content_skill_targets = _derive_content_skill_targets(
            instruction=combined_instruction,
            template_ids=template_ids,
            prior_plan_meta=prior_plan_meta if isinstance(prior_plan_meta, dict) else None,
            llm_skill_hint=content_skill_hint,
        )
        regeneration_directive = _build_regeneration_directive(content)
        prior_decision_answers = _sanitize_decision_answers(prior_plan_meta.get("decision_answers")) if isinstance(prior_plan_meta, dict) else {}
        response = _persist_assistant_plan_message(
            db=db,
            conv=conv,
            content=content,
            instruction=combined_instruction,
            template_ids=template_ids,
            custom_output_types=custom_output_types,
            output_type_representations=output_type_representations,
            rationale=rationale,
            decision_answers=prior_decision_answers,
            content_skill_targets=content_skill_targets,
            regeneration_directive=regeneration_directive,
            discovery=merged_discovery,
        )
        state.state = "plan_proposed"
        save_state(conv, state)
        cp_plan.mark("assistant_plan_pre_commit")
        db.commit()
        cp_plan.mark("assistant_plan_committed")
    response["memory_quick_add"] = {
        "memory_page_path": "/memory",
        "batch_api_relative": f"/api/memory/{pid}/batch",
        "hint": "Save durable facts to Memory (or batch API after review); they are merged into run context when compaction is enabled.",
    }
    return response


def _post_project_conversation_message_impl(
    pid: str,
    body: ConversationMessageRequest,
    user: User,
    db: Session,
) -> dict:
    from app.services.run_budget import project_token_context
    with project_token_context(pid):
        return _post_project_conversation_message_inner(pid, body, user, db)


def _post_project_conversation_message_inner(
    pid: str,
    body: ConversationMessageRequest,
    user: User,
    db: Session,
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content must not be empty")
    conv = _get_or_create_conversation(db, pid=pid, user_id=user.id, user=user)

    with checkpoint_scope(
        db,
        "post_project_conversation_message",
        metadata={"project_id": pid, "conversation_id": conv.id, "user_id": user.id},
    ) as cp:
        cp.mark("user_message_received")
        user_msg = ConversationMessage(
            conversation_id=conv.id,
            role="user",
            content=content[:6000],
            metadata_json="{}",
        )
        db.add(user_msg)
        db.flush()
        cp.mark("user_message_flushed")

        # Fast-path routing only for obvious greetings/acknowledgments.
        prior_messages = _serialize_messages(db, conv.id)
        prior_plan_meta = _latest_assistant_plan_metadata(prior_messages)
        state = load_state(conv)
        summary_updated = _update_conversation_summary(conv, state, prior_messages)

        # Fast-paths only apply to fresh conversations with no established context.
        # Once an assistant has responded or state has advanced, short messages like
        # "ok", "yes", or "thanks" must go through the full LLM path so context is preserved.
        has_prior_context = (
            any(m.get("role") == "assistant" for m in prior_messages)
            or state.state not in {"new", "exploring"}
        )

        if _is_vague_instruction(content) and not has_prior_context:
            state.state = "exploring"
            stamp_router(state, intent="greeting", confidence=1.0, rationale="vague_instruction_fast_path")
            save_state(conv, state)
            db.flush()
            cp.mark("fast_path_clarification_flushed")
            return _persist_clarification_message(db, conv, content)

        if _is_acknowledgment(content) and not has_prior_context:
            # Preserve current state — do not reset to "exploring"
            stamp_router(state, intent="ack", confidence=1.0, rationale="acknowledgment_fast_path")
            save_state(conv, state)
            db.flush()
            cp.mark("fast_path_ack_flushed")
            try:
                context_bundle = _load_project_context_bundle(db, pid, content)
            except Exception:
                context_bundle = {"text": "", "wiki_refs": []}
            return _persist_acknowledgment_response(
                db,
                conv,
                content,
                prior_messages,
                slots=state.slots,
                project_context=str(context_bundle.get("text") or ""),
            )

    # ── Auto-execute: user says 'go' — execute existing plan or generate+execute ──
    if _is_execute_now_intent(content) and state.state not in {"run_queued", "done"}:
        # Case 1: a plan message already exists → execute it directly.
        if (
            isinstance(prior_plan_meta, dict)
            and prior_plan_meta.get("plan_hash")
            and prior_plan_meta.get("template_output_types")
        ):
            return _execute_plan_now(
                db=db, conv=conv, pid=pid, user=user,
                plan_meta=prior_plan_meta, state=state,
            )

        # Case 2: no plan yet, but state.deliverable has template_ids from discovery.
        # Skip the collaborative flow and generate + execute in one shot.
        _deliverable = state.deliverable if isinstance(state.deliverable, dict) else {}
        _template_ids = [str(x) for x in (_deliverable.get("template_ids") or []) if str(x).strip()]
        if _template_ids:
            # Build instruction from user messages in conversation history.
            _instruction = " ".join(
                str(m.get("content") or "").strip()
                for m in prior_messages
                if m.get("role") == "user" and str(m.get("content") or "").strip()
                and not _is_execute_now_intent(str(m.get("content") or ""))
            ).strip() or content
            return _generate_and_execute_plan(
                db=db, conv=conv, pid=pid, user=user, state=state,
                content=content,
                instruction=_instruction,
                template_ids=_template_ids,
                custom_output_types=_normalize_custom_output_types(
                    [str(x) for x in (_deliverable.get("custom_output_types") or []) if str(x).strip()]
                ),
                output_type_representations=_normalize_output_type_representations(
                    _deliverable.get("representations") or {}
                ),
                content_skill_hint=_deliverable.get("content_skill_hint"),
                prior_messages=prior_messages,
            )

    available_output_types = [
        item for item in _load_output_types() if isinstance(item, dict) and isinstance(item.get("output_type_id"), str)
    ]
    history_prompt = "\n".join(
        f"{m.get('role', 'user')}: {str(m.get('content') or '').strip()}"
        for m in prior_messages[-20:]
        if str(m.get("content") or "").strip()
    )
    base_instruction = str((prior_plan_meta or {}).get("instruction") or "").strip()
    if _is_redo_followup(content) and base_instruction:
        combined_instruction = f"{base_instruction}\n\nUser follow-up: {content}".strip()
    elif _is_redo_followup(content) and not base_instruction:
        recovered = _find_prior_plan_instruction(db, pid, exclude_conv_id=conv.id)
        if recovered:
            combined_instruction = f"{recovered}\n\nUser follow-up: {content}".strip()
        else:
            state.state = "exploring"
            stamp_router(state, intent="clarify", confidence=0.5, rationale="redo_without_context")
            save_state(conv, state)
            db.flush()
            return _persist_clarification_message(db, conv, content)
    else:
        combined_instruction = f"{history_prompt}\nuser: {content}".strip()

    # Extract discovery answers on every turn (rule-based + LLM), then pass merged slots
    # into router so we avoid re-asking already supplied inputs.
    extracted_fast = _extract_discovery_answers_fast(content)
    extracted_llm = _extract_discovery_answers(content, prior_messages)
    extracted_wiki: dict[str, object] = {}
    wiki_source_refs: list[str] = []
    if settings.wiki_aware_discovery_enabled:
        try:
            extracted_wiki, wiki_source_refs = _extract_discovery_answers_from_wiki(
                project_id=pid,
                user_message=content,
                prior_messages=prior_messages,
            )
        except Exception as exc:
            _LOG.warning("wiki slot extractor failed for project %s conversation %s: %s", pid, conv.id, exc)
            extracted_wiki, wiki_source_refs = {}, []
    premerged_slots = _merge_discovery(state.slots, extracted_fast)
    premerged_slots = _merge_discovery(premerged_slots, extracted_llm)
    premerged_slots = _merge_discovery(premerged_slots, extracted_wiki)
    if extracted_fast or extracted_llm or extracted_wiki:
        user_msg.metadata_json = json.dumps(
            {
                "kind": "discovery_answer",
                "captured": True,
                "discovery": premerged_slots,
                "sources": {
                    "fast": bool(extracted_fast),
                    "llm": bool(extracted_llm),
                    "wiki": bool(extracted_wiki),
                },
                "wiki_refs": wiki_source_refs[:8],
            }
        )
        try:
            db.flush()
        except Exception:
            _LOG.warning("failed to flush discovery metadata for conv %s", conv.id)
    existing_slots = state.slots if isinstance(state.slots, dict) else {}
    state.slots = {**existing_slots, **premerged_slots}
    for slot_key in ("client", "outcome", "win_themes", "audience"):
        val = premerged_slots.get(slot_key)
        if val is not None and str(val).strip() not in {"", "[]", "{}"}:
            try:
                record_discovery_answer(
                    db,
                    project_id=pid,
                    user_id=user.id,
                    slot_key=slot_key,
                    value=val,
                )
            except Exception:
                _LOG.warning("record_discovery_answer failed for slot %s project %s", slot_key, pid)
    if summary_updated:
        save_state(conv, state)
        try:
            db.flush()
        except Exception:
            _LOG.warning("failed to flush summary state for conv %s", conv.id)

    try:
        context_bundle = _load_project_context_bundle(db, pid, combined_instruction)
    except Exception:
        context_bundle = {"text": "", "wiki_refs": []}
    project_context = str(context_bundle.get("text") or "")
    context_wiki_refs = context_bundle.get("wiki_refs") if isinstance(context_bundle.get("wiki_refs"), list) else []
    resolved_wiki_refs = list(dict.fromkeys([*wiki_source_refs, *[str(x).strip() for x in context_wiki_refs if str(x).strip()]]))
    memory_profile = get_aggregated_profile(db, project_id=pid, user_id=user.id)
    decision = route_turn(
        user_message=content,
        conv_state=state.state,
        conv_slots=premerged_slots,
        recent_messages=prior_messages,
        project_context=project_context,
        available_output_types=available_output_types,
        history_summary=state.history_summary,
        memory_profile=memory_profile,
    )
    try:
        record_routing_decision(
            db,
            project_id=pid,
            user_id=user.id,
            decision_type=decision.intent,
            confidence=decision.confidence,
            outcome=decision.rationale or "router_decision",
        )
    except Exception:
        _LOG.warning("record_routing_decision failed for project %s", pid)

    merged_discovery = _merge_discovery(premerged_slots, decision.extracted_slots)
    if decision.extracted_slots and not (extracted_fast or extracted_llm):
        user_msg.metadata_json = json.dumps({"kind": "discovery_answer", "discovery": merged_discovery, "captured": True})
        db.flush()
    # Preserve non-discovery slots (slide negotiation, storyline, etc.) while
    # refreshing discovery slots with the latest extraction.
    existing_slots = state.slots if isinstance(state.slots, dict) else {}
    state.slots = {**existing_slots, **merged_discovery}
    canonical_missing_slots = _required_discovery_missing_slots(merged_discovery)
    wiki_prefilled_slots = [
        slot for slot in ("client", "outcome", "win_themes")
        if slot not in _required_discovery_missing_slots(extracted_wiki)
    ] if extracted_wiki else []

    deliverable = state.deliverable if isinstance(state.deliverable, dict) else {}
    template_ids = [str(x).strip() for x in decision.output_types if str(x).strip()]
    if not template_ids:
        template_ids = [
            str(x).strip()
            for x in (deliverable.get("template_ids") if isinstance(deliverable.get("template_ids"), list) else [])
            if str(x).strip()
        ]
    output_type_representations = (
        decision.representations if isinstance(decision.representations, dict) else {}
    ) or (
        deliverable.get("representations") if isinstance(deliverable.get("representations"), dict) else {}
    )
    # Fallback to keyword-based recommender when the LLM router produced no
    # output types. Preserves graceful degradation when Claude is unavailable
    # and keeps the existing conftest stub point intact.
    fallback_custom_output_types: list[str] = []
    if not template_ids:
        try:
            rec_ids, rec_custom, rec_reps, rec_rationale, rec_hint = _recommend_output_types(
                combined_instruction, available_output_types
            )
        except Exception:
            rec_ids, rec_custom, rec_reps, rec_rationale, rec_hint = ([], [], {}, "", None)
        rec_ids = [str(x).strip() for x in (rec_ids or []) if str(x).strip()]
        if rec_ids:
            template_ids = rec_ids
            if not output_type_representations and isinstance(rec_reps, dict):
                output_type_representations = rec_reps
            if not decision.rationale and rec_rationale:
                decision.rationale = str(rec_rationale)
            if rec_hint and not decision.content_skill_hint and isinstance(rec_hint, dict):
                decision.content_skill_hint = rec_hint
            fallback_custom_output_types = [str(x).strip() for x in (rec_custom or []) if str(x).strip()]
    content_skill_hint = (
        decision.content_skill_hint
        if isinstance(decision.content_skill_hint, dict)
        else (deliverable.get("content_skill_hint") if isinstance(deliverable.get("content_skill_hint"), dict) else None)
    )
    custom_output_types: list[str] = list(fallback_custom_output_types)
    rationale = decision.rationale or "Recommended by conversation router."

    recent_text = "\n".join(str(m.get("content") or "") for m in prior_messages[-8:])
    if decision.intent == "out_of_scope":
        if decision.confidence >= 0.8 and not _contains_deliverable_signal(recent_text):
            state.state = "exploring"
            state.pending_questions = []
            stamp_router(state, intent=decision.intent, confidence=decision.confidence, rationale=rationale)
            save_state(conv, state)
            db.flush()
            return _persist_out_of_scope_message(db, conv, content)
        decision = fallback_decision(
            state=state.state,
            slots=state.slots,
            reason="out_of_scope_low_conf_or_deliverable_detected",
        )

    proposal_detected = (
        _is_proposal_instruction(combined_instruction, template_ids)
        or _has_proposal_slot_signal(merged_discovery)
    )
    if settings.proposal_discovery_enabled and proposal_detected:
        missing_slots = list(dict.fromkeys(
            canonical_missing_slots
        ))
        if missing_slots:
            state.state = "discovery"
            state.pending_questions = missing_slots
            state.deliverable = {
                "template_ids": template_ids,
                "representations": output_type_representations,
                "content_skill_hint": content_skill_hint,
            }
            stamp_router(state, intent=decision.intent, confidence=decision.confidence, rationale=rationale)
            save_state(conv, state)
            db.flush()
            return _propose_discovery_questions(
                db,
                conv,
                combined_instruction,
                prior_messages,
                missing_slots=missing_slots,
                wiki_context=project_context if settings.wiki_aware_discovery_enabled else None,
                wiki_prefilled_slots=wiki_prefilled_slots,
                conv_slots=merged_discovery,
            )
        # Slots captured but output format not resolved yet — ask the user to pick
        # (PPTX vs DOCX) instead of falling back to generic conversation.
        if not template_ids:
            state.state = "ready_to_plan"
            state.pending_questions = ["output_format"]
            state.deliverable = {
                "template_ids": [],
                "representations": output_type_representations,
                "content_skill_hint": content_skill_hint,
            }
            stamp_router(
                state,
                intent=decision.intent,
                confidence=max(decision.confidence, 0.6),
                rationale="proposal_slots_complete_awaiting_format",
            )
            save_state(conv, state)
            db.flush()
            if resolved_wiki_refs:
                state.surfaced_wiki_refs = list(dict.fromkeys([*state.surfaced_wiki_refs, *resolved_wiki_refs]))
                save_state(conv, state)
                db.flush()
            return _persist_conversational_response(
                db,
                conv,
                content,
                prior_messages,
                slots=merged_discovery,
                project_context=project_context,
                missing_slots=["output_format"],
                wiki_refs=resolved_wiki_refs,
                already_surfaced_refs=state.surfaced_wiki_refs,
                router_intent=decision.intent,
                router_confidence=decision.confidence,
                project_id=pid,
                history_summary=state.history_summary,
            )

    # ── Collaborative building flow ───────────────────────────────────────────────
    # When all discovery slots are captured and collaborative_building_enabled,
    # enter the storyline_building → slide_negotiation → structure_agreed flow
    # instead of going straight to plan generation.
    if settings.collaborative_building_enabled and proposal_detected and not canonical_missing_slots and template_ids:
        return _handle_collaborative_building(
            db=db,
            conv=conv,
            pid=pid,
            content=content,
            prior_messages=prior_messages,
            state=state,
            merged_discovery=merged_discovery,
            project_context=project_context,
            decision=decision,
            template_ids=template_ids,
            output_type_representations=output_type_representations,
            content_skill_hint=content_skill_hint,
            custom_output_types=custom_output_types,
            combined_instruction=combined_instruction,
            rationale=rationale,
            resolved_wiki_refs=resolved_wiki_refs,
            canonical_missing_slots=canonical_missing_slots,
            prior_plan_meta=prior_plan_meta,
            user=user,
        )

    if decision.intent in {"smalltalk", "clarify", "greeting", "ack"} and not template_ids:
        state.state = "exploring"
        state.pending_questions = []
        stamp_router(state, intent=decision.intent, confidence=decision.confidence, rationale=rationale)
        save_state(conv, state)
        db.flush()
        if resolved_wiki_refs:
            state.surfaced_wiki_refs = list(dict.fromkeys([*state.surfaced_wiki_refs, *resolved_wiki_refs]))
            save_state(conv, state)
            db.flush()
        return _persist_conversational_response(
            db,
            conv,
            content,
            prior_messages,
            slots=merged_discovery,
            project_context=project_context,
            missing_slots=canonical_missing_slots,
            wiki_refs=resolved_wiki_refs,
            already_surfaced_refs=state.surfaced_wiki_refs,
            router_intent=decision.intent,
            router_confidence=decision.confidence,
            project_id=pid,
            history_summary=state.history_summary,
        )

    if not template_ids:
        state.state = "exploring"
        stamp_router(state, intent="clarify", confidence=0.3, rationale="no_template_ids")
        save_state(conv, state)
        db.flush()
        if resolved_wiki_refs:
            state.surfaced_wiki_refs = list(dict.fromkeys([*state.surfaced_wiki_refs, *resolved_wiki_refs]))
            save_state(conv, state)
            db.flush()
        return _persist_conversational_response(
            db,
            conv,
            content,
            prior_messages,
            slots=merged_discovery,
            project_context=project_context,
            missing_slots=canonical_missing_slots,
            wiki_refs=resolved_wiki_refs,
            already_surfaced_refs=state.surfaced_wiki_refs,
            router_intent=decision.intent,
            router_confidence=decision.confidence,
            project_id=pid,
            history_summary=state.history_summary,
        )

    with checkpoint_scope(
        db,
        "post_project_conversation_message.plan_commit",
        metadata={"project_id": pid, "conversation_id": conv.id},
    ) as cp_plan:
        state.state = "ready_to_plan"
        state.pending_questions = []
        state.deliverable = {
            "template_ids": template_ids,
            "representations": output_type_representations,
            "content_skill_hint": content_skill_hint,
        }
        stamp_router(state, intent=decision.intent, confidence=decision.confidence, rationale=rationale)
        save_state(conv, state)
        db.flush()
        cp_plan.mark("state_ready_to_plan_flushed")

        content_skill_targets = _derive_content_skill_targets(
            instruction=combined_instruction,
            template_ids=template_ids,
            prior_plan_meta=prior_plan_meta if isinstance(prior_plan_meta, dict) else None,
            llm_skill_hint=content_skill_hint,
        )
        regeneration_directive = _build_regeneration_directive(content)
        prior_decision_answers = _sanitize_decision_answers(prior_plan_meta.get("decision_answers")) if isinstance(prior_plan_meta, dict) else {}
        response = _persist_assistant_plan_message(
            db=db,
            conv=conv,
            content=content,
            instruction=combined_instruction,
            template_ids=template_ids,
            custom_output_types=custom_output_types,
            output_type_representations=output_type_representations,
            rationale=rationale,
            decision_answers=prior_decision_answers,
            content_skill_targets=content_skill_targets,
            regeneration_directive=regeneration_directive,
            discovery=merged_discovery,
        )
        state.state = "plan_proposed"
        save_state(conv, state)
        cp_plan.mark("assistant_plan_pre_commit")
        db.commit()
        cp_plan.mark("assistant_plan_committed")
    response["memory_quick_add"] = {
        "memory_page_path": "/memory",
        "batch_api_relative": f"/api/memory/{pid}/batch",
        "hint": "Save durable facts to Memory (or batch API after review); they are merged into run context when compaction is enabled.",
    }
    return response


@router.post("/{pid}/conversation/decisions")
def post_project_conversation_decisions(
    pid: str,
    body: ConversationDecisionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    conv = _get_or_create_conversation(db, pid=pid, user_id=user.id, user=user)
    if body.conversation_id and body.conversation_id != conv.id:
        raise HTTPException(
            status_code=400,
            detail=_detail("conversation_id_mismatch", "conversation_id does not match current conversation"),
        )
    messages = _serialize_messages(db, conv.id)
    plan_meta = _latest_assistant_plan_metadata(messages)
    if not plan_meta:
        raise HTTPException(
            status_code=409,
            detail=_detail("plan_missing", "No assistant plan is available for decision updates"),
        )
    latest_plan_hash = str(plan_meta.get("plan_hash") or "")
    if body.plan_hash and body.plan_hash != latest_plan_hash:
        raise HTTPException(
            status_code=409,
            detail=_detail("plan_changed", "Plan changed. Please resolve decisions on the latest plan"),
        )
    answers_map: dict[str, list[str]] = {}
    for ans in body.answers:
        key = (ans.prompt_id or "").strip()
        if not key:
            continue
        values = [str(v).strip() for v in (ans.selected_values or []) if str(v).strip()]
        if ans.free_text and ans.free_text.strip():
            values.append(ans.free_text.strip())
        if not values:
            # Skip empty entries so a user who clicked "Save" without choosing
            # anything gets a structured 400 below instead of silently replacing
            # their prior answer with an empty list.
            continue
        answers_map[key] = values[:5]
    if not answers_map:
        raise HTTPException(
            status_code=400,
            detail=_detail("answers_missing", "answers must include at least one selected value"),
        )

    prior_answers = _sanitize_decision_answers(plan_meta.get("decision_answers"))
    merged_answers = {**prior_answers, **answers_map}
    discovery = _merge_discovery({}, plan_meta.get("discovery"))
    if merged_answers.get("audience_role"):
        discovery = _merge_discovery(discovery, {"audience": merged_answers["audience_role"][0]})
    if merged_answers.get("narrative_arc"):
        discovery = _merge_discovery(discovery, {"narrative_arc": merged_answers["narrative_arc"][0]})
    if merged_answers.get("tone"):
        discovery = _merge_discovery(discovery, {"tone": merged_answers["tone"][0]})
    if merged_answers.get("slide_length_budget"):
        try:
            discovery = _merge_discovery(
                discovery,
                {"length_budget": {"pptx": int(str(merged_answers["slide_length_budget"][0]))}},
            )
        except Exception:
            pass
    assistant_instruction = str(plan_meta.get("instruction") or "").strip()
    if not assistant_instruction:
        raise HTTPException(
            status_code=409,
            detail=_detail("plan_instruction_missing", "Latest plan is missing instruction context"),
        )
    decision_lines = []
    for k, vals in merged_answers.items():
        if vals:
            decision_lines.append(f"{k}: {', '.join(vals)}")
    enriched_instruction = assistant_instruction
    if decision_lines:
        enriched_instruction = (
            f"{assistant_instruction}\n\nUser-confirmed decisions:\n- " + "\n- ".join(decision_lines)
        )
    # Reuse the previously approved plan's output routing. Saving decisions
    # should never re-run the LLM recommender — that path is expensive, slow,
    # and can fail on transient Claude errors (rate limits, network blips,
    # JSON parse issues), surfacing to the user as
    # "Failed to apply decision updates" even though the user's selections
    # were valid. The template ids / representations were already committed
    # by the plan that generated these decision prompts, so we keep them and
    # only refresh the rationale + decision metadata.
    prior_template_ids_raw = plan_meta.get("template_output_types")
    template_ids = [
        str(t).strip()
        for t in (prior_template_ids_raw if isinstance(prior_template_ids_raw, list) else [])
        if str(t).strip()
    ]
    prior_custom_raw = plan_meta.get("custom_output_types")
    custom_output_types = [
        str(t).strip()
        for t in (prior_custom_raw if isinstance(prior_custom_raw, list) else [])
        if str(t).strip()
    ]
    prior_reps = plan_meta.get("output_type_representations")
    output_type_representations = {
        str(k).strip(): str(v).strip()
        for k, v in (prior_reps if isinstance(prior_reps, dict) else {}).items()
        if str(k).strip() and str(v).strip()
    }
    rationale = str(plan_meta.get("rationale") or "Plan refreshed with your latest decisions.")

    user_msg = ConversationMessage(
        conversation_id=conv.id,
        role="user",
        content=(
            "Decision update: "
            + "; ".join([f"{k}={','.join(v)}" for k, v in merged_answers.items() if v])[:5000]
        ),
        metadata_json=json.dumps({"decision_answers": merged_answers, "plan_hash": latest_plan_hash}),
    )
    db.add(user_msg)
    db.flush()

    return _persist_assistant_plan_message(
        db=db,
        conv=conv,
        content=enriched_instruction,
        instruction=assistant_instruction,
        template_ids=template_ids,
        custom_output_types=custom_output_types,
        output_type_representations=output_type_representations,
        rationale=rationale,
        decision_answers=merged_answers,
        content_skill_targets=plan_meta.get("content_skill_targets")
        if isinstance(plan_meta.get("content_skill_targets"), dict)
        else {},
        regeneration_directive=str(plan_meta.get("regeneration_directive") or ""),
        discovery=discovery,
    )


@router.post("/{pid}/conversation/outline")
def post_project_conversation_outline(
    pid: str,
    body: ConversationOutlineUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    conv = _get_or_create_conversation(db, pid=pid, user_id=user.id, user=user)
    if body.conversation_id and body.conversation_id != conv.id:
        raise HTTPException(
            status_code=400,
            detail=_detail("conversation_id_mismatch", "conversation_id does not match current conversation"),
        )
    if not isinstance(body.slides, list) or len(body.slides) < 1:
        raise HTTPException(status_code=400, detail=_detail("slides_missing", "slides must include at least one slide"))
    normalized_slides: list[dict[str, str]] = []
    allowed_types = {
        "title",
        "bullets",
        "stat_cards",
        "column_cards",
        "stack_layers",
        "table",
        "chart",
        "section_divider",
        "big_number",
        "process_flow",
    }
    for slide in body.slides:
        title = str(slide.title or "").strip()
        slide_type = str(slide.slide_type or "").strip()
        purpose = str(slide.purpose or "").strip()
        if not title:
            continue
        if slide_type not in allowed_types:
            raise HTTPException(status_code=400, detail=_detail("invalid_slide_type", f"Unsupported slide_type: {slide_type}"))
        normalized_slides.append({"title": title, "slide_type": slide_type, "purpose": purpose})
    if not normalized_slides:
        raise HTTPException(status_code=400, detail=_detail("slides_invalid", "No valid slides were provided"))

    messages = _serialize_messages(db, conv.id)
    plan_meta = _latest_assistant_plan_metadata(messages)
    if not plan_meta:
        raise HTTPException(status_code=409, detail=_detail("plan_missing", "No assistant plan is available to update"))
    latest_plan_hash = str(plan_meta.get("plan_hash") or "")
    if body.plan_hash and body.plan_hash != latest_plan_hash:
        raise HTTPException(
            status_code=409,
            detail=_detail("plan_changed", "Plan changed. Please edit outline on the latest plan", latest_plan_hash=latest_plan_hash),
        )

    plan_message_id = next(
        (
            int(m.get("id"))
            for m in reversed(messages)
            if m.get("role") == "assistant"
            and isinstance(m.get("metadata"), dict)
            and str((m.get("metadata") or {}).get("plan_hash") or "") == latest_plan_hash
        ),
        0,
    )
    row = db.scalar(select(ConversationMessage).where(ConversationMessage.id == plan_message_id))
    if row is None:
        raise HTTPException(status_code=404, detail=_detail("plan_message_missing", "Plan message no longer exists"))

    metadata = plan_meta if isinstance(plan_meta, dict) else {}
    outline = metadata.get("deck_outline_preview") if isinstance(metadata.get("deck_outline_preview"), dict) else {}
    updated_discovery = _merge_discovery(metadata.get("discovery"), {"edited_by_user": True})
    outline = {
        **outline,
        "slides": normalized_slides,
        "rationale": str(outline.get("rationale") or "Updated by user"),
    }
    new_hash = _build_plan_hash(
        instruction=str(metadata.get("instruction") or ""),
        template_ids=metadata.get("template_output_types") or [],
        custom_output_types=metadata.get("custom_output_types") or [],
        reps=metadata.get("output_type_representations") or {},
        content_skill_targets=metadata.get("content_skill_targets") if isinstance(metadata.get("content_skill_targets"), dict) else {},
        regeneration_directive=str(metadata.get("regeneration_directive") or ""),
        discovery=updated_discovery,
    )
    metadata["deck_outline_preview"] = outline
    metadata["discovery"] = updated_discovery
    metadata["plan_hash"] = new_hash
    row.metadata_json = json.dumps(metadata)
    conv.updated_at = datetime.now(IST).replace(tzinfo=None)
    db.commit()

    return {
        "conversation_id": conv.id,
        "plan_hash": new_hash,
        "deck_outline_preview": outline,
        "discovery": updated_discovery,
        "messages": _serialize_messages(db, conv.id),
    }


@router.delete("/{pid}/conversation")
def clear_project_conversation(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    conv = db.scalar(
        select(Conversation)
        .where(Conversation.project_id == pid, Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    if conv is None:
        return {"cleared": False}
    db.execute(delete(ConversationMessage).where(ConversationMessage.conversation_id == conv.id))
    db.execute(delete(Conversation).where(Conversation.id == conv.id))
    db.commit()
    return {"cleared": True}


@router.post("/{pid}/conversation/confirm")
def confirm_project_conversation_plan(
    pid: str,
    body: ConversationConfirmRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    conv = _get_or_create_conversation(db, pid=pid, user_id=user.id, user=user)
    if body.conversation_id and body.conversation_id != conv.id:
        raise HTTPException(
            status_code=400,
            detail=_detail("conversation_id_mismatch", "conversation_id does not match current conversation"),
        )
    messages = _serialize_messages(db, conv.id)
    plan_meta = _latest_assistant_plan_metadata(messages)
    if not plan_meta:
        raise HTTPException(
            status_code=409,
            detail=_detail("plan_missing", "No assistant plan is available to confirm"),
        )
    # When decision prompts are disabled, always allow confirmation.
    # The LLM handles clarification via conversation, not hardcoded gates.
    if settings.instruction_decision_prompts_enabled and not bool(plan_meta.get("ready_for_confirmation")):
        raise HTTPException(
            status_code=409,
            detail=_detail(
                "plan_open_questions",
                "Plan still has open questions and cannot be confirmed",
                unresolved_prompt_ids=plan_meta.get("unresolved_prompt_ids") or [],
                open_questions=plan_meta.get("open_questions") or [],
            ),
        )
    if (
        settings.proposal_discovery_enabled
        and _is_proposal_instruction(str(plan_meta.get("instruction") or ""), plan_meta.get("template_output_types") or [])
        and not _has_sufficient_discovery(plan_meta.get("discovery"))
    ):
        raise HTTPException(
            status_code=409,
            detail=_detail(
                "proposal_discovery_incomplete",
                "Please complete discovery inputs before confirming this proposal plan",
            ),
        )
    plan_hash = str(plan_meta.get("plan_hash") or "")
    if body.plan_hash and body.plan_hash != plan_hash:
        raise HTTPException(
            status_code=409,
            detail=_detail("plan_changed", "Plan changed. Please reconfirm the latest plan", latest_plan_hash=plan_hash),
        )
    da = _sanitize_decision_answers(plan_meta.get("decision_answers"))
    dossier = plan_meta.get("strategy_dossier") if isinstance(plan_meta.get("strategy_dossier"), dict) else None
    from app.services.strategy_plan import resolve_selected_strategy

    selected_strategy = resolve_selected_strategy(dossier, da)
    confirm_msg = ConversationMessage(
        conversation_id=conv.id,
        role="user",
        content="Confirmed plan for execution.",
        metadata_json=json.dumps(
            {
                "plan_confirmed": True,
                "plan_hash": plan_hash,
                "instruction": str(plan_meta.get("instruction") or ""),
                "template_output_types": plan_meta.get("template_output_types") or [],
                "custom_output_types": plan_meta.get("custom_output_types") or [],
                "output_type_representations": plan_meta.get("output_type_representations") or {},
                "content_skill_targets": plan_meta.get("content_skill_targets")
                if isinstance(plan_meta.get("content_skill_targets"), dict)
                else {},
                "regeneration_directive": str(plan_meta.get("regeneration_directive") or ""),
                "confirmed_at": datetime.now(IST).isoformat(),
                "decision_answers": da,
                "strategy_dossier": dossier,
                "selected_strategy": selected_strategy,
                "discovery": _normalize_discovery(plan_meta.get("discovery")),
                "deck_outline_preview": plan_meta.get("deck_outline_preview")
                if isinstance(plan_meta.get("deck_outline_preview"), dict)
                else None,
                "document_outline_preview": plan_meta.get("document_outline_preview")
                if isinstance(plan_meta.get("document_outline_preview"), dict)
                else None,
                "wiki_context_refs": plan_meta.get("wiki_context_refs")
                if isinstance(plan_meta.get("wiki_context_refs"), list)
                else [],
            }
        ),
    )
    db.add(confirm_msg)
    conv.updated_at = datetime.now(IST).replace(tzinfo=None)
    db.commit()
    return {
        "conversation_id": conv.id,
        "confirmed": True,
        "plan_hash": plan_hash,
        "instruction": str(plan_meta.get("instruction") or ""),
        "template_output_types": plan_meta.get("template_output_types") or [],
        "custom_output_types": plan_meta.get("custom_output_types") or [],
        "output_type_representations": plan_meta.get("output_type_representations") or {},
        "content_skill_targets": plan_meta.get("content_skill_targets")
        if isinstance(plan_meta.get("content_skill_targets"), dict)
        else {},
        "regeneration_directive": str(plan_meta.get("regeneration_directive") or ""),
        "discovery": _normalize_discovery(plan_meta.get("discovery")),
        "deck_outline_preview": plan_meta.get("deck_outline_preview"),
        "document_outline_preview": plan_meta.get("document_outline_preview"),
        "wiki_context_refs": plan_meta.get("wiki_context_refs") or [],
    }


@router.get("/{pid}/me/preferences")
def get_my_project_preferences(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    row = db.scalar(
        select(UserProjectPreference).where(
            UserProjectPreference.user_id == user.id,
            UserProjectPreference.project_id == pid,
        )
    )
    if row is None:
        return {"project_id": pid, "context_lines": [], "learning_signals": {}, "updated_at": None}
    try:
        data = json.loads(row.preferences_json) if row.preferences_json else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    lines = data.get("context_lines")
    ls = data.get("learning_signals")
    return {
        "project_id": pid,
        "context_lines": lines if isinstance(lines, list) else [],
        "learning_signals": ls if isinstance(ls, dict) else {},
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.patch("/{pid}/me/preferences")
def patch_my_project_preferences(
    pid: str,
    body: UserProjectPreferencesBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    row = db.scalar(
        select(UserProjectPreference).where(
            UserProjectPreference.user_id == user.id,
            UserProjectPreference.project_id == pid,
        )
    )
    base: dict = {}
    if row is not None:
        try:
            parsed = json.loads(row.preferences_json) if row.preferences_json else {}
            if isinstance(parsed, dict):
                base = parsed
        except Exception:
            base = {}
    if body.context_lines is not None:
        base["context_lines"] = [str(x).strip() for x in body.context_lines if str(x).strip()][:50]
    if body.learning_signals is not None:
        prev = base.get("learning_signals")
        merged = dict(prev) if isinstance(prev, dict) else {}
        for k, v in body.learning_signals.items():
            if not k or len(str(k)) > 64:
                continue
            try:
                merged[str(k)[:64]] = int(v)
            except (TypeError, ValueError):
                continue
        base["learning_signals"] = merged
    payload = json.dumps(base, sort_keys=True)
    now = datetime.now(IST).replace(tzinfo=None)
    if row is None:
        row = UserProjectPreference(user_id=user.id, project_id=pid, preferences_json=payload, updated_at=now)
        db.add(row)
    else:
        row.preferences_json = payload
        row.updated_at = now
    db.commit()
    return get_my_project_preferences(pid, user, db)


@router.get("/{pid}/admin/team-personalization")
def get_team_personalization_summary(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner"}, user, db)
    total_items = int(
        db.scalar(
            select(func.count())
            .select_from(MemoryItem)
            .where(MemoryItem.project_id == pid, MemoryItem.is_archived.is_(False))
        )
        or 0
    )
    by_type_rows = db.execute(
        select(MemoryItem.memory_type, func.count())
        .where(MemoryItem.project_id == pid, MemoryItem.is_archived.is_(False))
        .group_by(MemoryItem.memory_type)
    ).all()
    by_source_rows = db.execute(
        select(MemoryItem.source, func.count())
        .where(MemoryItem.project_id == pid, MemoryItem.is_archived.is_(False))
        .group_by(MemoryItem.source)
    ).all()
    pref_users = int(
        db.scalar(select(func.count()).select_from(UserProjectPreference).where(UserProjectPreference.project_id == pid))
        or 0
    )
    return {
        "project_id": pid,
        "memory_items_total": total_items,
        "memory_items_by_type": {str(r[0]): int(r[1]) for r in by_type_rows},
        "memory_items_by_source": {str(r[0]): int(r[1]) for r in by_source_rows},
        "users_with_saved_preferences": pref_users,
    }


@router.get("/{pid}/scheduled-tasks")
def list_scheduled_tasks(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    rows = db.scalars(select(ScheduledTask).where(ScheduledTask.project_id == pid).order_by(ScheduledTask.created_at.desc())).all()
    items: list[dict] = []
    for row in rows:
        items.append(
            {
                "id": row.id,
                "name": row.name,
                "instruction": row.instruction,
                "status": row.status,
                "trigger_type": row.trigger_type,
                "cadence_minutes": row.cadence_minutes,
                "run_at": row.run_at.isoformat() if row.run_at else None,
                "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
                "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
                "last_run_status": row.last_run_status,
                "output_types": json.loads(row.output_types_json or "[]"),
                "custom_output_types": json.loads(row.custom_output_types_json or "[]"),
                "output_type_representations": json.loads(row.output_type_representations_json or "{}"),
            }
        )
    return {"project_id": pid, "items": items}


@router.post("/{pid}/scheduled-tasks")
def create_scheduled_task(
    pid: str,
    body: ScheduledTaskCreateBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    run_at_dt = None
    if body.run_at:
        try:
            run_at_dt = datetime.fromisoformat(body.run_at.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid run_at ISO timestamp") from None
    task = ScheduledTask(
        id=f"task_{uuid.uuid4().hex[:10]}",
        project_id=pid,
        created_by=user.id,
        name=(body.name or "").strip()[:255],
        instruction=(body.instruction or "").strip()[:6000],
        output_types_json=json.dumps(list(dict.fromkeys(body.output_types or []))),
        custom_output_types_json=json.dumps(body.custom_output_types or []),
        output_type_representations_json=json.dumps(body.output_type_representations or {}),
        trigger_type=body.trigger_type if body.trigger_type in {"interval", "once"} else "interval",
        cadence_minutes=max(1, int(body.cadence_minutes or 60)),
        run_at=run_at_dt,
        timezone=(body.timezone or "UTC").strip()[:64],
        retry_limit=max(0, int(body.retry_limit or 3)),
        status="active",
    )
    task.next_run_at = task.run_at if task.trigger_type == "once" else (datetime.now(IST).replace(tzinfo=None) + timedelta(minutes=task.cadence_minutes))
    db.add(task)
    db.commit()
    return {"project_id": pid, "task_id": task.id, "status": "created"}


@router.patch("/{pid}/scheduled-tasks/{task_id}")
def update_scheduled_task(
    pid: str,
    task_id: str,
    body: ScheduledTaskUpdateBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.project_id == pid))
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if body.name is not None:
        row.name = body.name.strip()[:255]
    if body.instruction is not None:
        row.instruction = body.instruction.strip()[:6000]
    if body.output_types is not None:
        row.output_types_json = json.dumps(list(dict.fromkeys(body.output_types)))
    if body.custom_output_types is not None:
        row.custom_output_types_json = json.dumps(body.custom_output_types)
    if body.output_type_representations is not None:
        row.output_type_representations_json = json.dumps(body.output_type_representations)
    if body.trigger_type in {"interval", "once"}:
        row.trigger_type = body.trigger_type
    if body.cadence_minutes is not None:
        row.cadence_minutes = max(1, int(body.cadence_minutes))
    if body.timezone is not None:
        row.timezone = body.timezone.strip()[:64]
    if body.retry_limit is not None:
        row.retry_limit = max(0, int(body.retry_limit))
    if body.status in {"active", "paused", "archived"}:
        row.status = body.status
    if body.run_at is not None:
        row.run_at = datetime.fromisoformat(body.run_at.replace("Z", "+00:00")).replace(tzinfo=None) if body.run_at else None
    row.next_run_at = row.run_at if row.trigger_type == "once" else (datetime.now(IST).replace(tzinfo=None) + timedelta(minutes=row.cadence_minutes))
    if row.status != "active":
        row.next_run_at = None
    row.updated_at = datetime.now(IST).replace(tzinfo=None)
    db.commit()
    return {"project_id": pid, "task_id": task_id, "status": "updated"}


@router.post("/{pid}/scheduled-tasks/{task_id}/pause")
def pause_scheduled_task(
    pid: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.project_id == pid))
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    row.status = "paused"
    row.next_run_at = None
    row.updated_at = datetime.now(IST).replace(tzinfo=None)
    db.commit()
    return {"project_id": pid, "task_id": task_id, "status": "paused"}


@router.post("/{pid}/scheduled-tasks/{task_id}/resume")
def resume_scheduled_task(
    pid: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.project_id == pid))
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    row.status = "active"
    row.next_run_at = row.run_at if row.trigger_type == "once" else (datetime.now(IST).replace(tzinfo=None) + timedelta(minutes=row.cadence_minutes))
    row.updated_at = datetime.now(IST).replace(tzinfo=None)
    db.commit()
    return {"project_id": pid, "task_id": task_id, "status": "active"}


@router.post("/{pid}/scheduled-tasks/{task_id}/run-now")
def run_scheduled_task_now(
    pid: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    require_project_role(pid, {"Owner", "Editor"}, user, db)
    row = db.scalar(select(ScheduledTask).where(ScheduledTask.id == task_id, ScheduledTask.project_id == pid))
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    run_id = f"run_{uuid.uuid4().hex[:10]}"
    plan = {
        "skill_card": "auto_selected",
        "sub_agents": json.loads(row.output_types_json or "[]"),
        "custom_output_types": json.loads(row.custom_output_types_json or "[]"),
        "output_type_representations": json.loads(row.output_type_representations_json or "{}"),
        "scheduled_task_id": row.id,
    }
    run = Run(
        id=run_id,
        project_id=pid,
        status="plan_ready",
        output_types=row.output_types_json,
        instruction=row.instruction,
        plan_payload=json.dumps(plan),
    )
    db.add(run)
    append_run_event(db, run_id, "scheduled_task.run_started", {"task_id": row.id, "project_id": pid})
    append_run_event(db, run_id, "plan_ready", plan)
    append_run_event(db, run_id, "step", {"status": "awaiting_hitl_approval", "source": "scheduled_task"})
    db.add(
        ScheduledTaskRun(
            id=f"str_{uuid.uuid4().hex[:10]}",
            task_id=row.id,
            project_id=pid,
            run_id=run_id,
            status="plan_ready",
            message="Run-now created and awaiting approval",
        )
    )
    row.last_run_at = datetime.now(IST).replace(tzinfo=None)
    row.last_run_status = "queued"
    row.updated_at = datetime.now(IST).replace(tzinfo=None)
    db.commit()
    return {"project_id": pid, "task_id": task_id, "run_id": run_id, "status": "plan_ready"}


@router.get("/{pid}/token-usage")
def get_project_token_usage(
    pid: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Return accumulated token counts and estimated cost for this project session."""
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    from app.services.run_budget import get_project_usage
    from app.services.llm_pricing import calculate_run_cost_usd
    usage = get_project_usage(pid)
    cost = calculate_run_cost_usd(**usage)
    return {
        "project_id": pid,
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cache_read_tokens": usage["cache_read_tokens"],
        "cache_creation_tokens": usage["cache_creation_tokens"],
        "cost_usd": cost,
    }
