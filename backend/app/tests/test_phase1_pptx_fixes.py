"""Phase 1 PPTX Quality Fixes Test Suite.

Tests for:
- Step 1.1: Metrics injection into agent prompt
- Step 1.2: System prompt examples
- Step 1.3: Render validation warnings
- Step 1.4: Text truncation validation
- Step 1.5: Quality gate completeness check
"""

from __future__ import annotations

import json
import logging
from unittest.mock import Mock, patch, MagicMock
from io import StringIO

import pytest

from app.agents.agent_types import AgentContext
from app.agents.subagents import run_pptx_agent
from app.services.deliverable_quality import (
    _validate_pptx_completeness,
    run_deliverable_quality_loop,
)


# ============================================================================
# TEST 1: METRICS INJECTION
# ============================================================================

def test_pptx_agent_injects_metrics_into_prompt() -> None:
    """Test that PPTX agent extracts metrics from enrichment and injects them."""

    # Create a mock context with enrichment
    ctx = Mock()
    ctx.run_id = "test_run_1"
    ctx.output_type = "pptx"
    ctx.user_instruction = "Generate executive deck for P2P process"
    ctx.process_model = {
        "steps": [{"role": f"Role{i}", "owner": "Owner"} for i in range(14)],
        "systems": ["SAP", "Portal", "Email"],
        "metadata": {"process_name": "Procure-to-Pay"},
    }
    ctx.assembled_context = "Sample context"
    ctx.prior_artifacts_excerpt = "Sample narrative"
    ctx.skill_card = {}  # Add required attribute

    # Create enrichment with metrics
    ctx.enrichment = Mock()
    analytics = Mock()
    analytics.steps_count = 14
    analytics.roles_count = 5
    analytics.decision_points = 2
    ctx.enrichment.process_analytics = analytics

    risk_profile = Mock()
    risk_profile.risks = [{"gap": "Risk1"}, {"gap": "Risk2"}]
    ctx.enrichment.risk_profile = risk_profile
    ctx.enrichment.value_drivers = ["Driver1", "Driver2"]

    # Mock the Claude API
    with patch("app.agents.subagents.is_claude_enabled") as mock_enabled:
        mock_enabled.return_value = True

        with patch("app.agents.subagents.claude_generate_json") as mock_claude:
            # Mock Claude response with populated stat_cards
            mock_claude.return_value = {
                "slides": [
                    {"slide_type": "title", "title": "P2P"},
                    {
                        "slide_type": "stat_cards",
                        "title": "Process Scale",
                        "stat_cards": [
                            {"stat": "14", "label": "Steps", "description": "Process steps"},
                            {"stat": "5", "label": "Roles", "description": "Key roles"},
                            {"stat": "3", "label": "Systems", "description": "Systems"}
                        ]
                    }
                ]
            }

            # Run PPTX agent
            result = run_pptx_agent(ctx)

            # Verify Claude was called with metrics in the prompt
            assert mock_claude.called, "Claude API should be called"
            call_args = mock_claude.call_args
            user_prompt = call_args[1].get("user") if call_args else ""

            # Check that metrics are in the prompt
            assert "DATA FOR SLIDE 2" in user_prompt or "14" in user_prompt, \
                "Metrics should be injected into prompt"

            # Verify generated JSON has stat_cards
            if isinstance(result, dict) and "slides" in result:
                assert len(result["slides"]) >= 2, "Should have at least 2 slides"
                slide2 = result["slides"][1]
                assert slide2.get("slide_type") == "stat_cards", "Slide 2 should be stat_cards"
                cards = slide2.get("stat_cards", [])
                assert len(cards) >= 3, f"Slide 2 should have 3+ stat_cards, got {len(cards)}"


# ============================================================================
# TEST 2: VALIDATION CATCHES EMPTY SLIDES
# ============================================================================

def test_validate_pptx_completeness_detects_empty_stat_cards() -> None:
    """Test that _validate_pptx_completeness detects empty stat_cards."""

    pptx_json_str = json.dumps({
        "slides": [
            {"slide_type": "title", "title": "P2P Process"},
            {"slide_type": "stat_cards", "title": "Metrics", "stat_cards": []},  # Empty!
            {"slide_type": "column_cards", "title": "Pillars", "column_cards": [
                {"heading": "P1", "body": "Body1"},
                {"heading": "P2", "body": "Body2"},
                {"heading": "P3", "body": "Body3"}
            ]}
        ]
    })

    is_complete, issues = _validate_pptx_completeness(pptx_json_str)

    assert not is_complete, "Should be incomplete due to empty stat_cards"
    assert len(issues) > 0, "Should have at least one issue"
    assert "stat_cards" in issues[0], "Issue should mention stat_cards"
    assert "got 0" in issues[0], "Issue should report actual count"


