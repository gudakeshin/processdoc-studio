"""Phase 2 Integration Tests: Coordinator + TeammateExecutor.

Tests for subprocess-based worker execution integrated into coordinator.
"""

import json
from unittest.mock import MagicMock, Mock, patch

import pytest

from app.agents.coordinator_teammate_integration import CoordinatorTeammateIntegration
from app.services.teammate_executor import TeammateExecutor


class TestCoordinatorTeammateIntegration:
    """Test coordinator integration with TeammateExecutor."""

    def test_integration_initialization(self):
        """Test integration initialization."""
        executor = TeammateExecutor(max_processes=4)
        integration = CoordinatorTeammateIntegration(executor)

        assert integration.executor is executor
        assert integration.emit_event is None
        assert len(integration.running_tasks) == 0

    def test_integration_with_emit_event(self):
        """Test integration with event emission."""
        executor = TeammateExecutor()
        emit_event = Mock()

        integration = CoordinatorTeammateIntegration(executor, emit_event=emit_event)
        assert integration.emit_event is emit_event

    def test_execute_worker_subprocess_success(self):
        """Test successful subprocess worker execution."""
        executor = TeammateExecutor()
        integration = CoordinatorTeammateIntegration(executor)
        emit_event = Mock()
        integration.emit_event = emit_event

        # Mock the spawning and result
        mock_process = MagicMock()
        mock_process.pid = 111
        mock_process.task_id = "out:docx:123"

        # Simulate successful result
        result_data = {"status": "success", "result": {"docx_markdown": "# Heading\n\nContent"}}

        with patch.object(executor, "spawn_teammate", return_value=mock_process):
            with patch.object(executor, "poll_teammate") as mock_poll:
                # First call: process running, second call: process complete
                mock_poll.side_effect = [
                    (False, None),  # Running
                    (True, result_data),  # Complete
                ]

                state = {"context": "test"}
                output, error = integration.execute_worker_subprocess(
                    output_type="docx", state=state, task_id="out:docx:123"
                )

                assert error is None
                assert output == {"docx_markdown": "# Heading\n\nContent"}
                assert emit_event.called  # Should emit events

    def test_execute_worker_subprocess_failure(self):
        """Test subprocess worker execution failure."""
        executor = TeammateExecutor()
        integration = CoordinatorTeammateIntegration(executor)
        emit_event = Mock()
        integration.emit_event = emit_event

        mock_process = MagicMock()
        mock_process.pid = 111

        error_data = {"status": "error", "error": "Worker failed", "result": None}

        with patch.object(executor, "spawn_teammate", return_value=mock_process):
            with patch.object(executor, "poll_teammate") as mock_poll:
                mock_poll.return_value = (True, error_data)

                state = {"context": "test"}
                output, error = integration.execute_worker_subprocess(
                    output_type="docx", state=state
                )

                assert error == "Worker failed"
                assert output == {}
                assert emit_event.called

    def test_execute_worker_subprocess_timeout(self):
        """Test subprocess worker execution timeout."""
        executor = TeammateExecutor()
        integration = CoordinatorTeammateIntegration(executor)

        mock_process = MagicMock()
        mock_process.pid = 111

        with patch.object(executor, "spawn_teammate", return_value=mock_process):
            with patch.object(executor, "poll_teammate") as mock_poll:
                # Always return running (never completes)
                mock_poll.return_value = (False, None)

                # Use a counter to simulate time passing
                time_counter = [0]
                def mock_time_func():
                    time_counter[0] += 1
                    return float(time_counter[0] * 100)  # Advance time by 100 each call

                with patch("time.time", side_effect=mock_time_func):
                    with patch("time.sleep"):  # Speed up test
                        with patch.object(executor, "terminate_teammate"):
                            state = {"context": "test"}
                            output, error = integration.execute_worker_subprocess(
                                output_type="docx", state=state
                            )

                            assert "timeout" in error.lower()
                            assert output == {}

    def test_execute_worker_subprocess_spawn_failure(self):
        """Test handling of spawn failure."""
        executor = TeammateExecutor()
        integration = CoordinatorTeammateIntegration(executor)

        with patch.object(executor, "spawn_teammate", side_effect=RuntimeError("Spawn failed")):
            state = {"context": "test"}
            output, error = integration.execute_worker_subprocess(
                output_type="docx", state=state
            )

            assert "Spawn failed" in error
            assert output == {}

    def test_running_tasks_tracking(self):
        """Test tracking of running tasks."""
        executor = TeammateExecutor()
        integration = CoordinatorTeammateIntegration(executor)

        mock_process = MagicMock()
        mock_process.pid = 111

        with patch.object(executor, "spawn_teammate", return_value=mock_process):
            with patch.object(executor, "poll_teammate") as mock_poll:
                # Simulate long-running process that eventually completes
                mock_poll.side_effect = [
                    (False, None),  # Still running
                    (True, {"status": "success", "result": {}}),  # Complete
                ]

                state = {"context": "test"}
                integration.execute_worker_subprocess(
                    output_type="docx", state=state, task_id="task-1"
                )

                # Task should be removed after completion
                assert "task-1" not in integration.running_tasks

    def test_get_task_status(self):
        """Test getting task status."""
        executor = TeammateExecutor()
        integration = CoordinatorTeammateIntegration(executor)

        mock_process = MagicMock()
        mock_process.pid = 111

        # Manually add to running tasks
        integration.running_tasks["task-1"] = mock_process

        with patch.object(executor, "get_process_health") as mock_health:
            mock_health.return_value = MagicMock(
                alive=True,
                runtime_sec=10.5,
                memory_mb=256,
                exit_code=None,
            )

            status = integration.get_task_status("task-1")
            assert status is not None
            assert status["alive"]
            assert status["runtime_sec"] == 10.5
            assert status["memory_mb"] == 256

            # Non-existent task
            status = integration.get_task_status("task-999")
            assert status is None

    def test_terminate_all_subprocesses(self):
        """Test terminating all running subprocesses."""
        executor = TeammateExecutor()
        integration = CoordinatorTeammateIntegration(executor)

        # Add some mock processes
        for i in range(3):
            proc = MagicMock()
            proc.pid = 100 + i
            integration.running_tasks[f"task-{i}"] = proc

        with patch.object(executor, "terminate_teammate") as mock_term:
            integration.terminate_all_subprocesses()

            # Should call terminate for each process
            assert mock_term.call_count == 3
            assert len(integration.running_tasks) == 0

    def test_state_serialization(self):
        """Test that state is properly serialized for subprocess."""
        executor = TeammateExecutor()
        integration = CoordinatorTeammateIntegration(executor)

        with patch.object(executor, "spawn_teammate") as mock_spawn:
            mock_spawn.return_value = MagicMock(pid=111)

            with patch.object(executor, "poll_teammate") as mock_poll:
                mock_poll.return_value = (True, {"status": "success", "result": {}})

                # State with various types
                state = {
                    "string": "value",
                    "number": 42,
                    "float": 3.14,
                    "list": [1, 2, 3],
                    "dict": {"nested": "value"},
                    "none": None,
                }

                integration.execute_worker_subprocess("docx", state)

                # Verify spawn was called with JSON-serialized state
                call_args = mock_spawn.call_args
                state_json = call_args[1]["state_json"]

                # Should be valid JSON
                parsed = json.loads(state_json)
                assert parsed["string"] == "value"
                assert parsed["number"] == 42


