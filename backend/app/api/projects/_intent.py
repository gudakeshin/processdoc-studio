"""Pure intent/classification helpers and their lexicons for the conversation router.

Extracted verbatim from conversation.py; re-imported there so the
monkeypatch contract on app.api.projects.conversation.<name> still holds.
"""

from app.services.proposal_policy import has_proposal_intent, is_finance_proposal_intent


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


_DELIVERABLE_NOUNS = {
    "proposal", "deck", "presentation", "pptx", "powerpoint", "ppt",
    "document", "report", "docx", "word",
    "model", "spreadsheet", "excel", "xlsx",
    "process map", "process flow", "flowchart", "diagram",
    "sop", "standard operating procedure",
    "narrative", "brief", "memo", "analysis",
    "raci", "matrix",
}


_COMMIT_VERBS = {
    "create", "build", "generate", "make", "draft", "write", "produce",
    "design", "prepare", "develop", "construct", "deliver",
}


_GO_AHEAD_PHRASES = [
    "go ahead", "let's do it", "proceed", "let's build", "let's go",
    "ship it", "let's make it", "do it", "yes build", "yes create",
    "confirmed", "let's proceed", "start building", "start creating",
    "kick it off", "let's roll", "get started", "begin",
]


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


_EXECUTE_NOW_SUBSTRINGS = (
    "go ahead and draft", "go ahead and build", "go ahead and create",
    "go ahead and generate", "go ahead and start", "go ahead and make",
    "go ahead make", "go ahead build", "go ahead create", "go ahead generate",
    "please go ahead", "please draft", "please build the", "please create the",
    "please generate the", "start building", "start drafting", "start creating",
    "start generating", "begin building", "begin drafting", "begin creating",
    "kick it off", "kick off the", "get it started", "get started on",
    "run this now", "run it now", "run this", "make the deliverable",
    "create the deliverable", "build the deliverable", "generate the deliverable",
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
    if any(sub in lowered for sub in _EXECUTE_NOW_SUBSTRINGS):
        return True
    # Natural sentences that wrap an unambiguous trigger phrase (e.g. "Go ahead
    # make the deliverable now", "Lets go with the consolidation") still count,
    # as long as the message isn't a question or hedging/exploratory language.
    if "?" in lowered or any(hedge in lowered for hedge in _EXPLORATORY_PHRASES):
        return False
    return any(phrase in lowered for phrase in _EXECUTE_NOW_PATTERNS if len(phrase) >= 4)


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
