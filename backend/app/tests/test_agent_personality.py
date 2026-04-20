"""Tests for Jimmy agent personality system."""

import pytest

from app.services.agent_personality import (
    AgentPersonality,
    add_milestone_celebration,
    format_insight_with_personality,
    format_phase_transition,
    format_plan_with_personality,
    format_question_with_personality,
    format_remediation_with_personality,
    format_success_message,
    inject_personality_markers,
)


class TestAgentPersonalityCore:
    """Tests for core AgentPersonality class."""

    def test_agent_name(self):
        """Verify agent name is set to Sheldon."""
        assert AgentPersonality.name == "Sheldon"

    def test_agent_role(self):
        """Verify agent role is execution partner."""
        assert AgentPersonality.role == "Your execution partner"

    def test_catchphrases_exist(self):
        """Verify all catchphrase contexts are defined."""
        expected_contexts = [
            "start_planning",
            "confirming_plan",
            "starting_execution",
            "hitting_milestone",
            "successful_completion",
            "handling_issue",
            "insight_trigger",
        ]
        for context in expected_contexts:
            assert context in AgentPersonality.CATCHPHRASES
            assert len(AgentPersonality.CATCHPHRASES[context]) > 0

    def test_celebration_emoji_defined(self):
        """Verify celebration emoji list is populated."""
        assert len(AgentPersonality.CELEBRATION_EMOJI) > 0
        assert "🎯" in AgentPersonality.CELEBRATION_EMOJI
        assert "✨" in AgentPersonality.CELEBRATION_EMOJI
        assert "🚀" in AgentPersonality.CELEBRATION_EMOJI

    def test_progress_markers_defined(self):
        """Verify progress markers are defined."""
        expected_markers = [
            "phase_start",
            "phase_complete",
            "milestone",
            "success",
            "checkpoint",
            "ready",
            "issue",
        ]
        for marker in expected_markers:
            assert marker in AgentPersonality.PROGRESS_MARKERS

    def test_get_catchphrase(self):
        """Test catchphrase retrieval."""
        phrase = AgentPersonality.get_catchphrase("start_planning")
        assert phrase
        assert len(phrase) > 0
        assert phrase in AgentPersonality.CATCHPHRASES["start_planning"]

    def test_get_catchphrase_invalid_context(self):
        """Test catchphrase retrieval with invalid context returns empty string."""
        phrase = AgentPersonality.get_catchphrase("invalid_context")
        assert phrase == ""

    def test_get_insight(self):
        """Test insight formatting."""
        insight = AgentPersonality.get_insight(
            "strategic_observation",
            "This approach balances cost and speed"
        )
        assert "strategic_observation" not in insight  # Template var replaced
        assert "balances cost and speed" in insight


class TestPersonalityFormatters:
    """Tests for personality formatting helper functions."""

    def test_format_plan_with_personality(self):
        """Test plan formatting with personality."""
        result = format_plan_with_personality(
            plan_summary="Proposal for Acme transformation",
            outputs=["pptx"],
            custom_outputs=["docx"],
            rationale=None,
        )
        assert "Plan Ready" in result or "blueprint" in result.lower()
        assert "pptx" in result
        assert "docx" in result
        assert "🎯" in result or "confirm" in result.lower()

    def test_add_milestone_celebration(self):
        """Test milestone celebration injection."""
        msg = "Work is complete"
        result = add_milestone_celebration(msg, milestone_type="success")
        assert "✨" in result
        assert "Work is complete" in result

    def test_add_milestone_celebration_no_duplicate(self):
        """Test milestone celebration doesn't duplicate markers."""
        msg = "✨ Already has emoji"
        result = add_milestone_celebration(msg, milestone_type="success")
        assert result == msg  # Should not add another emoji

    def test_format_question_with_personality(self):
        """Test question formatting with personality."""
        result = format_question_with_personality("Which format do you prefer?")
        assert "🎯" in result
        assert "Which format do you prefer?" in result

    def test_format_question_with_context_hint(self):
        """Test question formatting with context hint."""
        result = format_question_with_personality(
            "Choose a delivery approach",
            context_hint="This shapes the timeline"
        )
        assert "🎯" in result
        assert "This shapes the timeline" in result

    def test_format_remediation_with_personality(self):
        """Test remediation formatting with personality."""
        issues = ["Issue 1"]
        actions = ["Fix stat cards to have 3+ items", "Add source citations"]
        result = format_remediation_with_personality(issues=issues, action_items=actions)
        assert "optimization" in result.lower() or "golden" in result.lower()
        assert "→" in result  # Visual markers
        assert "stat cards" in result or "Fix" in result

    def test_format_insight_with_personality(self):
        """Test insight formatting with personality."""
        result = format_insight_with_personality(
            insight_text="Data shows strong ROI potential",
            insight_type="strategic_observation"
        )
        assert "Data shows strong ROI potential" in result
        # Should use the strategic_observation template
        assert "stands out" in result.lower() or "what i" in result.lower()

    def test_format_success_message(self):
        """Test success message formatting."""
        result = format_success_message("Deck generated successfully")
        assert "Deck generated successfully" in result
        assert "✨" in result or "Shipped" in result.lower()

    def test_format_success_message_with_details(self):
        """Test success message with additional details."""
        result = format_success_message(
            "Generation complete",
            details="All quality gates passed"
        )
        assert "Generation complete" in result
        assert "All quality gates passed" in result

    def test_inject_personality_markers(self):
        """Test personality marker injection."""
        result = inject_personality_markers("Starting phase one", context="phase_start")
        assert "→" in result
        assert "Starting phase one" in result

    def test_format_phase_transition(self):
        """Test phase transition formatting."""
        result = format_phase_transition(
            phase_name="Execution",
            description="Running agent generation"
        )
        assert "Execution" in result
        assert "Running agent generation" in result
        assert "→" in result or "Here we go" in result.lower()


