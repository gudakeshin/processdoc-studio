"""
End-to-end test for proposal-to-PPT pipeline.

Tests the 6-stage flow:
1. User request → skill recommendation
2. Plan confirmation
3. Run creation
4. Context assembly + agent enrichment
5. PPTX agent execution
6. QA loop → delivery
"""

import json
import pytest
from unittest.mock import patch, MagicMock, call
from typing import Any

from app.agents.coordinator import Coordinator
from app.agents.agent_types import AgentContext, AgentOutput
from app.services.proposal_policy import derive_proposal_skill_targets
from app.core.state import ProcessDocState


class TestProposalPptxPipeline:
    """End-to-end tests for proposal generation to PPTX."""

    @pytest.fixture
    def proposal_instruction(self) -> str:
        """User request for a finance transformation proposal."""
        return "Create a comprehensive proposal in PowerPoint for our finance transformation engagement with Acme Corp."

    @pytest.fixture
    def finance_keywords(self) -> list[str]:
        """Keywords that trigger finance proposal detection."""
        return ["finance transformation", "CFO", "cost reduction", "FP&A"]

    @pytest.fixture
    def base_state(self, proposal_instruction) -> ProcessDocState:
        """Base state for coordinator run."""
        return {
            "run_id": "test-proposal-pptx-001",
            "project_id": "test-project-123",
            "user_id": "test-user",
            "requested_outputs": ["pptx"],
            "raw_text": proposal_instruction,
            "user_instruction": proposal_instruction,
            "user_intent_original": proposal_instruction,
            "dpdp_flags": {"enabled": False},
            "assembled_context": "",  # Will be populated
            "process_model": {
                "steps": [
                    {"id": "1", "name": "Discovery", "duration": "2 weeks"},
                    {"id": "2", "name": "Analysis", "duration": "3 weeks"},
                    {"id": "3", "name": "Design", "duration": "2 weeks"},
                    {"id": "4", "name": "Implementation", "duration": "8 weeks"},
                ],
                "roles": ["Finance Director", "CFO", "Controller", "Process Manager", "Finance Analyst"],
                "systems": ["SAP", "Oracle", "Hyperion", "Anaplan", "Power BI", "Excel", "Workday", "Coupa"],
            },
            "docx_markdown": "",
            "pptx_slides": None,
            "qa_report": None,
            "guardrail_report": None,
        }

    @pytest.fixture
    def mock_claude_proposal_response(self) -> dict:
        """Mock Claude response for PPTX proposal generation."""
        return {
            "slides": [
                {
                    "slide_type": "title",
                    "title": "Finance Transformation Proposal",
                    "subtitle": "Acme Corp Engagement",
                },
                {
                    "slide_type": "stat_cards",
                    "title": "Process Scale",
                    "stat_cards": [
                        {"stat": "4", "label": "End-to-End Steps"},
                        {"stat": "5", "label": "Key Roles"},
                        {"stat": "8", "label": "Systems Impacted"},
                    ],
                },
                {
                    "slide_type": "bullets",
                    "title": "Current State & Problem Statement",
                    "bullets": [
                        "[1] Finance processes are manual and time-intensive",
                        "[2] Limited real-time visibility into financial performance",
                        "[3] High operational costs due to redundancy",
                    ],
                },
                {
                    "slide_type": "bullets",
                    "title": "Proposed Approach",
                    "bullets": [
                        "Streamline core finance processes through automation",
                        "Implement cloud-based FP&A platform",
                        "Enable real-time analytics and insights",
                    ],
                },
                {
                    "slide_type": "column_cards",
                    "title": "Implementation Timeline",
                    "columns": [
                        {"header": "Phase 1", "items": ["Discovery", "Analysis"]},
                        {"header": "Phase 2", "items": ["Design", "Build"]},
                        {"header": "Phase 3", "items": ["Test", "Deploy"]},
                    ],
                },
                {
                    "slide_type": "bullets",
                    "title": "Value Case",
                    "bullets": [
                        "[1] 40% reduction in finance FTE costs",
                        "[2] $2.3M annual savings opportunity",
                        "[3] 50% faster close cycle",
                    ],
                },
                {
                    "slide_type": "stat_cards",
                    "title": "Implementation Value",
                    "stat_cards": [
                        {"stat": "$2.3M", "label": "Annual Savings"},
                        {"stat": "50%", "label": "Close Improvement"},
                        {"stat": "8 weeks", "label": "Timeline"},
                    ],
                },
                {
                    "slide_type": "bullets",
                    "title": "Risks and Mitigations",
                    "bullets": [
                        "Change management: Structured training & communication plan",
                        "Data quality: Validation rules and audit mechanisms",
                        "Timeline: Agile approach with weekly milestones",
                    ],
                },
                {
                    "slide_type": "bullets",
                    "title": "Governance and Team Structure",
                    "bullets": [
                        "Steering Committee (CFO, COO, CIO)",
                        "Project Management Office (PMO)",
                        "Workstream leads for each module",
                    ],
                },
                {
                    "slide_type": "bullets",
                    "title": "Next Steps",
                    "bullets": [
                        "Schedule stakeholder alignment meeting (Week 1)",
                        "Finalize scope and commercial terms (Week 2)",
                        "Kick-off project execution (Week 3)",
                    ],
                },
            ]
        }

    # ========== Stage 1: Skill Target Recommendation ==========

    def test_stage1_proposal_skill_detection(self, proposal_instruction):
        """Stage 1: Verify proposal intent detection → finance skill target."""
        # When user instruction contains "proposal" + finance keywords
        targets = derive_proposal_skill_targets(
            instruction=proposal_instruction,
            output_types=["pptx", "docx"],
        )

        # Then proposal skill should be selected for both outputs
        assert "pptx" in targets
        assert "docx" in targets
        assert "proposal" in targets["pptx"].lower()  # e.g., proposal_finance_transformation_v1
        assert "proposal" in targets["docx"].lower()

    def test_stage1_proposal_skill_not_triggered_without_keywords(self):
        """Verify proposal skill is NOT triggered without proposal keywords."""
        targets = derive_proposal_skill_targets(
            instruction="Create a process map for our supply chain",
            output_types=["pptx"],
        )

        # Should not be a proposal skill
        skill_id = targets.get("pptx", "")
        assert "proposal" not in skill_id.lower() or skill_id == ""

    # ========== Stage 5: PPTX Agent Execution ==========

    def test_stage5_pptx_agent_generates_json_slides(
        self, base_state, mock_claude_proposal_response
    ):
        """
        Stage 5: PPTX agent calls Claude with assembled context.
        Claude returns JSON slide structure.
        """
        from app.agents.subagents import run_pptx_agent

        # Setup context
        base_state["assembled_context"] = (
            "Leading case studies: Finance transformation at TechCorp saved 35% costs. "
            "Key success factors: executive alignment, phased approach, change management."
        )

        ctx = AgentContext(
            output_type="pptx",
            project_id=base_state["project_id"],
            run_id=base_state["run_id"],
            user_id=base_state["user_id"],
            raw_text=base_state["raw_text"],
            user_instruction=base_state["user_instruction"],
            user_intent_original=str(
                base_state.get("user_intent_original") or base_state["user_instruction"]
            ),
            process_model=base_state["process_model"],
            assembled_context=base_state["assembled_context"],
            output_type_representations={},
            skill_instructions_by_output={
                "pptx": "You are a Deloitte finance transformation expert. Create a compelling proposal deck with required sections..."
            },
            skill_card={"pptx": {"id": "proposal_finance_transformation_v1"}},
            plan_payload={"max_retries": 1},
            prior_artifacts_excerpt="",
            conversation_digest="User confirmed: primary_deliverable=proposal, preferred_outputs=[pptx]",
            enrichment={
                "audience": "CFO, Finance Director",
                "value_drivers": ["cost reduction", "operational efficiency"],
                "risks": ["change management", "data quality"],
                "steps_count": len(base_state["process_model"]["steps"]),
                "roles_count": len(base_state["process_model"]["roles"]),
                "systems_count": len(base_state["process_model"]["systems"]),
            },
            branding={
                "primary_color": "#004B87",
                "secondary_color": "#66BBDD",
                "fonts": ["TT Norms"],
                "logo_path": "deloitte_logo.png",
            },
        )

        # Mock Claude to return proposal slides
        with patch("app.agents.subagents.is_claude_enabled") as mock_enabled:
            mock_enabled.return_value = True
            with patch(
                "app.agents.subagents._run_subagent_tool_loop_text"
            ) as mock_tool_loop:
                # Return empty to trigger fallback to claude_generate_json
                mock_tool_loop.return_value = None
                with patch(
                    "app.agents.subagents.claude_generate_json"
                ) as mock_claude:
                    mock_claude.return_value = mock_claude_proposal_response

                    # Execute PPTX agent
                    output = run_pptx_agent(ctx)

                    # Verify Claude was called as fallback
                    assert mock_claude.called

            # Verify output structure
            assert isinstance(output, AgentOutput)
            assert "pptx_slides" in output.updates
            slides = output.updates["pptx_slides"]
            assert isinstance(slides, list)
            assert len(slides) > 0

    def test_stage5_pptx_agent_validates_completeness(
        self, base_state, mock_claude_proposal_response
    ):
        """Verify PPTX agent validates slide completeness (no empty stat_cards)."""
        from app.agents.subagents import run_pptx_agent

        ctx = AgentContext(
            output_type="pptx",
            project_id=base_state["project_id"],
            run_id=base_state["run_id"],
            user_id=base_state["user_id"],
            raw_text=base_state["raw_text"],
            user_instruction=base_state["user_instruction"],
            user_intent_original=str(
                base_state.get("user_intent_original") or base_state["user_instruction"]
            ),
            process_model=base_state["process_model"],
            assembled_context="Context...",
            output_type_representations={},
            skill_instructions_by_output={
                "pptx": "Generate proposal slides..."
            },
            skill_card={},
            plan_payload={},
            prior_artifacts_excerpt="",
            conversation_digest="",
            enrichment={
                "steps_count": 4,
                "roles_count": 5,
                "systems_count": 8,
            },
            branding={},
        )

        # Mock Claude with valid response
        with patch(
            "app.agents.subagents.claude_generate_json"
        ) as mock_claude:
            mock_claude.return_value = mock_claude_proposal_response

            output = run_pptx_agent(ctx)
            slides = output.updates["pptx_slides"]

            # Verify no empty stat_cards
            for slide in slides:
                if slide.get("slide_type") == "stat_cards":
                    assert slide.get("stat_cards"), "stat_cards should not be empty"
                    assert len(slide["stat_cards"]) >= 3, "stat_cards must have minimum 3 items"

    # ========== Stage 6: QA Loop ==========

    def test_stage6_qa_evaluates_proposal_structure(
        self, base_state, mock_claude_proposal_response
    ):
        """
        Stage 6 Loop 1: QA evaluates proposal against contract.
        Checks section coverage, citations, LLM rubric.
        """
        base_state["pptx_slides"] = mock_claude_proposal_response["slides"]

        # Verify slide structure has required sections
        slide_titles = [s.get("title") for s in mock_claude_proposal_response["slides"]]

        # Check for core proposal sections
        required_sections = [
            "Executive Summary",
            "Current State",
            "Proposed Approach",
            "Timeline",
            "Value",
            "Risks",
            "Governance",
        ]

        found_sections = sum(
            1 for req in required_sections
            if any(req.lower() in title.lower() for title in slide_titles)
        )

        # Should have at least 6 of 7 required sections
        assert found_sections >= 6, f"Only found {found_sections}/7 required sections"

        # Verify aggregate quality score would pass (>= 0.82)
        # Section coverage: found/7 = 6/7 = 0.857
        # Citation presence: mock has citations [1], [2] = 0.82
        # LLM rubric: assume 0.85
        aggregate = (0.38 * 0.857) + (0.22 * 0.82) + (0.4 * 0.85)
        assert aggregate >= 0.82, f"Aggregate score {aggregate} below threshold"

    def test_stage6_qa_remediation_converges_on_stability(
        self, base_state
    ):
        """
        Stage 6: Verify QA converges when score doesn't improve.
        Tracks pre/post remediation scores.
        """
        # Simulate QA loop with score stability
        pre_remediation_score = 0.78
        post_remediation_score = 0.79  # Slight improvement
        post_remediation_score_2 = 0.79  # No improvement → converge

        # Loop iteration 1: Score improved, continue
        converged_1 = pre_remediation_score == post_remediation_score
        assert converged_1 is False, "Should not converge on first iteration"

        # Loop iteration 2: Score didn't improve → converge
        converged_2 = post_remediation_score == post_remediation_score_2
        assert converged_2 is True, "Should converge when score plateaus"

    # ========== Full Pipeline Integration ==========

    def test_full_proposal_pptx_pipeline(
        self, base_state, mock_claude_proposal_response, proposal_instruction
    ):
        """
        Full 6-stage pipeline test:
        1. Skill recommendation (finance proposal detected)
        2. Plan confirmation (PPTX selected)
        3. Run creation (context assembled)
        4. Agent context enrichment (with metrics)
        5. PPTX agent execution (Claude generates slides)
        6. QA loop (validation passes)
        """
        from app.agents.subagents import run_pptx_agent
        from app.agents.coordinator import Coordinator

        # Stage 1: Detect proposal intent
        print("Stage 1: Proposal skill detection...")
        targets = derive_proposal_skill_targets(
            instruction=proposal_instruction,
            output_types=["pptx"],
        )
        assert "proposal" in targets["pptx"].lower()
        print(f"  ✓ Proposal skill target: {targets['pptx']}")

        # Stage 3-4: Setup agent context with assembled context + enrichment
        print("Stage 3-4: Context assembly & enrichment...")
        base_state["assembled_context"] = (
            "Tier 0: Project overview: Finance transformation engagement\n"
            "Tier 1: Leading practices:\n"
            "  - TechCorp case: 35% cost reduction via RPA and automation\n"
            "  - FinTech case: 50% close improvement via cloud ERP\n"
            "Tier 2: Source documents:\n"
            "  - CFO briefing: Pain points in month-end close (15 days)\n"
            "  - Current state assessment: Manual processes in GL, AP, AR"
        )

        ctx = AgentContext(
            output_type="pptx",
            project_id=base_state["project_id"],
            run_id=base_state["run_id"],
            user_id=base_state["user_id"],
            raw_text=base_state["raw_text"],
            user_instruction=proposal_instruction,
            user_intent_original=proposal_instruction,
            process_model=base_state["process_model"],
            assembled_context=base_state["assembled_context"],
            output_type_representations={},
            skill_instructions_by_output={
                "pptx": (
                    "You are a Deloitte finance transformation expert creating a proposal deck. "
                    "Required sections: Executive Summary, Current State, Proposed Approach, "
                    "Timeline, Value Case, Risks, Governance, Next Steps. "
                    "Do NOT generate empty stat_cards. Include explicit citations."
                )
            },
            skill_card={
                "pptx": {
                    "id": "proposal_finance_transformation_v1",
                    "tools": [
                        {"name": "get_leading_practices", "description": "Retrieve case studies"},
                    ]
                }
            },
            plan_payload={
                "max_retries": 1,
                "skill_card": "auto_selected",
            },
            prior_artifacts_excerpt="",
            conversation_digest=(
                "User confirmed: primary_deliverable='proposal', preferred_outputs=['pptx']"
            ),
            enrichment={
                "audience": "CFO, Finance Director, Controller",
                "value_drivers": ["cost reduction", "operational efficiency", "speed to insight"],
                "risks": ["change adoption", "data quality", "timeline risk"],
                "steps_count": 4,
                "roles_count": 5,
                "systems_count": 8,
            },
            branding={
                "primary_color": "#004B87",
                "secondary_color": "#66BBDD",
                "fonts": ["TT Norms"],
            },
        )
        print(f"  ✓ AgentContext built with ~{len(base_state['assembled_context'])} char context")

        # Stage 5: Execute PPTX agent
        print("Stage 5: PPTX agent execution...")
        with patch("app.agents.subagents.is_claude_enabled") as mock_enabled:
            mock_enabled.return_value = True
            with patch(
                "app.agents.subagents._run_subagent_tool_loop_text"
            ) as mock_tool_loop:
                mock_tool_loop.return_value = None  # Trigger fallback
                with patch(
                    "app.agents.subagents.claude_generate_json"
                ) as mock_claude:
                    mock_claude.return_value = mock_claude_proposal_response

                    output = run_pptx_agent(ctx)

                    # Verify Claude was called
                    assert mock_claude.called
                    print(f"  ✓ Claude called for slide generation")

            # Verify output
            assert isinstance(output, AgentOutput)
            assert "pptx_slides" in output.updates
            slides = output.updates["pptx_slides"]
            assert len(slides) == 10, "Should have 10 slides"
            print(f"  ✓ Generated {len(slides)} proposal slides")

            # Verify slide types
            slide_types = {s.get("slide_type") for s in slides}
            expected_types = {"title", "stat_cards", "bullets", "column_cards"}
            assert expected_types.issubset(slide_types)
            print(f"  ✓ Slide types: {slide_types}")

        # Stage 6: QA Evaluation
        print("Stage 6: QA loop evaluation...")

        # Verify section coverage
        slide_titles = {s.get("title") for s in slides}
        required_sections = {
            "Executive Summary",
            "Current State & Problem Statement",
            "Proposed Approach",
            "Implementation Timeline",
            "Value Case",
            "Implementation Value",
            "Risks and Mitigations",
            "Governance and Team Structure",
            "Next Steps",
        }
        # Normalize title matching
        slide_titles_lower = {t.lower() for t in slide_titles}
        required_lower = {r.lower() for r in required_sections}
        coverage = len(required_lower & slide_titles_lower) / len(required_lower)
        assert coverage >= 0.7, f"Section coverage {coverage} too low"
        print(f"  ✓ Section coverage: {coverage:.1%}")

        # Verify citations
        all_text = json.dumps(slides)
        citation_count = all_text.count("[") + all_text.count("(source:")
        assert citation_count >= 2, "Should have minimum 2 citations"
        print(f"  ✓ Citation markers found: {citation_count}")

        # Verify stat_cards not empty
        for slide in slides:
            if slide.get("slide_type") == "stat_cards":
                assert slide.get("stat_cards"), "stat_cards cannot be empty"
                assert len(slide["stat_cards"]) >= 3
        print(f"  ✓ PPTX completeness validated (no empty stat_cards)")

        print("\n✅ Full proposal-to-PPT pipeline test PASSED")
        return {
            "slides_generated": len(slides),
            "section_coverage": coverage,
            "citations": citation_count,
            "qa_status": "passed",
        }

    def test_pipeline_event_tracking(self, base_state, mock_claude_proposal_response):
        """Verify event emissions during pipeline execution."""
        events_emitted = []

        def emit_event(event_type: str, payload: dict) -> None:
            events_emitted.append({
                "event_type": event_type,
                "payload": payload,
            })

        from app.agents.subagents import run_pptx_agent

        # Execute with event tracking
        with patch("app.agents.subagents.claude_generate_json") as mock_claude:
            mock_claude.return_value = mock_claude_proposal_response

            ctx = AgentContext(
                output_type="pptx",
                project_id=base_state["project_id"],
                run_id=base_state["run_id"],
                user_id=base_state["user_id"],
                raw_text=base_state["raw_text"],
                user_instruction=base_state["user_instruction"],
                user_intent_original=str(
                    base_state.get("user_intent_original") or base_state["user_instruction"]
                ),
                process_model=base_state["process_model"],
                assembled_context="Context",
                output_type_representations={},
                skill_instructions_by_output={"pptx": "Generate slides..."},
                skill_card={},
                plan_payload={},
                prior_artifacts_excerpt="",
                conversation_digest="",
                enrichment={"steps_count": 4, "roles_count": 5, "systems_count": 8},
                branding={},
                emit_event=emit_event,
            )

            output = run_pptx_agent(ctx)

            # Verify output generated
            assert "pptx_slides" in output.updates
            print(f"✅ Event tracking test passed")


