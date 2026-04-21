"""Tests for the natural conversation flow — intent classification & routing.

Verifies that the agent behaves like a colleague, not a plan-generating machine:
- Greetings → friendly response (no plan)
- Exploratory messages → conversational dialogue (no plan)
- Acknowledgments → brief, warm response (no plan)
- Contextual follow-ups → contextual answer (no plan)
- Clear commit requests → plan generation (yes plan)
"""

import pytest

from app.api.projects import (
    _merge_discovery,
    _required_discovery_missing_slots,
    _has_sufficient_discovery,
    _is_acknowledgment,
    _is_commit_intent,
    _is_contextual_followup,
    _is_proposal_instruction,
    _is_vague_instruction,
)

# ── Commit intent detection ─────────────────────────────────────────────

class TestCommitIntentDetection:
    """_is_commit_intent should only fire on clear creation requests."""

    @pytest.mark.parametrize("msg", [
        "Create a proposal in PPT for the engagement",
        "Build me a financial model in Excel",
        "Generate a process map for accounts payable",
        "Make a deck showing the transformation roadmap",
        "Draft a report on Q2 performance",
        "Write an SOP for the onboarding process",
        "Prepare a RACI matrix for the project",
        "Produce a narrative brief for the CFO",
        "Design a process flow for procurement",
    ])
    def test_clear_creation_requests_are_commit(self, msg: str) -> None:
        assert _is_commit_intent(msg) is True, f"Should be commit: {msg}"

    @pytest.mark.parametrize("msg", [
        "Go ahead",
        "Let's do it",
        "Let's build it",
        "Proceed",
        "Ship it",
        "Let's roll",
        "Get started",
    ])
    def test_go_ahead_phrases_are_commit(self, msg: str) -> None:
        assert _is_commit_intent(msg) is True, f"Should be commit: {msg}"

    @pytest.mark.parametrize("msg", [
        "Regenerate the proposal",
        "Redo the deck with more detail",
        "Revise the financial model",
        "Try again with a different approach",
    ])
    def test_redo_requests_are_commit(self, msg: str) -> None:
        assert _is_commit_intent(msg) is True, f"Should be commit: {msg}"

    @pytest.mark.parametrize("msg", [
        "I'm thinking about creating a proposal",
        "What if we made a deck instead?",
        "Should I build a process map?",
        "Could we explore making a report?",
        "Can we discuss the proposal format?",
        "Let's discuss the approach for the deck",
        "Help me think through the proposal structure",
        "What options do we have for the report?",
        "I'm considering a financial model",
        "What do you think about a presentation?",
        "What's the best way to structure this?",
        "Any suggestions for the proposal?",
        "How should we approach this?",
    ])
    def test_exploratory_messages_are_not_commit(self, msg: str) -> None:
        assert _is_commit_intent(msg) is False, f"Should NOT be commit: {msg}"

    @pytest.mark.parametrize("msg", [
        "We're working on a finance transformation project",
        "The client is a large bank in Southeast Asia",
        "I need help with something",
        "Tell me about process documentation",
        "How does the quality check work?",
        "What formats are available?",
        "The engagement involves CFO advisory",
        "Our team is focused on close acceleration",
    ])
    def test_context_sharing_is_not_commit(self, msg: str) -> None:
        assert _is_commit_intent(msg) is False, f"Should NOT be commit: {msg}"

    def test_empty_string_is_not_commit(self) -> None:
        assert _is_commit_intent("") is False
        assert _is_commit_intent(None) is False

    @pytest.mark.parametrize("msg", [
        "I need a proposal for the CFO",
        "I want a financial model with scenarios",
        "Give me a deck on the transformation roadmap",
        "Please create a process map",
        "Can you build a report for the board?",
        "Can you generate an SOP?",
    ])
    def test_strong_request_patterns_are_commit(self, msg: str) -> None:
        assert _is_commit_intent(msg) is True, f"Should be commit: {msg}"