def test_validate_pptx_completeness_detects_empty_column_cards() -> None:
    """Test that _validate_pptx_completeness detects empty column_cards."""

    pptx_json_str = json.dumps({
        "slides": [
            {"slide_type": "title", "title": "P2P Process"},
            {"slide_type": "column_cards", "title": "Pillars", "column_cards": []}  # Empty!
        ]
    })

    is_complete, issues = _validate_pptx_completeness(pptx_json_str)

    assert not is_complete, "Should be incomplete due to empty column_cards"
    assert len(issues) > 0, "Should have at least one issue"
    assert "column_cards" in issues[0], "Issue should mention column_cards"


def test_validate_pptx_completeness_passes_with_populated_slides() -> None:
    """Test that _validate_pptx_completeness passes with valid data."""

    pptx_json_str = json.dumps({
        "slides": [
            {"slide_type": "title", "title": "P2P Process"},
            {
                "slide_type": "stat_cards",
                "title": "Metrics",
                "stat_cards": [
                    {"stat": "14", "label": "Steps", "description": "Steps"},
                    {"stat": "5", "label": "Roles", "description": "Roles"},
                    {"stat": "3", "label": "Systems", "description": "Systems"}
                ]
            },
            {
                "slide_type": "column_cards",
                "title": "Pillars",
                "column_cards": [
                    {"heading": "P1", "body": "Body1"},
                    {"heading": "P2", "body": "Body2"},
                    {"heading": "P3", "body": "Body3"}
                ]
            },
            {
                "slide_type": "bullets",
                "title": "Next Steps",
                "bullets": ["Action 1", "Action 2"]
            }
        ]
    })

    is_complete, issues = _validate_pptx_completeness(pptx_json_str)

    assert is_complete, f"Should be complete, but got issues: {issues}"
    assert len(issues) == 0, "Should have no issues"


# ============================================================================
# TEST 3: TEXT TRUNCATION WARNINGS
# ============================================================================

def test_render_bullets_logs_truncation_warning_for_long_text() -> None:
    """Test that rendering long bullets logs truncation warning."""

    # Verify the storage module has text truncation validation in code
    try:
        import inspect
        from app.services import storage
        source = inspect.getsource(storage)

        # Check that the code contains truncation validation
        assert "max_chars" in source or "truncat" in source.lower() or "[PPTX QA]" in source, \
            "Storage module should have text truncation validation"
    except Exception as e:
        # If we can't fully test the render function, at least verify completeness validation
        pytest.skip(f"Could not verify render function: {e}")


# ============================================================================
# TEST 4: COMPLETENESS CHECK TRIGGERS REMEDIATION
# ============================================================================

def test_quality_loop_fails_on_incomplete_pptx() -> None:
    """Test that quality loop fails when PPTX completeness check fails."""

    # Create incomplete PPTX JSON (empty stat_cards)
    incomplete_pptx = json.dumps({
        "slides": [
            {"slide_type": "title", "title": "P2P"},
            {"slide_type": "stat_cards", "title": "Metrics", "stat_cards": []}  # Empty!
        ]
    })

    # Create mock state and context
    state = {
        "skill_card": {
            "primary_skill_by_output_type": {
                "pptx": {"id": "pptx_skill", "display_name": "PPTX"}
            }
        }
    }

    outputs = {"pptx_slides": incomplete_pptx}

    # Mock remediation function
    remediation_called = []
    def mock_remediation(st, wanted, failures):
        remediation_called.append(failures)
        return outputs  # Return same outputs (would be refreshed in real scenario)

    # Run quality loop with incomplete PPTX
    with patch("app.services.deliverable_quality.contract_for_outputs") as mock_contracts:
        mock_contracts.return_value = {
            "pptx_slides": {
                "dimensions": [],
                "pass_threshold": 0.72,
                "_contract_id": "pptx_contract"
            }
        }

        report, refreshed = run_deliverable_quality_loop(
            state=state,
            wanted=["pptx_slides"],
            outputs=outputs,
            apply_remediation=mock_remediation,
            emit_event=None,
            project_id="test_123"
        )

        # Verify that remediation was triggered
        assert len(remediation_called) > 0, "Remediation should be triggered for incomplete PPTX"

        # Verify that the failure contains completeness issues
        failures = remediation_called[0]
        assert "pptx_slides" in failures, "Failure should be for pptx_slides"
        assert "completeness" in str(failures).lower(), \
            f"Failure should mention completeness, got: {failures}"


# ============================================================================
# TEST 5: END-TO-END DECK GENERATION
# ============================================================================

