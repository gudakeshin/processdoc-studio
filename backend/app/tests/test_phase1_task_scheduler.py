"""Phase 1 Task Scheduler Integration Tests.

Tests for task board-driven execution, lifecycle validation, and DAG management.
"""

import json
import pytest
from unittest.mock import Mock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.db.models import Base, RunTask
from app.services.run_tasks import validate_task_status_transition, VALID_STATUS_TRANSITIONS
from app.services.swarm import validate_task_dag, validate_task_dag_from_run_tasks


class TestTaskStatusTransitions:
    """Test task lifecycle state machine validation."""

    def test_valid_transition_queued_to_assigned(self):
        """Test queued → assigned transition."""
        is_valid, error = validate_task_status_transition("queued", "assigned")
        assert is_valid
        assert error is None

    def test_valid_transition_assigned_to_in_progress(self):
        """Test assigned → in_progress transition."""
        is_valid, error = validate_task_status_transition("assigned", "in_progress")
        assert is_valid
        assert error is None

    def test_valid_transition_in_progress_to_completed(self):
        """Test in_progress → completed transition."""
        is_valid, error = validate_task_status_transition("in_progress", "completed")
        assert is_valid
        assert error is None

    def test_valid_transition_failed_to_queued_retry(self):
        """Test failed → queued (retry) transition."""
        is_valid, error = validate_task_status_transition("failed", "queued")
        assert is_valid
        assert error is None

    def test_invalid_transition_completed_to_queued(self):
        """Test invalid transition from completed (terminal state)."""
        is_valid, error = validate_task_status_transition("completed", "queued")
        assert not is_valid
        assert error is not None
        assert "Invalid status transition" in error

    def test_invalid_transition_queued_to_in_progress(self):
        """Test invalid skipping of assigned state."""
        is_valid, error = validate_task_status_transition("queued", "in_progress")
        assert not is_valid
        assert error is not None

    def test_idempotent_same_status(self):
        """Test that same status is always valid (idempotent)."""
        for status in ["queued", "assigned", "in_progress", "completed", "failed"]:
            is_valid, error = validate_task_status_transition(status, status)
            assert is_valid, f"Same status {status} should be idempotent"
            assert error is None

    def test_case_insensitive(self):
        """Test that validation is case insensitive."""
        is_valid, error = validate_task_status_transition("QUEUED", "ASSIGNED")
        assert is_valid
        assert error is None

    def test_all_terminal_states(self):
        """Test that terminal states have no outgoing transitions."""
        terminal_states = ["completed", "skipped"]
        for state in terminal_states:
            for new_state in ["queued", "assigned", "in_progress"]:
                is_valid, error = validate_task_status_transition(state, new_state)
                assert not is_valid, f"{state} is terminal, cannot go to {new_state}"


class TestDAGValidation:
    """Test DAG cycle detection and dependency validation."""

    def test_valid_linear_dag(self):
        """Test valid linear dependency chain."""
        task_ids = ["task1", "task2", "task3"]
        depends_map = {
            "task1": [],
            "task2": ["task1"],
            "task3": ["task2"],
        }
        is_valid, error = validate_task_dag(task_ids, depends_map)
        assert is_valid
        assert error is None

    def test_valid_fan_out_dag(self):
        """Test valid fan-out DAG (task1 → task2, task1 → task3)."""
        task_ids = ["task1", "task2", "task3"]
        depends_map = {
            "task1": [],
            "task2": ["task1"],
            "task3": ["task1"],
        }
        is_valid, error = validate_task_dag(task_ids, depends_map)
        assert is_valid
        assert error is None

    def test_valid_complex_dag(self):
        """Test valid complex DAG with multiple dependencies."""
        task_ids = ["a", "b", "c", "d"]
        depends_map = {
            "a": [],
            "b": ["a"],
            "c": ["a"],
            "d": ["b", "c"],
        }
        is_valid, error = validate_task_dag(task_ids, depends_map)
        assert is_valid
        assert error is None

    def test_missing_dependency(self):
        """Test detection of missing dependency."""
        task_ids = ["task1", "task2"]
        depends_map = {
            "task1": [],
            "task2": ["task3"],  # task3 doesn't exist
        }
        is_valid, error = validate_task_dag(task_ids, depends_map)
        assert not is_valid
        assert error is not None
        assert "unknown task" in error.lower()

    def test_simple_cycle(self):
        """Test detection of simple cycle (A → B → A)."""
        task_ids = ["a", "b"]
        depends_map = {
            "a": ["b"],
            "b": ["a"],
        }
        is_valid, error = validate_task_dag(task_ids, depends_map)
        assert not is_valid
        assert error is not None
        assert "cycle" in error.lower()

    def test_self_loop_cycle(self):
        """Test detection of self-loop (A → A)."""
        task_ids = ["a", "b"]
        depends_map = {
            "a": ["a"],  # Self loop
            "b": [],
        }
        is_valid, error = validate_task_dag(task_ids, depends_map)
        assert not is_valid
        assert error is not None
        assert "cycle" in error.lower()

    def test_complex_cycle(self):
        """Test detection of complex cycle (A → B → C → A)."""
        task_ids = ["a", "b", "c"]
        depends_map = {
            "a": ["c"],
            "b": ["a"],
            "c": ["b"],
        }
        is_valid, error = validate_task_dag(task_ids, depends_map)
        assert not is_valid
        assert error is not None
        assert "cycle" in error.lower()

    def test_empty_dag(self):
        """Test empty DAG (no tasks)."""
        is_valid, error = validate_task_dag([], {})
        assert is_valid
        assert error is None


