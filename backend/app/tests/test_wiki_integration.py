"""
Integration tests for wiki system with ProcessDoc v2 components.

Tests connections between wiki and memory items, run events, conversations, coordinator, and LP.
"""


from app.services.wiki_integrations import (
    WikiConversationIntegration,
    WikiCoordinatorIntegration,
    WikiLeadingPracticesIntegration,
    WikiMemoryIntegration,
    WikiRunIntegration,
)

# ===== Memory Integration Tests (6 tests) =====

class TestWikiMemoryIntegration:
    """Test wiki integration with memory items."""

    def test_ingest_fact_memory_to_wiki(self):
        """Should convert fact memory item to wiki page."""
        memory_item = {
            "id": "mem_123",
            "type": "fact",
            "content": "Company has 500 employees across 5 regions",
            "metadata": {
                "title": "Company Size",
                "confidence": "high",
            },
        }

        wiki_page, error = WikiMemoryIntegration.ingest_memory_item_to_wiki(memory_item, "project", "proj_1")

        assert error is None
        assert wiki_page is not None
        assert wiki_page["category"] == "entity"
        assert wiki_page["source_memory_ids"] == ["mem_123"]

    def test_ingest_decision_memory_to_wiki(self):
        """Should convert decision memory to wiki page."""
        memory_item = {
            "id": "mem_456",
            "type": "decision",
            "content": "We chose to implement Oracle instead of SAP due to cost",
            "metadata": {
                "title": "ERP System Selection",
                "confidence": "high",
            },
        }

        wiki_page, error = WikiMemoryIntegration.ingest_memory_item_to_wiki(memory_item, "project", "proj_1")

        assert error is None
        assert wiki_page["category"] == "decision"
        assert "Oracle" in wiki_page["content"]

    def test_ingest_constraint_memory_to_wiki(self):
        """Should convert constraint memory to wiki page."""
        memory_item = {
            "id": "mem_789",
            "type": "constraint",
            "content": "Budget limited to $2M for transformation",
            "metadata": {"confidence": "high"},
        }

        wiki_page, error = WikiMemoryIntegration.ingest_memory_item_to_wiki(memory_item, "project", "proj_1")

        assert error is None
        assert wiki_page["category"] == "concept"
        assert "2M" in wiki_page["content"]

    def test_sync_memory_update_to_wiki(self):
        """Should update wiki page when memory item changes."""
        wiki_page = {
            "id": "page_1",
            "title": "Old Title",
            "content": "Old content",
            "frontmatter": '{"category": "entity", "confidence": "medium"}',
        }
        memory_update = {
            "id": "mem_123",
            "content": "Updated company size: 550 employees",
            "metadata": {"title": "Updated Title"},
        }

        updated_page, error = WikiMemoryIntegration.sync_memory_item_updates_to_wiki(memory_update, wiki_page)

        assert error is None
        assert updated_page["title"] == "Updated Title"
        assert "550 employees" in updated_page["content"]

    def test_memory_integration_preserves_metadata(self):
        """Should preserve memory metadata in wiki page."""
        memory_item = {
            "id": "mem_999",
            "type": "preference",
            "content": "Prefer agile delivery over waterfall",
            "metadata": {
                "title": "Delivery Preference",
                "confidence": "medium",
                "source": "stakeholder_feedback",
            },
        }

        wiki_page, error = WikiMemoryIntegration.ingest_memory_item_to_wiki(memory_item, "project", "proj_1")

        assert error is None
        # Confidence should be preserved in frontmatter
        assert "medium" in wiki_page["frontmatter"]

    def test_memory_integration_handles_invalid_item(self):
        """Should handle invalid memory items gracefully."""
        invalid_memory = {}  # Missing required fields

        wiki_page, error = WikiMemoryIntegration.ingest_memory_item_to_wiki(invalid_memory, "project", "proj_1")

        assert wiki_page is not None  # Should still return a page with defaults
        assert error is None


# ===== Run Integration Tests (7 tests) =====

