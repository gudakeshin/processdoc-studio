"""Coordinator integration with TeammateExecutor for subprocess execution.

Bridges between traditional in-process worker execution and subprocess-based
teammate execution for Phase 2 support.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from app.core.state import ProcessDocState
from app.services.observability import increment
from app.services.teammate_executor import TeammateExecutor, TeammateProcess

_LOG = logging.getLogger(__name__)


class CoordinatorTeammateIntegration:
    """Handles subprocess-based worker execution for coordinator."""

    def __init__(
        self,
        executor: TeammateExecutor,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        """Initialize integration.

        Args:
            executor: TeammateExecutor instance for process management
            emit_event: Optional callback for SSE event emission
        """
        self.executor = executor
        self.emit_event = emit_event
        self.running_tasks: dict[str, TeammateProcess] = {}  # task_id → process

    def execute_worker_subprocess(
        self,
        output_type: str,
        state: ProcessDocState,
        task_id: str | None = None,
        max_retries: int = 1,
    ) -> tuple[dict[str, Any], str | None]:
        """Execute worker via subprocess for given output type.

        Args:
            output_type: Output type (docx, xlsx, pptx, etc.)
            state: ProcessDocState to pass to subprocess
            task_id: Optional task ID for tracking
            max_retries: Number of retries on failure (not implemented in Phase 2)

        Returns:
            Tuple of (output_patch, error_message)
        """
        task_id = task_id or f"out:{output_type}:{int(time.time())}"
        teammate_id = f"worker-{output_type}"

        _LOG.info(f"Spawning teammate subprocess for {output_type} (task={task_id})")

        try:
            # Serialize state to JSON
            state_json = json.dumps(state, default=str)

            # Spawn teammate subprocess
            process = self.executor.spawn_teammate(
                teammate_id=teammate_id,
                task_id=task_id,
                state_json=state_json,
            )

            # Track running task
            self.running_tasks[task_id] = process

            # Emit event
            if self.emit_event:
                self.emit_event(
                    "task.subprocess_spawned",
                    {"task_id": task_id, "output_type": output_type, "pid": process.pid},
                )

            increment("coordinator_subprocess_spawned_total")

            # Wait for process with timeout
            timeout_sec = 300.0  # 5 minutes timeout for worker
            start_time = time.time()

            while time.time() - start_time < timeout_sec:
                is_complete, result = self.executor.poll_teammate(process)

                if is_complete:
                    # Process finished, parse result
                    self.running_tasks.pop(task_id, None)

                    if result and result.get("status") == "success":
                        output = result.get("result", {})
                        if self.emit_event:
                            self.emit_event(
                                "task.subprocess_completed",
                                {"task_id": task_id, "output_type": output_type},
                            )
                        increment("coordinator_subprocess_success_total")
                        return output, None

                    else:
                        error_msg = (
                            result.get("error", "Unknown error")
                            if result
                            else "Process exited without output"
                        )
                        _LOG.error(f"Subprocess {task_id} failed: {error_msg}")
                        if self.emit_event:
                            self.emit_event(
                                "task.subprocess_failed",
                                {"task_id": task_id, "output_type": output_type, "error": error_msg},
                            )
                        increment("coordinator_subprocess_error_total")
                        return {}, error_msg

                # Still running, check timeout
                time.sleep(0.5)

            # Timeout
            _LOG.error(f"Subprocess {task_id} exceeded timeout ({timeout_sec}s)")
            self.executor.terminate_teammate(process, timeout=5.0)
            self.running_tasks.pop(task_id, None)

            if self.emit_event:
                self.emit_event(
                    "task.subprocess_timeout",
                    {"task_id": task_id, "output_type": output_type},
                )

            increment("coordinator_subprocess_timeout_total")
            return {}, f"Process exceeded timeout ({timeout_sec}s)"

        except Exception as e:
            _LOG.error(f"Failed to execute subprocess for {output_type}: {e}")
            if self.emit_event:
                self.emit_event(
                    "task.subprocess_error",
                    {"output_type": output_type, "error": str(e)},
                )
            increment("coordinator_subprocess_exception_total")
            return {}, str(e)

    def terminate_all_subprocesses(self) -> None:
        """Terminate all running subprocesses."""
        _LOG.info(f"Terminating {len(self.running_tasks)} running subprocesses...")
        for task_id, process in list(self.running_tasks.items()):
            self.executor.terminate_teammate(process, timeout=2.0)
            self.running_tasks.pop(task_id, None)

    def get_running_tasks(self) -> dict[str, TeammateProcess]:
        """Get all currently running tasks."""
        return dict(self.running_tasks)

    def get_task_status(self, task_id: str) -> dict[str, Any] | None:
        """Get status of a specific task.

        Returns:
            Dict with alive, runtime_sec, memory_mb, etc. or None if not found
        """
        process = self.running_tasks.get(task_id)
        if process:
            health = self.executor.get_process_health(process)
            return {
                "task_id": task_id,
                "alive": health.alive,
                "runtime_sec": health.runtime_sec,
                "memory_mb": health.memory_mb,
                "exit_code": health.exit_code,
            }
        return None
