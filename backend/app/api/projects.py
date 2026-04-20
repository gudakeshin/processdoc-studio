import json
import shutil
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.formats import _load_output_types
from app.api.runs import _recommend_output_types
from app.core.auth import get_current_user, require_project_role
from app.core.config import settings
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
from app.services.proposal_policy import derive_proposal_skill_targets, generate_deck_outline_preview
from app.services.run_worker import append_run_event
from app.services.storage import ensure_workspace, workspace_path

router = APIRouter()


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


def _persist_conversational_response(
    db: Session, conv: Conversation, user_message: str, prior_messages: list[dict]
) -> dict:
    """Generate a natural, colleague-like conversational response.

    Instead of jumping to plan generation, engage in genuine dialogue:
    ask probing questions, suggest approaches, share insights, build understanding.
    """
    from app.services.claude import claude_generate

    # Build conversation context from recent messages
    recent_context = "\n".join(
        f"{m.get('role', 'user').upper()}: {str(m.get('content') or '')[:600]}"
        for m in prior_messages[-8:]
        if str(m.get("content") or "").strip()
    )

    system_prompt = """You are Sheldon, an energetic and insightful creative partner in a collaborative studio.
You're having a natural back-and-forth conversation with your teammate about their project.

Your role is to be a THOUGHTFUL COLLEAGUE — not a vending machine that produces plans on demand.

CONVERSATION RULES:
1. Ask probing questions to understand what they REALLY need — don't assume.
2. If they share context about a project, engage with it: ask about audience, goals, constraints.
3. If they ask "what approach" or "what options" — suggest 2-3 concrete approaches with brief trade-offs.
4. If they mention a topic/domain — share a relevant insight or angle they might not have considered.
5. Build understanding incrementally across messages — you're NOT in a rush to generate anything.
6. Keep responses concise (3-5 sentences) unless they ask for detail.
7. Use Sheldon's personality: energetic, strategic, supportive, occasionally witty.
8. Use occasional emojis (1-2 per message max) — don't overdo it.

CRITICAL: Do NOT say "Plan Ready" or offer to generate deliverables unless the user explicitly asks you to create/build/generate something.

When the user seems ready to commit, you can say something like:
"Sounds like we're aligned! When you're ready, just say the word and I'll put together a plan for [specific deliverable]."

Your capabilities (for context, so you can discuss them naturally):
- Proposals (PPT, Word)
- Financial models (Excel)
- Process maps and flowcharts
- SOPs and documentation
- Reports and analysis
- RACI matrices"""

    user_prompt = f"""Conversation so far:
{recent_context}

Latest message from user: {user_message}

Respond naturally as a colleague. Do NOT generate a plan or say "Plan Ready"."""

    try:
        response_text = claude_generate(
            system=system_prompt,
            user=user_prompt,
            temperature=0.7,
            max_tokens=400
        ).strip()
    except Exception:
        response_text = (
            "Great topic! Let me think about this with you. "
            "Can you tell me a bit more about the context? "
            "Who's the audience, and what's the main goal? "
            "That'll help me suggest the right approach. 🎯"
        )

    msg = ConversationMessage(
        conversation_id=conv.id,
        role="assistant",
        content=response_text,
        metadata_json=json.dumps({"kind": "conversational_response"}),
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
    db: Session, conv: Conversation, user_message: str, prior_messages: list[dict]
) -> dict:
    """Generate a brief, natural response to a simple acknowledgment.

    When user says "sounds good" or "makes sense", respond briefly and
    guide them toward next steps without being pushy.
    """
    from app.services.claude import claude_generate

    recent_context = "\n".join(
        f"{m.get('role', 'user').upper()}: {str(m.get('content') or '')[:400]}"
        for m in prior_messages[-4:]
        if str(m.get("content") or "").strip()
    )

    system_prompt = """You are Sheldon, an energetic creative partner.
The user just sent a brief acknowledgment (like "sounds good", "makes sense", "great").

Respond with 1-2 sentences that:
1. Acknowledge their response warmly
2. Either continue the discussion naturally OR gently ask what they'd like to do next
3. Keep Sheldon's personality (energetic, supportive)

Keep it SHORT — 1-2 sentences max. Don't be verbose."""

    user_prompt = f"""Recent conversation:
{recent_context}

User's acknowledgment: {user_message}

Respond briefly."""

    try:
        response_text = claude_generate(
            system=system_prompt,
            user=user_prompt,
            temperature=0.7,
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
) -> str:
    payload = json.dumps(
        {
            "instruction": instruction.strip(),
            "template_output_types": template_ids,
            "custom_output_types": custom_output_types,
            "output_type_representations": reps,
            "content_skill_targets": content_skill_targets or {},
            "regeneration_directive": (regeneration_directive or "").strip(),
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
    if not settings.instruction_decision_prompts_enabled:
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
) -> dict:
    decision_answers = decision_answers or {}
    content_skill_targets = {
        str(k).strip(): str(v).strip()
        for k, v in (content_skill_targets or {}).items()
        if str(k).strip() and str(v).strip()
    }
    regeneration_directive = (regeneration_directive or "").strip()
    decision_prompts, unresolved_prompt_ids, open_questions, soft_hints = _build_decision_prompts(
        content=content,
        template_ids=template_ids,
        custom_output_types=custom_output_types,
        current_answers=decision_answers,
    )
    strategy_dossier: dict | None = None
    if settings.strategy_options_planning_enabled and _instruction_may_warrant_strategy_options(instruction):
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
                if not decision_answers.get("execution_strategy"):
                    unresolved_prompt_ids = ["execution_strategy"] + unresolved_prompt_ids
                    open_questions = [
                        "Select one of the proposed execution approaches (see Approaches below).",
                    ] + open_questions
    # When decision prompts are disabled, always ready — the LLM handles clarification via conversation.
    ready_for_confirmation = True if not settings.instruction_decision_prompts_enabled else len(unresolved_prompt_ids) == 0
    display_open_questions = open_questions + soft_hints
    # ── Deck outline preview (lightweight Claude call for PPTX proposals) ──
    deck_outline_preview: dict | None = None
    pptx_skill = (content_skill_targets or {}).get("pptx", "")
    if "pptx" in {str(t).strip().lower() for t in template_ids} and pptx_skill:
        try:
            deck_outline_preview = generate_deck_outline_preview(
                instruction=instruction,
                output_type="pptx",
                skill_id=pptx_skill or None,
            )
        except Exception:
            deck_outline_preview = None

    plan_hash = _build_plan_hash(
        instruction=instruction,
        template_ids=template_ids,
        custom_output_types=custom_output_types,
        reps=output_type_representations,
        content_skill_targets=content_skill_targets,
        regeneration_directive=regeneration_directive,
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

    # Use personality-infused plan for display, with technical details below
    assistant_content = (
        f"{plan_with_personality}\n\n"
        f"**Technical Details:**\n"
        f"Template outputs: {', '.join(template_ids) if template_ids else 'none'}\n"
        f"Custom outputs: {', '.join(custom_output_types) if custom_output_types else 'none'}\n"
        f"Proposed representations: {json.dumps(output_type_representations)}\n"
        + (
            "\n**Open questions:**\n- " + "\n- ".join(display_open_questions)
            if display_open_questions
            else "\n✓ No open questions. Confirm plan to continue to execution."
        )
        + strategy_md
    )
    # Append deck outline preview to assistant content if available
    if isinstance(deck_outline_preview, dict) and deck_outline_preview.get("slides"):
        outline_lines = []
        for i, sl in enumerate(deck_outline_preview["slides"], 1):
            if isinstance(sl, dict):
                outline_lines.append(f"  {i}. [{sl.get('slide_type', 'bullets')}] {sl.get('title', '')} — {sl.get('purpose', '')}")
        if outline_lines:
            assistant_content += "\n\nProposed deck outline:\n" + "\n".join(outline_lines)
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
        "unresolved_prompt_ids": unresolved_prompt_ids,
        "ready_for_confirmation": ready_for_confirmation,
        "requires_confirmation": True,
        "plan_hash": plan_hash,
        "strategy_dossier": strategy_dossier,
        "deck_outline_preview": deck_outline_preview,
    }
    assistant_msg = ConversationMessage(
        conversation_id=conv.id,
        role="assistant",
        content=assistant_content,
        metadata_json=json.dumps(metadata_obj),
    )
    db.add(assistant_msg)
    conv.updated_at = datetime.utcnow()
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
        "unresolved_prompt_ids": unresolved_prompt_ids,
        "ready_for_confirmation": ready_for_confirmation,
        "requires_confirmation": True,
        "plan_hash": plan_hash,
        "deck_outline_preview": deck_outline_preview,
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
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {"project_id": pid, **data}
        except Exception:  # noqa: S110 — best-effort, non-fatal
            pass
    return {"project_id": pid, "qa_threshold": 0.8, "max_qa_loops": 2, "hard_gate_enabled": True}


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
    settings_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return {"project_id": pid, **current}


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
    require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content must not be empty")
    conv = _get_or_create_conversation(db, pid=pid, user_id=user.id, user=user)

    user_msg = ConversationMessage(
        conversation_id=conv.id,
        role="user",
        content=content[:6000],
        metadata_json="{}",
    )
    db.add(user_msg)
    db.flush()

    # ── Layer 1: Greetings & vague messages ────────────────────────────
    if _is_vague_instruction(content):
        return _persist_clarification_message(db, conv, content)

    # Load conversation context (needed by all subsequent layers)
    prior_messages = _serialize_messages(db, conv.id)
    prior_plan_meta = _latest_assistant_plan_metadata(prior_messages)

    # ── Layer 2: Simple acknowledgments ("sounds good", "makes sense") ─
    if _is_acknowledgment(content):
        return _persist_acknowledgment_response(db, conv, content, prior_messages)

    # ── Layer 3: Contextual follow-ups about recent findings/issues ────
    if _is_contextual_followup(content, prior_messages):
        recent_context = "\n".join(
            f"{m.get('role', 'user').upper()}: {str(m.get('content') or '')[:500]}"
            for m in prior_messages[-4:]
            if str(m.get("content") or "").strip()
        )
        return _persist_contextual_response(db, conv, content, recent_context)

    # ── Layer 4: Intent classification — COMMIT vs CONVERSATION ────────
    # Only proceed to plan generation if user clearly wants to build something.
    # Otherwise, engage in natural dialogue like a colleague would.
    if not _is_commit_intent(content):
        # User is exploring, discussing, brainstorming, or asking questions.
        # Engage conversationally — don't jump to "Plan Ready".
        return _persist_conversational_response(db, conv, content, prior_messages)

    # ── Layer 5: COMMIT path — user explicitly wants to build something ─
    # From here on, we know the user wants a specific deliverable created.
    available_output_types = [
        item for item in _load_output_types() if isinstance(item, dict) and isinstance(item.get("output_type_id"), str)
    ]

    history_prompt = "\n".join(
        f"{m.get('role', 'user')}: {str(m.get('content') or '').strip()}"
        for m in prior_messages[-12:]
        if str(m.get("content") or "").strip()
    )
    base_instruction = str((prior_plan_meta or {}).get("instruction") or "").strip()
    if _is_redo_followup(content) and base_instruction:
        # Prior plan found in this conversation — append the follow-up
        combined_instruction = f"{base_instruction}\n\nUser follow-up: {content}".strip()
    elif _is_redo_followup(content) and not base_instruction:
        # No prior plan in this conversation — attempt cross-session recovery
        recovered = _find_prior_plan_instruction(db, pid, exclude_conv_id=conv.id)
        if recovered:
            combined_instruction = f"{recovered}\n\nUser follow-up: {content}".strip()
        else:
            # Nothing found anywhere — ask for context rather than generating blindly
            return _persist_clarification_message(db, conv, content)
    else:
        combined_instruction = f"{history_prompt}\nuser: {content}".strip()

    # Get deliverable recommendations from LLM
    try:
        template_ids, custom_output_types, output_type_representations, rationale, content_skill_hint = _recommend_output_types(
            combined_instruction, available_output_types
        )
    except Exception:
        template_ids, custom_output_types, output_type_representations, rationale, content_skill_hint = [], [], {}, "Unable to process", None

    # If no deliverables recommended even on a commit intent, try one more pass before out-of-scope.
    # If the user's message contains explicit format or deliverable keywords, construct the
    # output types directly rather than declaring the request unsupported.
    if not template_ids and content.strip():
        _quick_format_map: dict[str, list[str]] = {
            "pptx": ["pptx", "ppt", "powerpoint", "slides", "slide deck", "presentation deck"],
            "docx": ["docx", "word document", "word doc"],
            "xlsx": ["excel", "spreadsheet", "xlsx"],
        }
        _allowed_ids = {item.get("output_type_id") for item in available_output_types if isinstance(item, dict)}
        _lowered_content = content.lower()
        emergency_types = [
            ot for ot, phrases in _quick_format_map.items()
            if any(p in _lowered_content for p in phrases) and ot in _allowed_ids
        ]
        if emergency_types:
            template_ids = emergency_types
            output_type_representations = {t: t for t in emergency_types}
        else:
            out_of_scope_response = _persist_out_of_scope_message(db, conv, content)
            return out_of_scope_response

    content_skill_targets = _derive_content_skill_targets(
        instruction=combined_instruction,
        template_ids=template_ids,
        prior_plan_meta=prior_plan_meta if isinstance(prior_plan_meta, dict) else None,
        llm_skill_hint=content_skill_hint,
    )
    regeneration_directive = _build_regeneration_directive(content)
    response = _persist_assistant_plan_message(
        db=db,
        conv=conv,
        content=content,
        instruction=combined_instruction,
        template_ids=template_ids,
        custom_output_types=custom_output_types,
        output_type_representations=output_type_representations,
        rationale=rationale,
        content_skill_targets=content_skill_targets,
        regeneration_directive=regeneration_directive,
    )
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
        answers_map[key] = values[:5]
    if not answers_map:
        raise HTTPException(
            status_code=400,
            detail=_detail("answers_missing", "answers must include at least one selected value"),
        )

    prior_answers = _sanitize_decision_answers(plan_meta.get("decision_answers"))
    merged_answers = {**prior_answers, **answers_map}
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
    available_output_types = [
        item for item in _load_output_types() if isinstance(item, dict) and isinstance(item.get("output_type_id"), str)
    ]
    template_ids, custom_output_types, output_type_representations, rationale, _skill_hint = _recommend_output_types(
        enriched_instruction, available_output_types
    )

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
    )


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
                "confirmed_at": datetime.utcnow().isoformat(),
                "decision_answers": da,
                "strategy_dossier": dossier,
                "selected_strategy": selected_strategy,
            }
        ),
    )
    db.add(confirm_msg)
    conv.updated_at = datetime.utcnow()
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
    now = datetime.utcnow()
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
    task.next_run_at = task.run_at if task.trigger_type == "once" else (datetime.utcnow() + timedelta(minutes=task.cadence_minutes))
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
    row.next_run_at = row.run_at if row.trigger_type == "once" else (datetime.utcnow() + timedelta(minutes=row.cadence_minutes))
    if row.status != "active":
        row.next_run_at = None
    row.updated_at = datetime.utcnow()
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
    row.updated_at = datetime.utcnow()
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
    row.next_run_at = row.run_at if row.trigger_type == "once" else (datetime.utcnow() + timedelta(minutes=row.cadence_minutes))
    row.updated_at = datetime.utcnow()
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
    row.last_run_at = datetime.utcnow()
    row.last_run_status = "queued"
    row.updated_at = datetime.utcnow()
    db.commit()
    return {"project_id": pid, "task_id": task_id, "run_id": run_id, "status": "plan_ready"}