# ── Acknowledgment detection ────────────────────────────────────────────

class TestAcknowledgmentDetection:
    """_is_acknowledgment catches simple one-word responses."""

    @pytest.mark.parametrize("msg", [
        "sounds good",
        "makes sense",
        "that makes sense",
        "good point",
        "i see",
        "understood",
        "interesting",
        "great",
        "perfect",
        "cool",
        "awesome",
        "yep",
        "yes",
        "no",
        "agree",
        "exactly",
        "right",
        "hmm",
    ])
    def test_acknowledgments_detected(self, msg: str) -> None:
        assert _is_acknowledgment(msg) is True, f"Should be acknowledgment: {msg}"

    @pytest.mark.parametrize("msg", [
        "Sounds good, let's create a proposal",
        "Great, now build the deck",
        "I think we should focus on the financial model",
        "What about adding a RACI matrix?",
    ])
    def test_messages_with_substance_not_acknowledgments(self, msg: str) -> None:
        assert _is_acknowledgment(msg) is False, f"Should NOT be acknowledgment: {msg}"


# ── Vague instruction detection ─────────────────────────────────────────

class TestVagueInstructionDetection:
    """_is_vague_instruction catches greetings and capability questions."""

    @pytest.mark.parametrize("msg", [
        "Hi",
        "hello",
        "hey",
        "thanks",
        "good morning",
        "ok",
    ])
    def test_greetings_are_vague(self, msg: str) -> None:
        assert _is_vague_instruction(msg) is True

    @pytest.mark.parametrize("msg", [
        "Create a proposal for the engagement",
        "I need a financial model",
        "What should we build?",
    ])
    def test_substantive_messages_not_vague(self, msg: str) -> None:
        assert _is_vague_instruction(msg) is False


# ── Contextual follow-up detection ──────────────────────────────────────

class TestContextualFollowupDetection:
    """_is_contextual_followup catches questions about recent findings."""

    def test_followup_with_context(self) -> None:
        prior = [
            {"role": "assistant", "content": "Found 3 issues: structural gaps, missing citations, deficient coverage."},
            {"role": "user", "content": "What refinements should we target?"},
        ]
        assert _is_contextual_followup("What refinements should we target?", prior) is True

    def test_followup_without_context(self) -> None:
        prior = [
            {"role": "assistant", "content": "Welcome! How can I help you today?"},
        ]
        assert _is_contextual_followup("What refinements should we target?", prior) is False

    def test_non_followup(self) -> None:
        prior = [
            {"role": "assistant", "content": "Found issues in the deck."},
        ]
        assert _is_contextual_followup("Create a new proposal", prior) is False


# ── Full routing integration tests ──────────────────────────────────────