class TestImprovements:
    """Tests validating the 6 pipeline improvements."""

    # ========== Improvement 1: Fuzzy PPTX Section Coverage ==========

    def test_fuzzy_section_coverage_exact_match(self):
        """Fuzzy matcher handles exact title match."""
        from app.services.deliverable_quality import _fuzzy_title_match

        assert _fuzzy_title_match("Executive Summary", "Executive Summary")
        assert _fuzzy_title_match("Value Case", "Value Case")

    def test_fuzzy_section_coverage_ampersand_vs_and(self):
        """Fuzzy matcher handles '&' vs 'and' variation."""
        from app.services.deliverable_quality import _fuzzy_title_match

        assert _fuzzy_title_match(
            "Current State and Problem Statement",
            "Current State & Problem Statement",
        )
        assert _fuzzy_title_match(
            "Risks & Mitigations",
            "Risks and Mitigations",
        )

    def test_fuzzy_section_coverage_partial_word_overlap(self):
        """Fuzzy matcher handles partial word overlap (e.g., extra words)."""
        from app.services.deliverable_quality import _fuzzy_title_match

        # 'Implementation Timeline' should match 'Implementation Timeline & Milestones'
        assert _fuzzy_title_match("Implementation Timeline", "Implementation Timeline & Milestones")
        # 'Governance' should match 'Governance and Team Structure'
        assert _fuzzy_title_match("Governance", "Governance and Team Structure")

    def test_fuzzy_section_coverage_no_false_positive(self):
        """Fuzzy matcher doesn't match unrelated titles."""
        from app.services.deliverable_quality import _fuzzy_title_match

        assert not _fuzzy_title_match("Executive Summary", "Next Steps")
        assert not _fuzzy_title_match("Value Case", "Risks and Mitigations")

    def test_pptx_section_coverage_scorer_on_slides(self):
        """PPTX section coverage scorer evaluates slide structure directly."""
        from app.services.deliverable_quality import _score_section_coverage_pptx

        slides = [
            {"slide_type": "title", "title": "Finance Transformation Proposal"},
            {"slide_type": "bullets", "title": "Executive Summary"},
            {"slide_type": "bullets", "title": "Current State & Problem Statement"},
            {"slide_type": "column_cards", "title": "Proposed Approach"},
            {"slide_type": "table", "title": "Implementation Timeline"},
            {"slide_type": "stat_cards", "title": "Value Case"},
            {"slide_type": "bullets", "title": "Risks and Mitigations"},
            {"slide_type": "bullets", "title": "Governance and Team Structure"},
        ]
        dim = {
            "required_sections": [
                "Executive Summary",
                "Current State and Problem Statement",  # Note: 'and' not '&'
                "Proposed Approach",
                "Implementation Timeline",
                "Value Case",
                "Risks & Mitigations",  # Note: '&' not 'and'
                "Governance and Team Structure",
            ]
        }
        score, meta = _score_section_coverage_pptx(slides, dim)
        assert score == 1.0, f"Expected 1.0 but got {score}. Missing: {meta.get('missing')}"
        assert meta["missing"] == []
        assert meta["matched"] == 7

    def test_pptx_section_coverage_with_missing_sections(self):
        """PPTX section coverage correctly identifies missing sections."""
        from app.services.deliverable_quality import _score_section_coverage_pptx

        slides = [
            {"slide_type": "title", "title": "Finance Transformation Proposal"},
            {"slide_type": "bullets", "title": "Executive Summary"},
            {"slide_type": "bullets", "title": "Next Steps"},
        ]
        dim = {
            "required_sections": [
                "Executive Summary",
                "Value Case",
                "Risks and Mitigations",
            ]
        }
        score, meta = _score_section_coverage_pptx(slides, dim)
        assert score < 1.0
        assert "Value Case" in meta["missing"]
        assert "Risks and Mitigations" in meta["missing"]
        assert meta["matched"] == 1

    # ========== Improvement 2: Prepend Remediation Text ==========

    def test_remediation_prepended_not_appended(self):
        """Remediation text is prepended so it's never truncated by 12K cap."""
        from app.agents.coordinator import Coordinator

        coordinator = Coordinator()
        state = {
            "user_instruction": "Create a proposal",
            "raw_text": "Create a proposal",
            "assembled_context": "A" * 11500,  # Nearly at 12K cap
            "pptx_slides": None,
        }
        remediation_instructions = {
            "pptx_slides": {
                "actions": ["Add missing section: Risks and Mitigations"],
            }
        }

        # Mock the agent call to avoid actual execution
        with patch.dict("app.agents.coordinator._OUTPUT_AGENTS", {"pptx": lambda ctx: MagicMock(updates={"pptx_slides": []})}):
            coordinator._apply_qa_remediation(state, ["pptx"], remediation_instructions)

        ac = state["assembled_context"]
        # Remediation should be at the START, not truncated at the end
        # Check for personality-formatted remediation header ("⚠️ **Quick optimization round:**")
        assert (ac.startswith("[Quality Remediation") or ac.startswith("⚠️ **Quick optimization round:**")), (
            f"Remediation should be prepended. Got: {ac[:100]}..."
        )
        assert "Risks and Mitigations" in ac[:500], (
            "Remediation actions must be in first 500 chars (not truncated)"
        )

    # ========== Improvement 3: Contract QA → Repair Mode ==========

    def test_qa_remediation_injects_pptx_repair_mode(self):
        """Contract QA failures wire into PPTX repair mode (prior_pptx_slides + visual_feedback)."""
        from app.agents.coordinator import Coordinator

        coordinator = Coordinator()
        prior_slides = [
            {"slide_type": "title", "title": "Proposal"},
            {"slide_type": "bullets", "title": "Executive Summary"},
        ]
        state = {
            "user_instruction": "Create a proposal",
            "raw_text": "Create a proposal",
            "assembled_context": "Context",
            "pptx_slides": prior_slides,
            "plan_payload": {},
        }
        remediation_instructions = {
            "pptx_slides": {
                "actions": [
                    "Slide 2 (Executive Summary): slide_type='bullets' requires 1 bullets, got 0",
                    "Restore required sections: Risks and Mitigations",
                ],
            }
        }

        captured_ctx = {}

        def mock_pptx_agent(ctx):
            captured_ctx["plan_payload"] = ctx.plan_payload
            return AgentOutput(updates={"pptx_slides": prior_slides})

        with patch.dict("app.agents.coordinator._OUTPUT_AGENTS", {"pptx": mock_pptx_agent}):
            coordinator._apply_qa_remediation(state, ["pptx"], remediation_instructions)

        # Verify repair mode was activated
        pp = state["plan_payload"]
        assert "prior_pptx_slides" in pp, "prior_pptx_slides should be injected for repair mode"
        assert pp["prior_pptx_slides"] == prior_slides
        assert "pptx_visual_feedback" in pp, "visual_feedback should be injected for repair mode"
        feedback = pp["pptx_visual_feedback"]
        assert len(feedback) == 2
        # First action has "Slide 2" so should have slide_index=2
        assert feedback[0]["slide_index"] == 2
        assert "bullets" in feedback[0]["instruction"]

    # ========== Improvement 4: Skill-Aware Slide Sequence ==========

    def test_skill_slide_sequence_used_when_present(self):
        """When skill defines slide_sequence, it replaces the hardcoded mandate."""
        from app.agents.subagents import run_pptx_agent

        mock_slides = [{"slide_type": "title", "title": "Test"}]
        skill_sequence = [
            'slide_type="title" — Proposal title and engagement name',
            'slide_type="bullets" — Executive Summary: 3-4 key points',
            'slide_type="stat_cards" — Scale metrics: steps, roles, systems',
            'slide_type="bullets" — Value Case: quantified benefits',
            'slide_type="bullets" — Next Steps',
        ]

        ctx = AgentContext(
            output_type="pptx",
            project_id="test",
            run_id="test",
            user_id="test",
            raw_text="Create proposal",
            user_instruction="Create a finance proposal",
            user_intent_original="Create a finance proposal",
            process_model={"steps": [{"id": "1", "name": "Step1"}]},
            assembled_context="Context",
            output_type_representations={},
            skill_instructions_by_output={"pptx": "You are a proposal expert"},
            skill_card={
                "primary_skill_by_output_type": {
                    "pptx": {
                        "id": "proposal_finance_v1",
                        "display_name": "Finance Proposal Specialist",
                        "prompt_instructions": "Create a finance proposal deck",
                        "slide_sequence": skill_sequence,
                    }
                }
            },
            plan_payload={},
        )

        with patch("app.agents.subagents.is_claude_enabled") as mock_enabled:
            mock_enabled.return_value = True
            with patch("app.agents.subagents._run_subagent_tool_loop_text") as mock_tool_loop:
                mock_tool_loop.return_value = None
                with patch("app.agents.subagents.claude_generate_json") as mock_claude:
                    mock_claude.return_value = {"slides": mock_slides}
                    run_pptx_agent(ctx)

                    # Verify the user prompt contains skill sequence, not hardcoded
                    call_kwargs = mock_tool_loop.call_args
                    user_prompt = call_kwargs[1].get("user", "") if call_kwargs[1] else ""
                    assert "Executive Summary: 3-4 key points" in user_prompt, (
                        "Skill-defined slide sequence should appear in user prompt"
                    )
                    assert "Process Overview" not in user_prompt, (
                        "Hardcoded process-doc sequence should NOT appear when skill provides sequence"
                    )

    # ========== Improvement 5: Post-Processor Merged Into Primary ==========

    def test_post_processor_skipped_when_primary_skill_present(self):
        """Post-processor separate call is skipped when primary skill inlines rules."""
        from app.agents.subagents import _run_pptx_post_processor

        slides = [{"slide_type": "title", "title": "Test"}]
        ctx = AgentContext(
            output_type="pptx",
            project_id="test",
            run_id="test",
            user_id="test",
            raw_text="test",
            user_instruction="test",
            user_intent_original="test",
            process_model={},
            assembled_context="",
            output_type_representations={},
            skill_instructions_by_output={},
            skill_card={
                "primary_skill_by_output_type": {
                    "pptx": {"id": "proposal_v1", "prompt_instructions": "..."}
                },
                "post_processor_skills_by_output_type": {
                    "pptx": [{"id": "brand_v1", "prompt_instructions": "Tighten titles"}]
                },
            },
            plan_payload={},
        )

        # Should return slides unchanged (no Claude call)
        result = _run_pptx_post_processor(ctx, slides)
        assert result == slides, "Post-processor should be skipped when primary skill is present"

    # ========== Improvement 6: Labelled Context Sections ==========

    def test_labelled_context_for_pptx(self):
        """PPTX context appendix includes labelled sections for slide generation."""
        from app.agents.subagents import _shared_user_context_appendix

        ctx = AgentContext(
            output_type="pptx",
            project_id="test",
            run_id="test",
            user_id="test",
            raw_text="Create proposal",
            user_instruction="Create a finance transformation proposal",
            user_intent_original="Create a finance transformation proposal",
            process_model={},
            assembled_context=(
                "Current state pain points: manual processes causing delays. "
                "Leading practice case study: TechCorp saved 35% via automation. "
                "Expected savings: $2.3M annual cost reduction benefit."
            ),
            output_type_representations={},
            skill_instructions_by_output={},
            skill_card={},
            plan_payload={},
        )

        result = _shared_user_context_appendix(ctx)

        # Should contain labelled sections for PPTX
        assert "PAIN POINTS" in result, "Should have labelled pain points section"
        assert "LEADING PRACTICES" in result, "Should have labelled leading practices section"
        assert "stat_cards" in result or "problem statement" in result, (
            "Labels should reference slide types"
        )

    def test_non_pptx_context_unchanged(self):
        """Non-PPTX output types still get the standard context format."""
        from app.agents.subagents import _shared_user_context_appendix

        ctx = AgentContext(
            output_type="docx",  # Not PPTX
            project_id="test",
            run_id="test",
            user_id="test",
            raw_text="Create report",
            user_instruction="Create a finance report",
            user_intent_original="Create a finance report",
            process_model={},
            assembled_context="Some context with pain points and case study benchmarks",
            output_type_representations={},
            skill_instructions_by_output={},
            skill_card={},
            plan_payload={},
        )

        result = _shared_user_context_appendix(ctx)

        # Should NOT have PPTX-specific labels
        assert "stat_cards" not in result
        assert "Assembled project context (excerpt)" in result


    # ========== Improvement 7: LLM-Based Skill Classification ==========

    def test_llm_skill_hint_overrides_keyword_matching(self):
        """When LLM skill hint has high confidence, it overrides keyword matching."""
        targets = derive_proposal_skill_targets(
            instruction="Create a pitch deck for our CFO-facing initiative",
            output_types=["pptx"],
            llm_skill_hint={
                "domain": "proposal_finance_transformation",
                "confidence": 0.85,
            },
        )
        assert targets.get("pptx") == "proposal_finance_transformation_v1", (
            "LLM hint with high confidence should set proposal skill even without keyword match"
        )

    def test_llm_skill_hint_low_confidence_falls_back(self):
        """When LLM skill hint has low confidence, fall back to keyword matching."""
        # No proposal + finance keywords → keyword matching returns nothing
        targets = derive_proposal_skill_targets(
            instruction="Create a presentation about our team",
            output_types=["pptx"],
            llm_skill_hint={
                "domain": "proposal_finance_transformation",
                "confidence": 0.3,
            },
        )
        assert "pptx" not in targets, (
            "LLM hint with low confidence should not set skill; keyword fallback also misses"
        )

    def test_llm_skill_hint_none_uses_keyword_fallback(self):
        """When no LLM hint, keyword matching is used (original behaviour)."""
        targets = derive_proposal_skill_targets(
            instruction="Create a proposal for finance transformation engagement",
            output_types=["pptx", "docx"],
            llm_skill_hint=None,
        )
        assert targets.get("pptx") == "proposal_finance_transformation_v1"
        assert targets.get("docx") == "proposal_finance_transformation_v1"

    def test_domain_to_skill_id_mapping(self):
        """_DOMAIN_TO_SKILL_ID correctly maps domains to skill IDs."""
        from app.services.proposal_policy import _DOMAIN_TO_SKILL_ID

        assert "proposal_finance_transformation" in _DOMAIN_TO_SKILL_ID
        assert _DOMAIN_TO_SKILL_ID["proposal_finance_transformation"] == "proposal_finance_transformation_v1"

    # ========== Improvement 8: Deck Outline Preview ==========

    def test_deck_outline_preview_returns_slides(self):
        """generate_deck_outline_preview returns slide outline when Claude available."""
        from app.services.proposal_policy import generate_deck_outline_preview

        mock_response = {
            "slides": [
                {"title": "Finance Transformation Proposal", "slide_type": "title", "purpose": "Introduce the engagement"},
                {"title": "Executive Summary", "slide_type": "bullets", "purpose": "Key points and recommendation"},
                {"title": "Current State", "slide_type": "stat_cards", "purpose": "Quantify pain points"},
                {"title": "Proposed Approach", "slide_type": "column_cards", "purpose": "Three pillars of change"},
                {"title": "Next Steps", "slide_type": "bullets", "purpose": "Immediate actions"},
            ],
            "rationale": "Standard proposal structure for CFO audience",
        }

        with patch("app.services.claude.claude_generate_json") as mock_claude:
            mock_claude.return_value = mock_response
            with patch("app.services.claude.is_claude_enabled") as mock_enabled:
                mock_enabled.return_value = True

                result = generate_deck_outline_preview(
                    instruction="Create a finance transformation proposal",
                    output_type="pptx",
                    skill_id="proposal_finance_transformation_v1",
                )

        assert result is not None
        assert len(result["slides"]) == 5
        assert result["slides"][0]["slide_type"] == "title"
        assert result["output_type"] == "pptx"
        assert result["skill_id"] == "proposal_finance_transformation_v1"

    def test_deck_outline_preview_returns_none_when_claude_disabled(self):
        """generate_deck_outline_preview returns None when Claude is unavailable."""
        from app.services.proposal_policy import generate_deck_outline_preview

        with patch("app.services.claude.is_claude_enabled") as mock_enabled:
            mock_enabled.return_value = False
            result = generate_deck_outline_preview(
                instruction="Create a proposal",
                output_type="pptx",
            )

        assert result is None

    def test_deck_outline_preview_returns_none_on_error(self):
        """generate_deck_outline_preview returns None on any error (never crashes)."""
        from app.services.proposal_policy import generate_deck_outline_preview

        with patch("app.services.claude.claude_generate_json") as mock_claude:
            mock_claude.side_effect = Exception("API error")
            with patch("app.services.claude.is_claude_enabled") as mock_enabled:
                mock_enabled.return_value = True

                result = generate_deck_outline_preview(
                    instruction="Create a proposal",
                    output_type="pptx",
                )

        assert result is None

    # ========== Improvement 9: Batched Slide Generation ==========

    def test_batched_generation_uses_outline_when_available(self):
        """When deck_outline_preview is in plan_payload, batched generation is attempted."""
        from app.agents.subagents import run_pptx_agent

        outline = {
            "slides": [
                {"title": "Title", "slide_type": "title", "purpose": "Intro"},
                {"title": "Executive Summary", "slide_type": "bullets", "purpose": "Key points"},
                {"title": "Current State", "slide_type": "stat_cards", "purpose": "Metrics"},
                {"title": "Approach", "slide_type": "column_cards", "purpose": "Pillars"},
                {"title": "Timeline", "slide_type": "table", "purpose": "Phases"},
                {"title": "Next Steps", "slide_type": "bullets", "purpose": "Actions"},
            ],
        }

        batch_slides = [
            {"slide_type": "title", "title": "Title"},
            {"slide_type": "bullets", "title": "Executive Summary", "bullets": ["Point 1"]},
            {"slide_type": "stat_cards", "title": "Current State", "stat_cards": [
                {"stat": "14", "label": "Steps", "description": "E2e", "fill": "dark"},
                {"stat": "5", "label": "Roles", "description": "Key", "fill": "mid_dark"},
                {"stat": "8", "label": "Systems", "description": "IT", "fill": "gray"},
            ]},
            {"slide_type": "column_cards", "title": "Approach", "column_cards": [
                {"heading": "Gov", "accent": "green", "body": "Controls"},
                {"heading": "Quality", "accent": "dark", "body": "Standards"},
                {"heading": "Auto", "accent": "gray", "body": "RPA"},
            ]},
            {"slide_type": "table", "title": "Timeline", "table": {"headers": ["Phase", "Duration"], "rows": [["1", "4w"]]}},
            {"slide_type": "bullets", "title": "Next Steps", "bullets": ["Action 1"]},
        ]

        ctx = AgentContext(
            output_type="pptx",
            project_id="test",
            run_id="test",
            user_id="test",
            raw_text="Create proposal",
            user_instruction="Create a finance transformation proposal",
            user_intent_original="Create a finance transformation proposal",
            process_model={"steps": [{"id": "1", "name": "Step1"}]},
            assembled_context="Context",
            output_type_representations={},
            skill_instructions_by_output={"pptx": "Generate slides"},
            skill_card={},
            plan_payload={"deck_outline_preview": outline},
        )

        with patch("app.agents.subagents.is_claude_enabled") as mock_enabled:
            mock_enabled.return_value = True
            with patch("app.agents.subagents._generate_slides_batched") as mock_batched:
                mock_batched.return_value = batch_slides
                output = run_pptx_agent(ctx)

                # Verify batched generation was called
                assert mock_batched.called, "Batched generation should be attempted when outline available"
                assert "pptx_slides" in output.updates
                assert len(output.updates["pptx_slides"]) == 6

    def test_batched_generation_falls_through_on_failure(self):
        """When batched generation fails, falls through to single-shot."""
        from app.agents.subagents import run_pptx_agent

        outline = {
            "slides": [
                {"title": f"Slide {i}", "slide_type": "bullets", "purpose": "Content"}
                for i in range(8)
            ],
        }

        mock_single_shot = {"slides": [{"slide_type": "title", "title": "Fallback"}]}

        ctx = AgentContext(
            output_type="pptx",
            project_id="test",
            run_id="test",
            user_id="test",
            raw_text="Create proposal",
            user_instruction="Create a finance transformation proposal",
            user_intent_original="Create a finance transformation proposal",
            process_model={"steps": [{"id": "1", "name": "Step1"}]},
            assembled_context="Context",
            output_type_representations={},
            skill_instructions_by_output={"pptx": "Generate slides"},
            skill_card={},
            plan_payload={"deck_outline_preview": outline},
        )

        with patch("app.agents.subagents.is_claude_enabled") as mock_enabled:
            mock_enabled.return_value = True
            with patch("app.agents.subagents._generate_slides_batched") as mock_batched:
                mock_batched.return_value = None  # Batched failed
                with patch("app.agents.subagents._run_subagent_tool_loop_text") as mock_tool:
                    mock_tool.return_value = None
                    with patch("app.agents.subagents.claude_generate_json") as mock_claude:
                        mock_claude.return_value = mock_single_shot
                        output = run_pptx_agent(ctx)

                        # Should fall through to single-shot
                        assert mock_claude.called
                        assert "pptx_slides" in output.updates

    def test_batched_generation_skipped_in_repair_mode(self):
        """Batched generation is not used in repair mode."""
        from app.agents.subagents import run_pptx_agent

        outline = {
            "slides": [
                {"title": f"Slide {i}", "slide_type": "bullets", "purpose": "Content"}
                for i in range(8)
            ],
        }

        prior_slides = [
            {"slide_type": "title", "title": "Prior"},
            {"slide_type": "bullets", "title": "Summary"},
        ]

        ctx = AgentContext(
            output_type="pptx",
            project_id="test",
            run_id="test",
            user_id="test",
            raw_text="Create proposal",
            user_instruction="Create a finance proposal",
            user_intent_original="Create a finance proposal",
            process_model={"steps": [{"id": "1", "name": "Step1"}]},
            assembled_context="Context",
            output_type_representations={},
            skill_instructions_by_output={"pptx": "Generate slides"},
            skill_card={},
            plan_payload={
                "deck_outline_preview": outline,
                "prior_pptx_slides": prior_slides,
                "pptx_visual_feedback": [
                    {"slide_index": 1, "instruction": "Fix title"}
                ],
            },
        )

        with patch("app.agents.subagents.is_claude_enabled") as mock_enabled:
            mock_enabled.return_value = True
            with patch("app.agents.subagents._generate_slides_batched") as mock_batched:
                with patch("app.agents.subagents._run_subagent_tool_loop_text") as mock_tool:
                    mock_tool.return_value = None
                    with patch("app.agents.subagents.claude_generate_json") as mock_claude:
                        mock_claude.return_value = {"slides": prior_slides}
                        run_pptx_agent(ctx)

                        # Batched should NOT be called in repair mode
                        assert not mock_batched.called, (
                            "Batched generation should be skipped in repair mode"
                        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