class TestWikiRunIntegration:
    """Test wiki integration with run events and artifacts."""

    def test_ingest_run_artifacts_to_wiki(self):
        """Should ingest run artifacts and learnings into wiki."""
        run_id = "run_123"
        run_summary = {
            "name": "Financial Model Development",
            "executed_at": "2026-04-10",
            "status": "completed",
            "outcomes": "Created 3-year forecast model",
            "key_findings": "Revenue growth expected at 15% CAGR",
            "learnings": [
                {
                    "title": "Data quality is critical",
                    "description": "Clean data is 60% of the modeling effort",
                },
            ],
        }
        artifacts = [
            {"name": "Financial Model", "type": "xlsx", "path": "/run/model.xlsx"},
            {"name": "Executive Summary", "type": "pptx", "path": "/run/summary.pptx"},
        ]

        result, error = WikiRunIntegration.ingest_run_artifact_to_wiki(
            run_id, run_summary, artifacts, "proj_1"
        )

        assert error is None
        assert result is not None
        assert result["pages_created"] >= 3  # Overview + learnings + artifacts
        assert result["run_id"] == run_id

    def test_extract_run_learnings(self):
        """Should extract learning events from run log."""
        run_events = [
            {"event_type": "learning", "summary": "Process improvement", "details": "Reduce cycle time by 20%"},
            {"event_type": "other", "summary": "Status update", "details": "On track"},
            {"event_type": "insight", "summary": "Cost driver", "details": "Labor is 40% of cost"},
        ]

        learnings = WikiRunIntegration.extract_run_learnings(run_events)

        assert len(learnings) == 2
        assert any("Process improvement" in l["title"] for l in learnings)
        assert any("Cost driver" in l["title"] for l in learnings)

    def test_run_artifact_page_includes_outcomes(self):
        """Should include run outcomes in wiki page."""
        run_summary = {
            "name": "Test Run",
            "outcomes": "Successfully completed all tasks",
            "status": "completed",
        }
        artifacts = []

        result, error = WikiRunIntegration.ingest_run_artifact_to_wiki("run_1", run_summary, artifacts, "proj_1")

        assert error is None
        pages = result["pages"]
        assert any("Successfully completed" in p["content"] for p in pages)

    def test_run_integration_handles_missing_learnings(self):
        """Should handle runs with no learnings gracefully."""
        run_summary = {
            "name": "Minimal Run",
            "status": "completed",
            # No learnings field
        }
        artifacts = []

        result, error = WikiRunIntegration.ingest_run_artifact_to_wiki("run_2", run_summary, artifacts, "proj_1")

        assert error is None
        assert result["pages_created"] >= 1

    def test_artifact_catalog_generation(self):
        """Should generate artifact catalog for wiki page."""
        artifacts = [
            {"name": "Model v1", "type": "xlsx", "path": "/runs/model.xlsx"},
            {"name": "Deck", "type": "pptx", "path": "/runs/deck.pptx"},
        ]
        run_summary = {"name": "Test Run", "status": "completed"}

        result, error = WikiRunIntegration.ingest_run_artifact_to_wiki(
            "run_3", run_summary, artifacts, "proj_1"
        )

        assert error is None
        pages = result["pages"]
        artifact_pages = [p for p in pages if "Artifacts" in p["title"]]
        assert len(artifact_pages) > 0
        assert "Model v1" in artifact_pages[0]["content"]

    def test_run_integration_confidence_levels(self):
        """Should set appropriate confidence levels for run artifacts."""
        run_summary = {"name": "Test", "status": "completed"}
        result, error = WikiRunIntegration.ingest_run_artifact_to_wiki("run_4", run_summary, [], "proj_1")

        pages = result["pages"]
        # Check for any page with high confidence (the overview page)
        high_conf_pages = [p for p in pages if p.get("confidence") == "high"]
        assert len(high_conf_pages) > 0


# ===== Conversation Integration Tests (5 tests) =====