class TestConversationRouting:
    """
    Verify that different message types route to the correct handler.
    These tests validate the intent classification logic without hitting the DB.
    """

    def test_greeting_routes_to_clarification(self) -> None:
        """Greeting should be caught by vague check before intent classification."""
        assert _is_vague_instruction("Hi") is True
        assert _is_commit_intent("Hi") is False

    def test_exploratory_routes_to_conversation(self) -> None:
        """Exploratory message should NOT be commit intent."""
        msg = "I'm thinking about putting together a finance transformation proposal for the CFO"
        assert _is_vague_instruction(msg) is False
        assert _is_commit_intent(msg) is False

    def test_clear_request_routes_to_plan(self) -> None:
        """Explicit creation request should trigger plan generation."""
        msg = "Create a proposal in PowerPoint for our finance transformation engagement"
        assert _is_vague_instruction(msg) is False
        assert _is_commit_intent(msg) is True

    def test_discussion_does_not_trigger_plan(self) -> None:
        """Discussion about options should stay in conversation mode."""
        msg = "What's the best way to present this to the CFO? Should it be a deck or a document?"
        assert _is_vague_instruction(msg) is False
        assert _is_commit_intent(msg) is False

    def test_acknowledgment_does_not_trigger_plan(self) -> None:
        """Simple acknowledgment should get brief response."""
        msg = "sounds good"
        assert _is_acknowledgment(msg) is True
        assert _is_commit_intent(msg) is False

    def test_context_sharing_stays_conversational(self) -> None:
        """Sharing project context should engage dialogue, not plan."""
        msg = "We're working with a large bank on their close acceleration initiative. The CFO wants to see projected savings."
        assert _is_vague_instruction(msg) is False
        assert _is_commit_intent(msg) is False

    def test_question_stays_conversational(self) -> None:
        """Questions about approach should stay conversational."""
        msg = "How should we structure the deliverable for maximum impact?"
        assert _is_vague_instruction(msg) is False
        assert _is_commit_intent(msg) is False

    def test_go_ahead_after_discussion_triggers_plan(self) -> None:
        """Explicit go-ahead should trigger plan generation."""
        msg = "Go ahead and build it"
        assert _is_commit_intent(msg) is True

    def test_hedged_creation_stays_conversational(self) -> None:
        """'Thinking about creating' is exploratory, not a commit."""
        msg = "Should I create a proposal or would a brief memo be better?"
        assert _is_commit_intent(msg) is False

    def test_multi_word_deliverable_detected(self) -> None:
        """Compound deliverable nouns should be detected."""
        msg = "Create a standard operating procedure for the intake process"
        assert _is_commit_intent(msg) is True

    def test_please_create_is_commit(self) -> None:
        msg = "Please create a process map for our procurement workflow"
        assert _is_commit_intent(msg) is True

    def test_what_options_is_not_commit(self) -> None:
        msg = "What options do we have for structuring the proposal?"
        assert _is_commit_intent(msg) is False


class TestProposalDiscoveryHelpers:
    def test_is_proposal_instruction_true_for_proposal_signals(self) -> None:
        assert _is_proposal_instruction("Create a finance transformation proposal deck", ["pptx"]) is True

    def test_is_proposal_instruction_false_for_non_proposal(self) -> None:
        assert _is_proposal_instruction("Create a process map for procurement", ["process_map"]) is False

    def test_has_sufficient_discovery_true(self) -> None:
        payload = {
            "client": {"name": "Varroc", "industry": "Manufacturing"},
            "outcome": {"primary": "Secure steering committee approval", "decision": "Fund phase 1"},
            "win_themes": ["Control uplift", "Fast value"],
        }
        assert _has_sufficient_discovery(payload) is True

    def test_has_sufficient_discovery_false_without_outcome(self) -> None:
        payload = {
            "client": {"name": "Varroc", "industry": "Manufacturing"},
            "outcome": {"primary": "", "decision": ""},
            "win_themes": ["Control uplift"],
        }
        assert _has_sufficient_discovery(payload) is False

    def test_merge_discovery_does_not_overwrite_non_empty_with_empty(self) -> None:
        base = {
            "client": {"name": "Varroc", "industry": "Auto"},
            "outcome": {"primary": "Transform PTP", "decision": ""},
        }
        incoming = {
            "client": {"name": "", "industry": "Manufacturing"},
            "outcome": {"primary": "", "decision": "Approve phase 1"},
        }
        merged = _merge_discovery(base, incoming)
        assert merged["client"]["name"] == "Varroc"
        assert merged["client"]["industry"] == "Manufacturing"
        assert merged["outcome"]["primary"] == "Transform PTP"
        assert merged["outcome"]["decision"] == "Approve phase 1"

    def test_required_missing_slots_uses_canonical_discovery(self) -> None:
        payload = {
            "client": {"name": "Varroc"},
            "win_themes": ["CFO transformation"],
            "outcome": {"primary": ""},
        }
        assert _required_discovery_missing_slots(payload) == ["outcome"]
