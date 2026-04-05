"""Teammate subprocess execution and lifecycle management.

Manages independent Claude Code processes for teammate execution with:
- Process spawning and monitoring
- Health checks and crash detection
- Resource limits and cleanup
- Graceful shutdown handling
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

_LOG = logging.getLogger(__name__)


@dataclass
class ProcessHealth:
    """Health status of a teammate process."""
    alive: bool
    pid: int
    runtime_sec: float
    memory_mb: float
    cpu_percent: float
    exit_code: Optional[int] = None
    error: Optional[str] = None


@dataclass
class TeammateProcess:
    """Represents a running teammate subprocess."""
    pid: int
    teammate_id: str
    task_id: str
    process: subprocess.Popen
    spawn_time: float
    last_heartbeat: float = field(default_factory=time.time)
    exit_code: Optional[int] = None
    output: str = ""
    error: str = ""

    def is_alive(self) -> bool:
        """Check if process is still running."""
        if self.exit_code is not None:
            return False
        poll = self.process.poll()
        if poll is not None:
            self.exit_code = poll
            return False
        return True

    def get_runtime_sec(self) -> float:
        """Get process runtime in seconds."""
        return time.time() - self.spawn_time

    def terminate(self, timeout: float = 5.0) -> bool:
        """Gracefully terminate process with SIGTERM, then SIGKILL."""
        if not self.is_alive():
            return True

        try:
            # Send SIGTERM first
            os.kill(self.pid, signal.SIGTERM)
            start = time.time()

            # Wait for graceful shutdown
            while self.is_alive() and (time.time() - start) < timeout:
                time.sleep(0.1)

            # Force kill if still alive
            if self.is_alive():
                os.kill(self.pid, signal.SIGKILL)
                time.sleep(0.1)

            self.exit_code = self.process.poll()
            return not self.is_alive()
        except (OSError, ProcessLookupError):
            # Process already dead
            self.exit_code = self.process.poll()
            return True


class TeammateExecutor:
    """Manages spawning and monitoring of teammate subprocess execution."""

    def __init__(
        self,
        max_processes: int = 8,
        process_timeout_sec: float = 600.0,
        heartbeat_interval_sec: float = 5.0,
    ):
        """Initialize teammate executor.

        Args:
            max_processes: Maximum concurrent teammate processes
            process_timeout_sec: Max runtime per process before forced termination
            heartbeat_interval_sec: How often to check process health
        """
        self.max_processes = max_processes
        self.process_timeout_sec = process_timeout_sec
        self.heartbeat_interval_sec = heartbeat_interval_sec

        self.processes: dict[int, TeammateProcess] = {}  # pid -> process
        self.processes_by_task: dict[str, TeammateProcess] = {}  # task_id -> process
        self.lock = threading.Lock()

        # Start health monitor thread
        self._monitor_thread = threading.Thread(target=self._monitor_processes, daemon=True)
        self._monitor_thread.start()
        _LOG.info(f"TeammateExecutor started with max_processes={max_processes}")

    def spawn_teammate(
        self,
        teammate_id: str,
        task_id: str,
        state_json: str,
        entrypoint_path: str = "app.agents.teammate_main:main",
    ) -> TeammateProcess:
        """Spawn a new teammate subprocess.

        Args:
            teammate_id: ID of teammate (e.g., "teammate-1")
            task_id: ID of task to execute
            state_json: JSON-serialized ProcessDocState
            entrypoint_path: Module path to entrypoint function

        Returns:
            TeammateProcess instance

        Raises:
            RuntimeError: If max_processes limit reached or spawn fails
        """
        with self.lock:
            if len(self.processes) >= self.max_processes:
                raise RuntimeError(
                    f"Cannot spawn teammate: max_processes ({self.max_processes}) reached"
                )

        try:
            # Spawn subprocess running teammate_main.py
            cmd = [
                "python3.11",
                "-m",
                "app.agents.teammate_main",
                "--teammate-id",
                teammate_id,
                "--task-id",
                task_id,
            ]

            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=os.path.dirname(os.path.dirname(__file__)),
            )

            # Send state via stdin
            proc.stdin.write(state_json)
            proc.stdin.close()

            teammate_proc = TeammateProcess(
                pid=proc.pid,
                teammate_id=teammate_id,
                task_id=task_id,
                process=proc,
                spawn_time=time.time(),
            )

            with self.lock:
                self.processes[proc.pid] = teammate_proc
                self.processes_by_task[task_id] = teammate_proc

            _LOG.info(
                f"Spawned teammate process: {teammate_id} (task={task_id}, pid={proc.pid})"
            )
            return teammate_proc

        except Exception as e:
            _LOG.error(f"Failed to spawn teammate {teammate_id} for task {task_id}: {e}")
            raise

    def poll_teammate(self, teammate_proc: TeammateProcess) -> tuple[bool, Optional[dict[str, Any]]]:
        """Poll a teammate process for completion.

        Args:
            teammate_proc: TeammateProcess to check

        Returns:
            Tuple of (is_complete, result_dict or None)
            - is_complete: True if process finished
            - result_dict: Parsed JSON output if successful, None if failed
        """
        if not teammate_proc.is_alive():
            # Process finished, try to parse output
            try:
                if teammate_proc.output.strip():
                    result = json.loads(teammate_proc.output)
                    _LOG.info(
                        f"Teammate {teammate_proc.teammate_id} (task={teammate_proc.task_id}) "
                        f"completed with status={result.get('status')}"
                    )
                    return True, result
                else:
                    _LOG.warning(
                        f"Teammate {teammate_proc.teammate_id} (task={teammate_proc.task_id}) "
                        f"finished with no output (exit_code={teammate_proc.exit_code})"
                    )
                    return True, None
            except json.JSONDecodeError as e:
                _LOG.error(
                    f"Failed to parse teammate output: {e}\nOutput: {teammate_proc.output}"
                )
                return True, None

        # Still running
        return False, None

    def terminate_teammate(self, teammate_proc: TeammateProcess, timeout: float = 5.0) -> None:
        """Terminate a teammate process.

        Args:
            teammate_proc: TeammateProcess to terminate
            timeout: Graceful shutdown timeout in seconds
        """
        if teammate_proc.terminate(timeout=timeout):
            _LOG.info(f"Terminated teammate {teammate_proc.teammate_id} (pid={teammate_proc.pid})")
        else:
            _LOG.warning(
                f"Failed to terminate teammate {teammate_proc.teammate_id} (pid={teammate_proc.pid})"
            )

        with self.lock:
            self.processes.pop(teammate_proc.pid, None)
            self.processes_by_task.pop(teammate_proc.task_id, None)

    def get_process_health(self, teammate_proc: TeammateProcess) -> ProcessHealth:
        """Get health status of a teammate process.

        Args:
            teammate_proc: TeammateProcess to check

        Returns:
            ProcessHealth instance with current status
        """
        alive = teammate_proc.is_alive()
        runtime_sec = teammate_proc.get_runtime_sec()

        # Try to read memory via /proc (Linux only)
        memory_mb = 0.0
        if alive and os.path.exists(f"/proc/{teammate_proc.pid}/status"):
            try:
                with open(f"/proc/{teammate_proc.pid}/status") as f:
                    for line in f:
                        if line.startswith("VmRSS"):
                            memory_mb = int(line.split()[1]) / 1024  # KB to MB
                            break
            except (IOError, ValueError):
                pass

        error = None
        if not alive and teammate_proc.error:
            error = teammate_proc.error[:200]  # Truncate for logging

        return ProcessHealth(
            alive=alive,
            pid=teammate_proc.pid,
            runtime_sec=runtime_sec,
            memory_mb=memory_mb,
            cpu_percent=0.0,  # TODO: Implement CPU measurement
            exit_code=teammate_proc.exit_code,
            error=error,
        )

    def get_all_processes(self) -> list[TeammateProcess]:
        """Get all active processes."""
        with self.lock:
            return list(self.processes.values())

    def cleanup_all(self, timeout: float = 5.0) -> None:
        """Cleanup all running processes."""
        processes = self.get_all_processes()
        _LOG.info(f"Cleaning up {len(processes)} teammate processes...")

        for proc in processes:
            if proc.is_alive():
                self.terminate_teammate(proc, timeout=timeout)

    def _monitor_processes(self) -> None:
        """Background thread that monitors process health and enforces timeouts."""
        while True:
            try:
                time.sleep(self.heartbeat_interval_sec)

                with self.lock:
                    processes_to_check = list(self.processes.values())

                for proc in processes_to_check:
                    if not proc.is_alive():
                        # Try to collect output
                        try:
                            stdout, stderr = proc.process.communicate(timeout=0.5)
                            proc.output = stdout
                            proc.error = stderr
                        except subprocess.TimeoutExpired:
                            pass

                    # Check timeout
                    runtime_sec = proc.get_runtime_sec()
                    if runtime_sec > self.process_timeout_sec:
                        _LOG.warning(
                            f"Teammate {proc.teammate_id} (task={proc.task_id}) "
                            f"exceeded timeout ({runtime_sec}s > {self.process_timeout_sec}s), terminating"
                        )
                        self.terminate_teammate(proc, timeout=2.0)

            except Exception as e:
                _LOG.error(f"Error in process monitor thread: {e}")

    def __del__(self) -> None:
        """Cleanup on deletion."""
        try:
            self.cleanup_all(timeout=2.0)
        except Exception:
            pass
