"""End-to-end integration tests for Coordinator event loop with mock data."""

import json
import pytest
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from typing import Any

from app.agents.coordinator import Coordinator, ExecutionPlan
from app.agents.coordinator_state_manager import CoordinatorStateManager, ExecutionPlanSnapshot
from app.core.state import ProcessDocState


class MockContextEngine:
    """Mock context assembly engine."""

    def assemble(self, project_id, redacted, lp_snippets=None):
        """Mock context assembly."""
        class Context:
            def __init__(self):
                self.text = f"Context for project {project_id}: {redacted[:100]}..."
                self.metadata = {"context_type": "v1"}
        return Context()

    def planner_excerpt(self, project_id, query, char_cap=800):
        """Mock planner excerpt."""
        return "Relevant context excerpt for planning..."


class MockDPDP:
    """Mock DPDP redaction service."""

    def redact(self, text):
        """Mock DPDP redaction."""
        return text, {"redacted_items": 0}


class MockQALoop:
    """Mock QA evaluation."""

    def run(self, outputs, threshold=0.8, project_id=None, max_loops=2):
        """Mock QA evaluation."""
        return {
            "passed": True,
            "scores": {
                "docx": {"readability": 0.95, "completeness": 0.90},
                "pptx": {"clarity": 0.92, "flow": 0.88},
            },
            "remediation_instructions": {},
        }


class MockGuardrails:
    """Mock guardrails evaluation."""

    def evaluate(self, outputs, dpdp_gate7=True):
        """Mock guardrails check."""
        return {
            "passed": True,
            "issues": [],
            "dpdp_gate7_result": "pass",
        }


@pytest.fixture
def mock_coordinator():
    """Create a coordinator with mocked dependencies."""
    coordinator = Coordinator()

    # Mock all the heavy dependencies
    coordinator.context_engine = MockContextEngine()
    coordinator.dpdp = MockDPDP()
    coordinator.qa_loop = MockQALoop()
    coordinator.guardrails = MockGuardrails()

    # Mock skill registry
    coordinator.skill_registry = [
        {
            "id": "docx_v1",
            "output_types": ["docx"],
            "prompt_instructions": "Generate a professional DOCX document",
            "role": "primary",
        },
        {
            "id": "pptx_v1",
            "output_types": ["pptx"],
            "prompt_instructions": "Generate a professional PPTX presentation",
            "role": "primary",
        },
    ]

    # Mock output requirements
    coordinator.output_requirements = {
        "docx": ["docx_v1"],
        "pptx": ["pptx_v1"],
    }

    return coordinator


@pytest.fixture
def mock_state() -> ProcessDocState:
    """Create a comprehensive mock state."""
    return {
        "run_id": "test-run-e2e-001",
        "project_id": "test-project",
        "user_id": "test-user",
        "requested_outputs": ["docx"],
        "raw_text": "This is test input content for document generation. " * 10,
        "user_instruction": "Generate a professional document based on this content.",
        "dpdp_flags": {"enabled": False},
    }


@pytest.fixture
def events_emitted():
    """Collect emitted events."""
    return []