class TestIntegrationEventEmission:
    """Test event emission during integration."""

    def test_emit_subprocess_spawned(self):
        """Test emitting subprocess spawned event."""
        executor = TeammateExecutor()
        emit_event = Mock()
        integration = CoordinatorTeammateIntegration(executor, emit_event=emit_event)

        mock_process = MagicMock()
        mock_process.pid = 111

        with patch.object(executor, "spawn_teammate", return_value=mock_process):
            with patch.object(executor, "poll_teammate") as mock_poll:
                mock_poll.return_value = (True, {"status": "success", "result": {}})

                integration.execute_worker_subprocess("docx", {})

                # Check that spawned event was emitted
                calls = emit_event.call_args_list
                spawn_calls = [c for c in calls if "spawned" in c[0][0]]
                assert len(spawn_calls) > 0

    def test_emit_subprocess_completed(self):
        """Test emitting subprocess completed event."""
        executor = TeammateExecutor()
        emit_event = Mock()
        integration = CoordinatorTeammateIntegration(executor, emit_event=emit_event)

        mock_process = MagicMock()
        mock_process.pid = 111

        with patch.object(executor, "spawn_teammate", return_value=mock_process):
            with patch.object(executor, "poll_teammate") as mock_poll:
                mock_poll.return_value = (True, {"status": "success", "result": {}})

                integration.execute_worker_subprocess("docx", {})

                # Check that completed event was emitted
                calls = emit_event.call_args_list
                completed_calls = [c for c in calls if "completed" in c[0][0]]
                assert len(completed_calls) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
