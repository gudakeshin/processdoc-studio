"""Unit tests for CoordinatorStateManager."""

import pytest

from app.agents.coordinator_state_manager import (
    CoordinatorStateError,
    CoordinatorStateManager,
    ExecutionPlanSnapshot,
)


class TestCoordinatorStateManager:
    """Test suite for CoordinatorStateManager."""

    @pytest.fixture
    def state_manager(self):
        """Create a test state manager."""
        return CoordinatorStateManager(
            run_id="test-run-123",
            project_id="test-project",
        )

    def test_initialization(self, state_manager):
        """Test state manager initialization."""
        assert state_manager.run_id == "test-run-123"
        assert state_manager.project_id == "test-project"
        assert state_manager.current_state == "init"
        assert state_manager.replanning_count == 0

    def test_initialize_task_board(self, state_manager):
        """Test task board initialization."""
        state_manager.initialize_task_board(
            output_types=["docx", "pptx"],
            contract_nodes=[],
        )

        # Check milestone tasks exist
        assert "context" in state_manager.task_board
        assert "process_model" in state_manager.task_board
        assert "plan" in state_manager.task_board
        assert "qa" in state_manager.task_board
        assert "guardrails" in state_manager.task_board

        # Check output tasks exist
        assert "out:docx" in state_manager.task_board
        assert "out:pptx" in state_manager.task_board

        # Check dependencies
        assert state_manager.task_board["process_model"]["depends_on"] == ["context"]
        assert state_manager.task_board["plan"]["depends_on"] == ["process_model"]
        assert "plan" in state_manager.task_board["out:docx"]["depends_on"]

    def test_state_transitions_valid(self, state_manager):
        """Test valid state transitions."""
        state_manager.transition_to("planning")
        assert state_manager.current_state == "planning"

        state_manager.transition_to("task_assignment")
        assert state_manager.current_state == "task_assignment"

        state_manager.transition_to("execution")
        assert state_manager.current_state == "execution"

        state_manager.transition_to("finalize")
        assert state_manager.current_state == "finalize"

        state_manager.transition_to("done")
        assert state_manager.current_state == "done"

    def test_state_transitions_invalid(self, state_manager):
        """Test invalid state transitions."""
        with pytest.raises(CoordinatorStateError):
            state_manager.transition_to("finalize")  # Can't jump from init to finalize

        state_manager.transition_to("planning")
        with pytest.raises(CoordinatorStateError):
            state_manager.transition_to("done")  # Can't go from planning to done

    def test_get_ready_task_ids_initial(self, state_manager):
        """Test ready task computation with no dependencies done."""
        state_manager.initialize_task_board(["docx"], [])

        # Initially only context should be ready (no dependencies)
        ready = state_manager.get_ready_task_ids()
        assert "context" in ready
        # But nothing else (they all depend on context or downstream)
        assert "process_model" not in ready
        assert "plan" not in ready

    def test_get_ready_task_ids_sequential(self, state_manager):
        """Test ready task computation as dependencies complete."""
        state_manager.initialize_task_board(["docx"], [])

        # Mark context done
        state_manager.mark_task_done("context")
        ready = state_manager.get_ready_task_ids()
        assert "process_model" in ready

        # Mark process_model done
        state_manager.mark_task_done("process_model")
        ready = state_manager.get_ready_task_ids()
        assert "plan" in ready

        # Mark plan done
        state_manager.mark_task_done("plan")
        ready = state_manager.get_ready_task_ids()
        assert "out:docx" in ready

    def test_assign_task(self, state_manager):
        """Test task assignment."""
        state_manager.initialize_task_board(["docx"], [])

        state_manager.assign_task("context", "teammate-1")

        task = state_manager.task_board["context"]
        assert task["assigned_teammate"] == "teammate-1"
        assert task["status"] == "running"
        assert task["attempts"] == 1

    def test_assign_task_invalid(self, state_manager):
        """Test assignment of non-existent task."""
        with pytest.raises(ValueError, match="Unknown task"):
            state_manager.assign_task("fake-task", "teammate-1")

    def test_mark_task_done(self, state_manager):
        """Test marking task as done."""
        state_manager.initialize_task_board(["docx"], [])
        state_manager.assign_task("context", "teammate-1")
        state_manager.mark_task_done("context")

        task = state_manager.task_board["context"]
        assert task["status"] == "completed"
        assert task["error"] is None

    def test_mark_task_failed(self, state_manager):
        """Test marking task as failed."""
        state_manager.initialize_task_board(["docx"], [])
        state_manager.assign_task("context", "teammate-1")
        state_manager.mark_task_failed("context", error="Test error")

        task = state_manager.task_board["context"]
        assert task["status"] == "failed"
        assert task["error"] == "Test error"

    def test_all_tasks_done_initial(self, state_manager):
        """Test all_tasks_done when tasks are pending."""
        state_manager.initialize_task_board(["docx"], [])
        assert not state_manager.all_tasks_done()

    def test_all_tasks_done_complete(self, state_manager):
        """Test all_tasks_done when all tasks are done."""
        state_manager.initialize_task_board(["docx"], [])

        # Mark all tasks as done
        for task_id in state_manager.task_board:
            state_manager.mark_task_done(task_id)

        assert state_manager.all_tasks_done()

    def test_next_teammate_roundrobin(self, state_manager):
        """Test round-robin teammate assignment."""
        teammates = [state_manager.next_teammate() for _ in range(9)]

        # Should cycle through 3 teammates
        assert teammates == [
            "teammate-1",
            "teammate-2",
            "teammate-3",
            "teammate-1",
            "teammate-2",
            "teammate-3",
            "teammate-1",
            "teammate-2",
            "teammate-3",
        ]

    def test_checkpoint_restore(self, state_manager):
        """Test checkpoint serialization and restore."""
        state_manager.initialize_task_board(["docx", "pptx"], [])
        state_manager.transition_to("planning")
        state_manager.mark_task_done("context")

        # Checkpoint
        checkpoint = state_manager.checkpoint()
        assert checkpoint["version"] == "1.0"
        assert checkpoint["run_id"] == "test-run-123"
        assert checkpoint["current_state"] == "planning"
        assert "context" in checkpoint["task_board"]
        assert checkpoint["task_board"]["context"]["status"] == "completed"

        # Restore
        restored = CoordinatorStateManager.restore(checkpoint)
        assert restored.run_id == "test-run-123"
        assert restored.current_state == "planning"
        assert restored.task_board["context"]["status"] == "completed"

    def test_get_task_summary(self, state_manager):
        """Test task summary for SSE emission."""
        state_manager.initialize_task_board(["docx"], [])

        summary = state_manager.get_task_summary()
        assert "current_state" in summary
        assert "tasks" in summary
        assert "ready_tasks" in summary
        assert "replanning_count" in summary
        assert "timestamp" in summary

    def test_execution_plan_snapshot(self):
        """Test ExecutionPlanSnapshot serialization."""
        plan = ExecutionPlanSnapshot(
            ordered_output_types=["docx", "pptx"],
            rationale="Test rationale",
            per_output_notes={"docx": "Note 1"},
            used_llm_plan=True,
            thinking_excerpt="Thinking...",
        )

        # Serialize
        data = plan.to_dict()
        assert data["ordered_output_types"] == ["docx", "pptx"]
        assert data["rationale"] == "Test rationale"

        # Deserialize
        restored = ExecutionPlanSnapshot.from_dict(data)
        assert restored.ordered_output_types == ["docx", "pptx"]
        assert restored.rationale == "Test rationale"

    def test_replan_state_transition(self, state_manager):
        """Test transition to replan_on_failure and limit."""
        state_manager.initialize_task_board(["docx"], [])
        state_manager.transition_to("planning")  # Start from init -> planning

        for i in range(3):
            state_manager.transition_to("task_assignment")
            state_manager.transition_to("execution")
            state_manager.transition_to("replan_on_failure", task_id="out:docx", error="Test error")
            assert state_manager.replanning_count == i + 1

        # Fourth replan should fail
        state_manager.transition_to("task_assignment")
        state_manager.transition_to("execution")
        with pytest.raises(CoordinatorStateError, match="Max replanning attempts"):
            state_manager.transition_to("replan_on_failure", task_id="out:docx", error="Test error")

    def test_repr(self, state_manager):
        """Test string representation."""
        state_manager.initialize_task_board(["docx"], [])
        repr_str = repr(state_manager)
        assert "CoordinatorStateManager" in repr_str
        assert "init" in repr_str
        assert "tasks=" in repr_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