class TestPersonalityIntegration:
    """Integration tests for personality system."""

    def test_plan_message_has_personality_markers(self):
        """Test that plan messages contain personality markers."""
        plan = format_plan_with_personality(
            plan_summary="Create proposal deck",
            outputs=["pptx"],
        )
        # Should have at least one emoji or personality marker
        personality_markers = ["🎯", "✨", "🚀", "→", "✓", "Plan Ready", "blueprint"]
        assert any(marker in plan for marker in personality_markers)

    def test_remediation_has_collaborative_tone(self):
        """Test that remediation messages have collaborative tone."""
        remediation = format_remediation_with_personality(
            issues=[],
            action_items=[
                "Add stat cards to slide 2",
                "Include source citations"
            ]
        )
        # Should have collaborative language
        collaborative_words = ["golden", "golden", "polish", "quick", "fix", "optimization"]
        assert any(word in remediation.lower() for word in collaborative_words)
        # Should have visual markers for actions
        assert "→" in remediation

    def test_all_catchphrases_are_strings(self):
        """Test that all catchphrases are valid strings."""
        for context, phrases in AgentPersonality.CATCHPHRASES.items():
            assert isinstance(phrases, list), f"Phrases for {context} should be a list"
            for phrase in phrases:
                assert isinstance(phrase, str), f"Phrase in {context} should be string"
                assert len(phrase) > 0, f"Phrase in {context} should not be empty"

    def test_personality_consistency_across_helpers(self):
        """Test that personality is consistent across helper functions."""
        # All should use consistent emoji and tone
        plan = format_plan_with_personality("test", ["pptx"])
        insight = format_insight_with_personality("insight", "strategic_observation")
        question = format_question_with_personality("test question")
        remediation = format_remediation_with_personality([], ["action"])

        # All should be non-empty
        assert len(plan) > 0
        assert len(insight) > 0
        assert len(question) > 0
        assert len(remediation) > 0

        # All should have personality (emoji or markers)
        has_emoji = (
            ("🎯" in plan or "✨" in plan or "🚀" in plan) and
            ("🎯" in question or "✨" in question or "🚀" in question) and
            ("→" in remediation or "🚀" in remediation)
        )
        assert has_emoji, "Messages should contain personality markers"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_outputs(self):
        """Test plan formatting with empty outputs."""
        result = format_plan_with_personality(
            plan_summary="Simple plan",
            outputs=[],
        )
        assert "Simple plan" in result
        assert len(result) > 0

    def test_none_custom_outputs(self):
        """Test plan formatting with None custom outputs."""
        result = format_plan_with_personality(
            plan_summary="Plan",
            outputs=["pptx"],
            custom_outputs=None,
        )
        assert "pptx" in result
        assert len(result) > 0

    def test_long_action_items(self):
        """Test remediation with long action items."""
        long_action = "Add comprehensive stat cards to slide 2 with descriptions, icons, and proper styling"
        result = format_remediation_with_personality(
            issues=[],
            action_items=[long_action]
        )
        assert long_action in result

    def test_special_characters_in_content(self):
        """Test personality formatters handle special characters."""
        result = format_question_with_personality(
            "What's the primary & secondary goal? (focus: ROI)"
        )
        assert "primary & secondary goal" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