class TestCoordinatorE2EIntegration:
    """End-to-end integration tests."""

    def emit_event(self, events_list):
        """Create event emitter."""
        def _emit(event_type: str, payload: dict[str, Any]) -> None:
            events_list.append({
                "event_type": event_type,
                "payload": payload,
                "timestamp": len(events_list),
            })
            print(f"[Event {len(events_list)}] {event_type}")
        return _emit

    @patch('app.agents.coordinator.SessionLocal')
    @patch('app.agents.coordinator.settings')
    def test_full_event_loop_single_output(
        self,
        mock_settings,
        mock_session,
        mock_coordinator,
        mock_state,
        events_emitted,
    ):
        """Test complete event loop for single output (docx)."""
        # Setup mocks
        mock_settings.coordinator_llm_planning_enabled = False
        mock_settings.memory_compaction_v1_enabled = False
        mock_settings.memory_v2_retrieval_enabled = False
        mock_settings.coordinator_planning_context_chars = 800
        mock_settings.processdoc_coordinator_debug_log = ""
        mock_settings.scratchpad_visibility_enabled = False

        mock_session_inst = MagicMock()
        mock_session.return_value = mock_session_inst
        mock_session_inst.scalars.return_value.all.return_value = []
        mock_session_inst.scalar.return_value = None

        emit_fn = self.emit_event(events_emitted)

        # Mock process extraction and hooks
        with patch('app.agents.coordinator.run_process_extraction') as mock_pe:
            mock_pe.return_value = mock_state
            with patch('app.agents.coordinator.run_hooks_sync', return_value=[]):
                with patch.object(mock_coordinator, '_parallel_read_stages', return_value={}):
                    with patch.object(mock_coordinator, '_plan_with_reasoning') as mock_plan:
                        mock_plan.return_value = (
                            ["docx"],
                            ExecutionPlan(
                                ordered_output_types=["docx"],
                                rationale="Single document requested",
                                used_llm_plan=False,
                            ),
                        )
                        with patch.object(mock_coordinator, '_load_project_custom_skills', return_value=[]):
                            with patch.object(mock_coordinator, '_outputs_from_state', return_value={"docx": "Mock DOCX content"}):
                                with patch.object(mock_coordinator, '_apply_worker_patch'):
                                    with patch.object(mock_coordinator, '_execute_worker_with_retry', return_value=({}, None)):
                                        with patch.object(mock_coordinator, '_apply_qa_remediation', return_value={"docx": "Mock DOCX content"}):

                                            # Run the event loop
                                            result = mock_coordinator._run_event_loop(
                                                mock_state,
                                                emit_event=emit_fn,
                                            )

                                            # Verify event loop completed
                                            assert result is not None
                                            print(f"\n✅ Event loop completed successfully")
                                            print(f"📊 Total events emitted: {len(events_emitted)}")

                                            # Verify events were emitted
                                            event_types = [e["event_type"] for e in events_emitted]
                                            print(f"📝 Event types: {set(event_types)}")

                                            # Should have state events
                                            assert any("state" in et for et in event_types), "No state events emitted"
                                            print("✅ State events emitted")

    @patch('app.agents.coordinator.SessionLocal')
    @patch('app.agents.coordinator.settings')
    def test_event_loop_with_multiple_outputs(
        self,
        mock_settings,
        mock_session,
        mock_coordinator,
        mock_state,
        events_emitted,
    ):
        """Test event loop with multiple outputs (docx + pptx)."""
        mock_state["requested_outputs"] = ["docx", "pptx"]

        mock_settings.coordinator_llm_planning_enabled = False
        mock_settings.memory_compaction_v1_enabled = False
        mock_settings.memory_v2_retrieval_enabled = False
        mock_settings.coordinator_planning_context_chars = 800
        mock_settings.processdoc_coordinator_debug_log = ""
        mock_settings.scratchpad_visibility_enabled = False

        mock_session_inst = MagicMock()
        mock_session.return_value = mock_session_inst
        mock_session_inst.scalars.return_value.all.return_value = []
        mock_session_inst.scalar.return_value = None

        emit_fn = self.emit_event(events_emitted)

        with patch('app.agents.coordinator.run_process_extraction') as mock_pe:
            mock_pe.return_value = mock_state
            with patch('app.agents.coordinator.run_hooks_sync', return_value=[]):
                with patch.object(mock_coordinator, '_parallel_read_stages', return_value={}):
                    with patch.object(mock_coordinator, '_plan_with_reasoning') as mock_plan:
                        mock_plan.return_value = (
                            ["docx", "pptx"],
                            ExecutionPlan(
                                ordered_output_types=["docx", "pptx"],
                                rationale="Multiple outputs requested",
                                used_llm_plan=False,
                            ),
                        )
                        with patch.object(mock_coordinator, '_load_project_custom_skills', return_value=[]):
                            with patch.object(mock_coordinator, '_outputs_from_state', return_value={"docx": "Mock", "pptx": "Mock"}):
                                with patch.object(mock_coordinator, '_apply_worker_patch'):
                                    with patch.object(mock_coordinator, '_execute_worker_with_retry', return_value=({}, None)):
                                        with patch.object(mock_coordinator, '_apply_qa_remediation', return_value={"docx": "Mock", "pptx": "Mock"}):

                                            result = mock_coordinator._run_event_loop(
                                                mock_state,
                                                emit_event=emit_fn,
                                            )

                                            assert result is not None
                                            print(f"\n✅ Multi-output event loop completed")
                                            print(f"📊 Total events: {len(events_emitted)}")

    def test_state_manager_task_board_workflow(self):
        """Test task board workflow through complete execution."""
        sm = CoordinatorStateManager(
            run_id="test-e2e-taskboard",
            project_id="test-project",
        )

        # Initialize with multiple outputs
        sm.initialize_task_board(["docx", "pptx", "sop"], [])
        print(f"\n✅ Task board initialized with {len(sm.task_board)} tasks")

        # Simulate full workflow
        workflow_log = []

        # Phase: Setup
        sm.transition_to("planning")
        workflow_log.append(f"State: {sm.current_state}, Ready: {sm.get_ready_task_ids()}")

        # Mark setup tasks done
        for task_id in ["context", "process_model", "plan"]:
            sm.mark_task_done(task_id)

        sm.transition_to("task_assignment")
        ready = sm.get_ready_task_ids()
        assert "out:docx" in ready
        print(f"✅ Setup complete, ready tasks: {ready}")

        # Phase: Task assignment and execution
        for task_id in ready:
            sm.assign_task(task_id, "teammate-1")
            sm.mark_task_done(task_id)

        workflow_log.append(f"State: {sm.current_state}, Completed output tasks")

        # All output tasks done, move to finalization
        sm.transition_to("execution")
        sm.transition_to("finalize")

        # Mark finalization tasks as done
        for task_id in ["qa", "guardrails", "finalize"]:
            if task_id in sm.task_board:
                sm.mark_task_done(task_id)

        print(f"✅ Ready to finalize, all tasks done: {sm.all_tasks_done()}")

        # Final state
        sm.transition_to("done")
        assert sm.current_state == "done"
        assert sm.all_tasks_done()

        print(f"✅ Complete workflow executed successfully")
        print(f"📊 State transitions: {len(workflow_log) + 3}")

    def test_checkpoint_restore_workflow(self):
        """Test pause/resume via checkpoint."""
        sm1 = CoordinatorStateManager(
            run_id="test-checkpoint",
            project_id="test-project",
        )

        sm1.initialize_task_board(["docx"], [])
        sm1.transition_to("planning")
        sm1.mark_task_done("context")
        sm1.mark_task_done("process_model")

        # Checkpoint mid-execution
        checkpoint = sm1.checkpoint()
        print(f"\n✅ Checkpoint created at state: {sm1.current_state}")

        # Restore to new instance
        sm2 = CoordinatorStateManager.restore(checkpoint)
        assert sm2.current_state == sm1.current_state
        assert sm2.task_board["context"]["status"] == "completed"
        assert sm2.task_board["process_model"]["status"] == "completed"

        # Continue from checkpoint
        sm2.transition_to("task_assignment")
        ready = sm2.get_ready_task_ids()
        assert "plan" in ready

        print(f"✅ Restored successfully, continuing from state: {sm2.current_state}")
        print(f"✅ Task board state preserved correctly")

    def test_failure_and_recovery_workflow(self):
        """Test failure detection and replanning."""
        sm = CoordinatorStateManager(
            run_id="test-failure-recovery",
            project_id="test-project",
            max_replans=3,
        )

        sm.initialize_task_board(["docx"], [])

        # Simulate setup success
        sm.transition_to("planning")
        for task_id in ["context", "process_model", "plan"]:
            sm.mark_task_done(task_id)

        # First attempt: task fails
        sm.transition_to("task_assignment")
        ready = sm.get_ready_task_ids()
        assert "out:docx" in ready

        sm.assign_task("out:docx", "teammate-1")
        sm.mark_task_failed("out:docx", error="Worker timeout")
        print(f"\n✅ Task failed: {sm.task_board['out:docx']['error']}")

        # Trigger replanning
        sm.transition_to("execution")
        sm.transition_to("replan_on_failure", task_id="out:docx", error="Worker timeout")
        print(f"✅ Replanning triggered, attempt: {sm.replanning_count}")

        # Replan: reset task
        assert sm.failure_context["task_id"] == "out:docx"
        sm.task_board["out:docx"]["status"] = "queued"

        # Second attempt: success
        sm.transition_to("task_assignment")
        ready = sm.get_ready_task_ids()
        assert "out:docx" in ready

        sm.assign_task("out:docx", "teammate-2")
        sm.mark_task_done("out:docx")
        print(f"✅ Task succeeded on retry")

        # Continue to finalization
        sm.transition_to("execution")
        sm.transition_to("finalize")

        # Mark remaining finalization tasks as done
        for task_id in ["qa", "guardrails"]:
            sm.mark_task_done(task_id)

        sm.transition_to("done")

        print(f"✅ Recovery workflow complete with {sm.replanning_count} replan attempt")

    def test_ready_task_dependency_ordering(self):
        """Test that ready tasks respect dependency ordering."""
        sm = CoordinatorStateManager(
            run_id="test-dependencies",
            project_id="test-project",
        )

        sm.initialize_task_board(["docx", "pptx", "sop"], [])

        # Verify initial state
        ready = sm.get_ready_task_ids()
        assert ready == ["context"], f"Expected only context ready, got: {ready}"
        print(f"\n✅ Initial: Only context is ready")

        # Mark context done
        sm.mark_task_done("context")
        ready = sm.get_ready_task_ids()
        assert ready == ["process_model"], f"Expected only process_model, got: {ready}"
        print(f"✅ After context: Only process_model is ready")

        # Mark process_model done
        sm.mark_task_done("process_model")
        ready = sm.get_ready_task_ids()
        assert ready == ["plan"], f"Expected only plan, got: {ready}"
        print(f"✅ After process_model: Only plan is ready")

        # Mark plan done
        sm.mark_task_done("plan")
        ready = sm.get_ready_task_ids()
        # All output tasks should be ready
        expected = {"out:docx", "out:pptx", "out:sop"}
        assert set(ready) == expected, f"Expected {expected}, got: {set(ready)}"
        print(f"✅ After plan: All output tasks ready: {ready}")

        # Mark outputs done
        for out_id in ready:
            sm.mark_task_done(out_id)

        ready = sm.get_ready_task_ids()
        assert ready == ["qa"], f"Expected only qa, got: {ready}"
        print(f"✅ After outputs: Only QA is ready")

        # Mark qa done
        sm.mark_task_done("qa")
        ready = sm.get_ready_task_ids()
        assert ready == ["guardrails"], f"Expected only guardrails, got: {ready}"
        print(f"✅ After QA: Only guardrails is ready")

        # Mark guardrails done
        sm.mark_task_done("guardrails")
        ready = sm.get_ready_task_ids()
        assert ready == ["finalize"], f"Expected only finalize, got: {ready}"
        print(f"✅ After guardrails: Only finalize is ready")

        # Mark finalize done
        sm.mark_task_done("finalize")
        ready = sm.get_ready_task_ids()
        assert ready == [], f"Expected no ready tasks, got: {ready}"
        assert sm.all_tasks_done(), "All tasks should be done"
        print(f"✅ All tasks complete: workflow verified")