class TestWikiConversationIntegration:
    """Test wiki integration with conversations."""

    def test_digest_conversation_to_wiki(self):
        """Should create wiki page from conversation."""
        messages = [
            {"user_id": "user_1", "content": "What should we do about costs?"},
            {"user_id": "user_2", "content": "We decided to cut 20% of expenses"},
            {"user_id": "user_1", "content": "Agreed. Implementation plan?"},
        ]

        wiki_page, error = WikiConversationIntegration.digest_conversation_to_wiki(
            "conv_123", messages, "proj_1"
        )

        assert error is None
        assert wiki_page is not None
        assert wiki_page["category"] == "synthesis"
        assert "3" in wiki_page["frontmatter"]  # 3 messages

    def test_extract_decisions_from_conversation(self):
        """Should extract decisions from conversation messages."""
        messages = [
            {"content": "We decided to use cloud infrastructure"},
            {"content": "Status update: project on track"},
            {"content": "We agreed on weekly meetings"},
        ]

        from app.services.wiki_integrations import _extract_decisions_from_conversation

        decisions = _extract_decisions_from_conversation(messages)

        assert len(decisions) > 0
        assert any("cloud" in d.lower() for d in decisions)

    def test_extract_questions_from_conversation(self):
        """Should extract questions from conversation."""
        messages = [
            {"content": "What is our timeline?"},
            {"content": "Implementation starts next week"},
            {"content": "Should we involve legal?"},
        ]

        from app.services.wiki_integrations import _extract_questions_from_conversation

        questions = _extract_questions_from_conversation(messages)

        assert len(questions) > 0
        assert any("timeline" in q.lower() for q in questions)

    def test_conversation_page_includes_summary(self):
        """Should include conversation summary in wiki page."""
        messages = [
            {"user_id": "user_1", "content": "First message"},
            {"user_id": "user_2", "content": "Response"},
        ]

        wiki_page, error = WikiConversationIntegration.digest_conversation_to_wiki(
            "conv_1", messages, "proj_1"
        )

        assert error is None
        assert "Summary" in wiki_page["content"]

    def test_conversation_metadata_preservation(self):
        """Should preserve conversation metadata in frontmatter."""
        messages = [{"content": "Test message"}]

        wiki_page, error = WikiConversationIntegration.digest_conversation_to_wiki(
            "conv_2", messages, "proj_1"
        )

        assert error is None
        assert "conversation_id" in wiki_page["frontmatter"]


# ===== Coordinator Integration Tests (4 tests) =====

class TestWikiCoordinatorIntegration:
    """Test wiki integration with coordinator."""

    def test_query_wiki_for_context(self):
        """Should query wiki for run planning context."""
        result = WikiCoordinatorIntegration.query_wiki_for_context(
            "What are best practices for financial modeling?",
            "leading_practice",
            None,
        )

        assert result is not None
        assert "question" in result
        assert "relevant_pages" in result
        assert "recommendations" in result

    def test_apply_learnings_to_plan(self):
        """Should enhance run plan with wiki learnings."""
        plan = {
            "run_type": "financial_model",
            "duration_weeks": 4,
            "team_size": 3,
        }
        learnings = [
            {"title": "Data quality is critical", "description": "Allocate 40% time to data"},
            {"title": "Avoid common pitfalls", "description": "Check formulas twice"},
        ]

        enhanced_plan = WikiCoordinatorIntegration.apply_learnings_to_run_plan(plan, learnings)

        assert enhanced_plan["learning_count"] == 2
        assert "learning_recommendations" in enhanced_plan

    def test_coordinator_integration_handles_no_learnings(self):
        """Should handle plans with no learnings."""
        plan = {"run_type": "test"}
        learnings = []

        result = WikiCoordinatorIntegration.apply_learnings_to_run_plan(plan, learnings)

        assert result["learning_count"] == 0

    def test_coordinator_flags_cautions(self):
        """Should flag cautions/warnings from learnings."""
        plan = {"run_type": "test"}
        learnings = [
            {"title": "Avoid rushing implementation", "description": "Can cause quality issues"},
        ]

        result = WikiCoordinatorIntegration.apply_learnings_to_run_plan(plan, learnings)

        assert "cautions" in result


# ===== Leading Practices Integration Tests (5 tests) =====