class TestDAGValidationFromRunTasks:
    """Test DAG validation with RunTask objects."""

    def setup_method(self):
        """Set up in-memory SQLite database for testing."""
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        Session_local = sessionmaker(bind=self.engine)
        self.session = Session_local()

    def teardown_method(self):
        """Clean up database."""
        self.session.close()

    def test_valid_dag_from_run_tasks(self):
        """Test DAG validation with RunTask objects."""
        # Create tasks
        task1 = RunTask(
            id="context",
            run_id="run1",
            project_id="proj1",
            title="Context",
            status="completed",
            depends_on_json="[]",
        )
        task2 = RunTask(
            id="plan",
            run_id="run1",
            project_id="proj1",
            title="Plan",
            status="queued",
            depends_on_json='["context"]',
        )
        self.session.add(task1)
        self.session.add(task2)
        self.session.flush()

        # Validate DAG
        is_valid, error = validate_task_dag_from_run_tasks([task1, task2])
        assert is_valid
        assert error is None

    def test_invalid_json_in_depends_on(self):
        """Test error handling for invalid JSON."""
        task = RunTask(
            id="task1",
            run_id="run1",
            project_id="proj1",
            title="Task",
            status="queued",
            depends_on_json='{"invalid": "json"}',  # Not a list
        )
        self.session.add(task)
        self.session.flush()

        is_valid, error = validate_task_dag_from_run_tasks([task])
        assert not is_valid
        assert error is not None
        assert "invalid" in error.lower() or "not a list" in error.lower()

    def test_malformed_json(self):
        """Test error handling for malformed JSON."""
        task = RunTask(
            id="task1",
            run_id="run1",
            project_id="proj1",
            title="Task",
            status="queued",
            depends_on_json="not valid json",
        )
        self.session.add(task)
        self.session.flush()

        is_valid, error = validate_task_dag_from_run_tasks([task])
        assert not is_valid
        assert error is not None


class TestPhase1TaskBoard:
    """Integration tests for Phase 1 task board features."""

    def test_status_transitions_valid_sequence(self):
        """Test a valid task status transition sequence."""
        states = ["queued", "assigned", "in_progress", "completed"]
        for i in range(len(states) - 1):
            is_valid, error = validate_task_status_transition(states[i], states[i + 1])
            assert is_valid, f"Transition {states[i]} → {states[i+1]} should be valid"

    def test_status_transitions_all_defined(self):
        """Test that all status transitions are properly defined."""
        for current_status, next_statuses in VALID_STATUS_TRANSITIONS.items():
            for next_status in next_statuses:
                # Verify reverse mapping exists
                if next_status != current_status:
                    assert next_status in VALID_STATUS_TRANSITIONS, f"Status {next_status} not defined"

    def test_pipeline_dag(self):
        """Test typical document generation pipeline DAG."""
        task_ids = ["context", "process_model", "plan", "out:docx", "qa", "guardrails", "finalize"]
        depends_map = {
            "context": [],
            "process_model": ["context"],
            "plan": ["process_model"],
            "out:docx": ["plan"],
            "qa": ["out:docx"],
            "guardrails": ["qa"],
            "finalize": ["guardrails"],
        }
        is_valid, error = validate_task_dag(task_ids, depends_map)
        assert is_valid, f"Pipeline DAG should be valid: {error}"

    def test_parallel_outputs_dag(self):
        """Test DAG with parallel output generation."""
        task_ids = ["context", "plan", "out:docx", "out:pptx", "qa", "finalize"]
        depends_map = {
            "context": [],
            "plan": ["context"],
            "out:docx": ["plan"],
            "out:pptx": ["plan"],
            "qa": ["out:docx", "out:pptx"],
            "finalize": ["qa"],
        }
        is_valid, error = validate_task_dag(task_ids, depends_map)
        assert is_valid, f"Parallel outputs DAG should be valid: {error}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