class TestCoordinatorMockWorkers:
    """Test coordinator with mocked worker execution."""

    @pytest.fixture
    def mock_coordinator(self):
        """Create coordinator with mocked workers."""
        coordinator = Coordinator()
        coordinator.context_engine = MockContextEngine()
        coordinator.dpdp = MockDPDP()
        coordinator.qa_loop = MockQALoop()
        coordinator.guardrails = MockGuardrails()
        coordinator.skill_registry = []
        coordinator.output_requirements = {}
        return coordinator

    def test_execute_single_task_mock(self, mock_coordinator):
        """Test single task execution with mocks."""
        mock_state = {
            "run_id": "test-worker",
            "docx": {"content": "test"},
        }

        # Test output task (should dispatch to worker)
        with patch.object(mock_coordinator, '_execute_worker_with_retry', return_value=({}, None)):
            update, err = mock_coordinator._execute_single_task(
                "out:docx",
                mock_state,
                output_type="docx",
            )

            assert err is None
            print(f"✅ Task execution succeeded")

        # Test non-output task (should skip)
        update, err = mock_coordinator._execute_single_task(
            "context",
            mock_state,
            output_type=None,
        )

        assert err is None
        assert update == {}
        print(f"✅ Non-output task skipped correctly")

    def test_poll_and_execute_tasks_mock(self, mock_coordinator):
        """Test task polling and execution."""
        mock_state = {"run_id": "test-poll"}

        sm = CoordinatorStateManager(
            run_id="test-poll",
            project_id="test-project",
        )

        sm.initialize_task_board(["docx"], [])
        sm.transition_to("planning")
        sm.mark_task_done("context")
        sm.mark_task_done("process_model")
        sm.mark_task_done("plan")

        # Assign and execute output task
        sm.assign_task("out:docx", "teammate-1")

        with patch.object(mock_coordinator, '_execute_worker_with_retry', return_value=({}, None)):
            updates, failed = mock_coordinator._poll_and_execute_tasks(
                mock_state,
                sm,
            )

            assert len(failed) == 0
            assert sm.task_board["out:docx"]["status"] == "completed"
            print(f"✅ Task polling and execution successful")

    def test_lead_replan_mock(self, mock_coordinator, events_emitted):
        """Test lead replanning logic."""
        mock_state = {"run_id": "test-replan"}

        sm = CoordinatorStateManager(
            run_id="test-replan",
            project_id="test-project",
        )

        sm.initialize_task_board(["docx"], [])
        sm.assign_task("out:docx", "teammate-1")
        sm.mark_task_failed("out:docx", error="Worker timeout")

        events = []
        emit_fn = lambda et, pl: events.append((et, pl))

        mock_coordinator._lead_replan(
            mock_state,
            sm,
            failed_task_id="out:docx",
            error="Worker timeout",
            emit_event=emit_fn,
        )

        # Task should be reset for retry
        assert sm.task_board["out:docx"]["status"] == "queued"
        assert len(events) > 0
        print(f"✅ Replanning executed, task reset for retry")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