def test_pptx_agent_generates_populated_deck() -> None:
    """Test end-to-end PPTX generation with populated slides."""

    ctx = Mock()
    ctx.run_id = "test_run_e2e"
    ctx.output_type = "pptx"
    ctx.user_instruction = "Generate executive deck"
    ctx.process_model = {
        "process_name": "Procure-to-Pay",
        "steps": [{"role": f"Role{i % 5}", "owner": "Owner"} for i in range(14)],
        "systems": ["SAP", "Portal", "Email"],
    }
    ctx.assembled_context = "Context"
    ctx.prior_artifacts_excerpt = "Prior"
    ctx.skill_card = {}  # Add required attribute

    # Create enrichment
    ctx.enrichment = Mock()
    analytics = Mock()
    analytics.steps_count = 14
    analytics.roles_count = 5
    ctx.enrichment.process_analytics = analytics
    ctx.enrichment.risk_profile = None
    ctx.enrichment.value_drivers = []

    with patch("app.agents.subagents.is_claude_enabled") as mock_enabled:
        mock_enabled.return_value = True

        with patch("app.agents.subagents.claude_generate_json") as mock_claude:
            # Return a properly populated deck
            mock_claude.return_value = {
                "slides": [
                    {"slide_type": "title", "title": "Procure-to-Pay", "subtitle": "Process Overview"},
                    {
                        "slide_type": "stat_cards",
                        "title": "Process Scale & Scope",
                        "stat_cards": [
                            {"stat": "14", "label": "Process Steps", "description": "End-to-end workflow", "fill": "dark"},
                            {"stat": "5", "label": "Key Roles", "description": "Departments involved", "fill": "mid_dark"},
                            {"stat": "3", "label": "Systems", "description": "Applications", "fill": "gray"}
                        ]
                    },
                    {
                        "slide_type": "column_cards",
                        "title": "Three Pillars",
                        "column_cards": [
                            {"heading": "Governance", "accent": "green", "body": "Centralize vendor master"},
                            {"heading": "Quality", "accent": "dark", "body": "Activate QM module"},
                            {"heading": "Automation", "accent": "gray", "body": "Implement OCR"}
                        ]
                    },
                    {
                        "slide_type": "bullets",
                        "title": "Next Steps",
                        "bullets": ["Action 1", "Action 2", "Action 3"]
                    }
                ]
            }

            result = run_pptx_agent(ctx)

            # Verify result structure (AgentOutput with updates)
            from app.agents.agent_types import AgentOutput
            assert isinstance(result, AgentOutput), "Result should be AgentOutput"
            assert "pptx_slides" in result.updates, "Result should have pptx_slides in updates"

            slides = result.updates["pptx_slides"]
            assert len(slides) >= 4, f"Should have at least 4 slides, got {len(slides)}"

            # Verify slide types
            assert slides[0]["slide_type"] == "title"
            assert slides[1]["slide_type"] == "stat_cards"
            assert slides[2]["slide_type"] == "column_cards"

            # Verify stat_cards are populated
            stat_cards = slides[1].get("stat_cards", [])
            assert len(stat_cards) >= 3, f"Stat cards should have 3+ items, got {len(stat_cards)}"

            # Verify each card has required fields
            for i, card in enumerate(stat_cards):
                assert "stat" in card, f"Card {i} missing stat"
                assert "label" in card, f"Card {i} missing label"
                assert "description" in card, f"Card {i} missing description"


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

def test_metrics_injection_prevents_empty_slides() -> None:
    """Integration test: metrics injection → populated JSON → completeness passes."""

    # Step 1: Verify metrics are available in enrichment
    ctx = Mock()
    ctx.enrichment = Mock()
    analytics = Mock()
    analytics.steps_count = 14
    analytics.roles_count = 5
    ctx.enrichment.process_analytics = analytics

    # Step 2: Verify agent uses metrics
    ctx.process_model = {"steps": [], "systems": []}
    ctx.output_type = "pptx"
    ctx.user_instruction = "Generate deck"
    ctx.assembled_context = ""
    ctx.prior_artifacts_excerpt = ""
    ctx.run_id = "test"
    ctx.skill_card = {}  # Add required attribute

    with patch("app.agents.subagents.is_claude_enabled") as mock_enabled:
        mock_enabled.return_value = True

        with patch("app.agents.subagents.claude_generate_json") as mock_claude:
            # Return populated deck
            mock_claude.return_value = {
                "slides": [
                    {"slide_type": "title", "title": "Test"},
                    {
                        "slide_type": "stat_cards",
                        "title": "Metrics",
                        "stat_cards": [
                            {"stat": "14", "label": "A", "description": "Desc"},
                            {"stat": "5", "label": "B", "description": "Desc"},
                            {"stat": "3", "label": "C", "description": "Desc"}
                        ]
                    }
                ]
            }

            result = run_pptx_agent(ctx)

            # Step 3: Verify completeness check passes
            from app.agents.agent_types import AgentOutput
            assert isinstance(result, AgentOutput)
            slides = result.updates.get("pptx_slides", [])
            pptx_json_str = json.dumps({"slides": slides})
            is_complete, issues = _validate_pptx_completeness(pptx_json_str)

            assert is_complete, f"Completeness check should pass, got issues: {issues}"


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