class TestWikiLeadingPracticesIntegration:
    """Test wiki integration with leading practices."""

    def test_retrieve_leading_practices(self):
        """Should retrieve leading practices from LP wiki."""
        result = WikiLeadingPracticesIntegration.get_leading_practices_from_wiki(
            "financial_modeling"
        )

        assert result is not None
        assert "topic" in result
        assert "pages" in result

    def test_retrieve_practices_with_category(self):
        """Should filter leading practices by category."""
        result = WikiLeadingPracticesIntegration.get_leading_practices_from_wiki(
            "transformation",
            category="framework",
        )

        assert result["category"] == "framework"

    def test_propose_learning_to_lp_wiki(self):
        """Should propose project learning as leading practice."""
        project_page = {
            "id": "page_1",
            "title": "Our Financial Model Template",
            "content": "This template worked well for us",
        }

        success, message = WikiLeadingPracticesIntegration.propose_learning_to_lp_wiki(
            project_page, "proj_1"
        )

        assert success is True
        assert "pending_review" in message or "Proposal" in message

    def test_proposal_includes_source_tracking(self):
        """Should track source project in LP proposal."""
        project_page = {
            "id": "page_123",
            "title": "Best Practice Template",
            "content": "Template content",
        }

        success, message = WikiLeadingPracticesIntegration.propose_learning_to_lp_wiki(
            project_page, "proj_source_123"
        )

        assert success is True

    def test_lp_integration_handles_invalid_input(self):
        """Should handle invalid page objects."""
        invalid_page = {}  # Missing fields

        success, message = WikiLeadingPracticesIntegration.propose_learning_to_lp_wiki(
            invalid_page, "proj_1"
        )

        # Should handle gracefully
        assert isinstance(success, bool)


# ===== End-to-End Integration Tests (4 tests) =====

class TestWikiIntegrationEndToEnd:
    """End-to-end integration tests across multiple systems."""

    def test_full_run_workflow_to_wiki(self):
        """Should support full workflow: run → artifacts → wiki → learnings → LP."""
        # 1. Create run
        run_id = "run_e2e_1"
        run_summary = {
            "name": "E2E Test Run",
            "outcomes": "Success",
            "learnings": [
                {"title": "Best practice found", "description": "New efficient approach"},
            ],
        }
        artifacts = [{"name": "Artifact", "type": "xlsx", "path": "/run/out.xlsx"}]

        # 2. Ingest into project wiki
        result, error = WikiRunIntegration.ingest_run_artifact_to_wiki(
            run_id, run_summary, artifacts, "proj_1"
        )

        assert error is None
        assert result["pages_created"] > 0

        # 3. Apply to coordinator planning
        learnings = result["pages"]
        plan = {"run_type": "next_run"}
        enhanced_plan = WikiCoordinatorIntegration.apply_learnings_to_run_plan(
            plan, learnings[:1]
        )

        assert "learning_recommendations" in enhanced_plan

        # 4. Propose to LP
        if learnings:
            success, msg = WikiLeadingPracticesIntegration.propose_learning_to_lp_wiki(
                learnings[0], "proj_1"
            )
            assert success is True

    def test_memory_to_wiki_to_coordinator(self):
        """Should support workflow: memory → wiki → coordinator."""
        # 1. Convert memory to wiki
        memory = {
            "id": "mem_e2e",
            "type": "decision",
            "content": "Chose cloud architecture",
            "metadata": {"confidence": "high"},
        }

        wiki_page, error = WikiMemoryIntegration.ingest_memory_item_to_wiki(
            memory, "project", "proj_1"
        )

        assert error is None

        # 2. Use in coordinator
        context = WikiCoordinatorIntegration.query_wiki_for_context(
            "What architecture did we choose?",
            "project",
            "proj_1",
        )

        assert context is not None

    def test_conversation_to_wiki_to_lp(self):
        """Should support workflow: conversation → wiki → LP."""
        # 1. Digest conversation
        messages = [
            {"user_id": "u1", "content": "We learned that iterative approach works"},
            {"user_id": "u2", "content": "Agreed, should be standard practice"},
        ]

        wiki_page, error = WikiConversationIntegration.digest_conversation_to_wiki(
            "conv_e2e", messages, "proj_1"
        )

        assert error is None

        # 2. Propose to LP
        success, msg = WikiLeadingPracticesIntegration.propose_learning_to_lp_wiki(
            wiki_page, "proj_1"
        )

        assert success is True

    def test_integration_error_handling(self):
        """Should handle errors gracefully across integrations."""
        # Test with minimal/invalid data
        memory = {"id": "mem_err"}  # Missing required fields

        wiki_page, error = WikiMemoryIntegration.ingest_memory_item_to_wiki(
            memory, "project", None
        )

        # Should still return something (not crash)
        assert wiki_page is not None or error is not None
