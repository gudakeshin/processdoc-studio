"""Coordinator state machine and task board management for agentic loop."""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.state import ProcessDocState
from app.db.models import RunTask, SwarmTeam, SwarmTeammate
from app.db.session import SessionLocal
from app.services.observability import increment
from app.services.swarm import ready_task_ids as compute_ready_task_ids

_LOG = logging.getLogger(__name__)


class CoordinatorStateError(Exception):
    """Raised when state transition is invalid."""

    pass


@dataclass
class ExecutionPlanSnapshot:
    """Snapshot of execution plan for serialization."""

    ordered_output_types: list[str]
    rationale: str
    per_output_notes: dict[str, str] = field(default_factory=dict)
    used_llm_plan: bool = False
    fallback_reason: Optional[str] = None
    thinking_excerpt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionPlanSnapshot":
        return cls(
            ordered_output_types=data.get("ordered_output_types", []),
            rationale=data.get("rationale", ""),
            per_output_notes=data.get("per_output_notes", {}),
            used_llm_plan=data.get("used_llm_plan", False),
            fallback_reason=data.get("fallback_reason"),
            thinking_excerpt=data.get("thinking_excerpt", ""),
        )


@dataclass
class CoordinatorStateManager:
    """
    Manages coordinator loop state, task board, and checkpoint/restore.

    State machine:
      init → planning → task_assignment → execution → replan_on_failure → (back to task_assignment)
                                                    → finalize (when all tasks done)
                                                    → done
    """

    run_id: str
    project_id: str
    current_state: str = "init"
    requested_outputs: list[str] = field(default_factory=list)
    execution_plan: Optional[ExecutionPlanSnapshot] = None
    task_board: dict[str, dict[str, Any]] = field(default_factory=dict)  # task_id -> {status, assigned_teammate, ...}
    task_assignments: dict[str, str] = field(default_factory=dict)  # task_id -> teammate_id
    teammate_rotation: int = 0  # For round-robin assignment
    failure_context: dict[str, Any] = field(default_factory=dict)  # {task_id, error, timestamp}
    replanning_count: int = 0
    max_replans: int = 3
    checkpoint_timestamp: Optional[datetime] = None

    # Track which tasks have been seen in this loop
    _seen_task_ids: set[str] = field(default_factory=set, init=False)
    _db_session: Optional[Session] = field(default=None, init=False)

    def __post_init__(self) -> None:
        """Initialize database session."""
        self._db_session = SessionLocal()

    def __del__(self) -> None:
        """Clean up database session."""
        if self._db_session:
            try:
                self._db_session.close()
            except Exception as e:
                _LOG.debug(f"Error closing session in CoordinatorStateManager: {e}")

    # ============================================================================
    # State Management
    # ============================================================================

    def transition_to(self, new_state: str, **context) -> None:
        """
        Move to next state with validation.

        Valid transitions:
          init -> planning
          planning -> task_assignment
          task_assignment -> execution
          execution -> task_assignment (if more tasks)
          execution -> finalize (if all tasks done)
          execution -> replan_on_failure (if task fails)
          replan_on_failure -> task_assignment
          finalize -> done
        """
        allowed = {
            "init": ["planning"],
            "planning": ["task_assignment"],
            "task_assignment": ["execution", "finalize"],
            "execution": ["task_assignment", "finalize", "replan_on_failure"],
            "replan_on_failure": ["task_assignment"],
            "finalize": ["done"],
            "done": [],
        }

        if new_state not in allowed.get(self.current_state, []):
            raise CoordinatorStateError(
                f"Invalid transition: {self.current_state} -> {new_state}. "
                f"Allowed: {allowed.get(self.current_state, [])}"
            )

        old_state = self.current_state
        self.current_state = new_state

        if new_state == "replan_on_failure":
            self.replanning_count += 1
            if self.replanning_count > self.max_replans:
                raise CoordinatorStateError(f"Max replanning attempts ({self.max_replans}) exceeded")
            _LOG.info(f"Coordinator transitioning to replan_on_failure (attempt {self.replanning_count})")
            self.failure_context = context

        _LOG.debug(f"Coordinator state: {old_state} -> {new_state}")
        increment("coordinator_state_transition_total")

    # ============================================================================
    # Task Board Management
    # ============================================================================

    def initialize_task_board(self, output_types: list[str], contract_nodes: list[dict]) -> None:
        """
        Initialize task board from output types and optional run_contract.

        Creates fixed pipeline tasks:
          context -> process_model -> plan -> out:{type} -> qa -> guardrails -> finalize
        """
        self.requested_outputs = output_types
        self.task_board = {}

        # Fixed milestone tasks
        milestones = [
            {"id": "context", "label": "Context Assembly", "phase": "setup"},
            {"id": "process_model", "label": "Process Extraction", "phase": "setup"},
            {"id": "plan", "label": "Execution Planning", "phase": "setup"},
        ]

        # Output tasks
        for out_type in output_types:
            milestones.append(
                {
                    "id": f"out:{out_type}",
                    "label": f"Generate {out_type.upper()}",
                    "phase": "generation",
                    "output_type": out_type,
                }
            )

        # Post-generation tasks
        milestones.extend(
            [
                {"id": "qa", "label": "Quality Assurance", "phase": "finalization"},
                {"id": "guardrails", "label": "Guardrails Check", "phase": "finalization"},
                {"id": "finalize", "label": "Finalize", "phase": "finalization"},
            ]
        )

        # Build dependency map
        depends_map = {
            "context": [],
            "process_model": ["context"],
            "plan": ["process_model"],
        }
        output_ids = [f"out:{ot}" for ot in output_types]
        for out_id in output_ids:
            depends_map[out_id] = ["plan"]
        depends_map["qa"] = output_ids if output_ids else ["plan"]
        depends_map["guardrails"] = ["qa"]
        depends_map["finalize"] = ["guardrails"]

        # Create task board entries
        for milestone in milestones:
            task_id = milestone["id"]
            self.task_board[task_id] = {
                "id": task_id,
                "label": milestone.get("label", task_id),
                "status": "queued",  # queued, running, completed, failed, skipped
                "assigned_teammate": None,
                "depends_on": depends_map.get(task_id, []),
                "phase": milestone.get("phase", "unknown"),
                "output_type": milestone.get("output_type"),
                "created_at": datetime.utcnow().isoformat(),
                "attempts": 0,
                "error": None,
            }

        _LOG.info(f"Initialized task board with {len(self.task_board)} tasks")
        increment("coordinator_task_board_initialized_total")

    def get_ready_task_ids(self) -> list[str]:
        """
        Compute task IDs that are queued and have all dependencies completed.

        Returns list of task IDs in priority order (by phase and creation order).
        """
        terminal = {"completed", "skipped", "failed"}
        ready = []

        for task_id in sorted(self.task_board.keys()):  # Maintain order
            task = self.task_board[task_id]

            # Skip if not in queued status
            if task["status"] != "queued":
                continue

            # Check if all dependencies are terminal
            all_deps_done = True
            for dep_id in task.get("depends_on", []):
                if dep_id not in self.task_board:
                    _LOG.warning(f"Task {task_id} depends on unknown task {dep_id}")
                    continue
                if self.task_board[dep_id]["status"] not in terminal:
                    all_deps_done = False
                    break

            if all_deps_done:
                ready.append(task_id)

        _LOG.debug(f"Ready tasks: {ready}")
        return ready

    def assign_task(self, task_id: str, teammate_id: str) -> None:
        """Assign a task to a teammate."""
        if task_id not in self.task_board:
            raise ValueError(f"Unknown task: {task_id}")

        self.task_board[task_id]["assigned_teammate"] = teammate_id
        self.task_board[task_id]["status"] = "running"
        self.task_assignments[task_id] = teammate_id
        self.task_board[task_id]["attempts"] = (self.task_board[task_id].get("attempts") or 0) + 1

        _LOG.info(f"Assigned task {task_id} to {teammate_id}")
        increment("coordinator_task_assigned_total")

    def mark_task_done(self, task_id: str, emit_event: Optional[Callable[[str, dict[str, Any]], None]] = None) -> None:
        """
        Mark a task as completed and notify of newly ready tasks.

        Args:
            task_id: Task ID to mark as done
            emit_event: Optional callback to emit task.ready events for newly ready tasks
        """
        if task_id not in self.task_board:
            raise ValueError(f"Unknown task: {task_id}")

        self.task_board[task_id]["status"] = "completed"
        self.task_board[task_id]["error"] = None

        _LOG.info(f"Task {task_id} completed")
        increment("coordinator_task_completed_total")

        # Check if any queued tasks just became ready due to this task's completion
        if emit_event:
            newly_ready = self.get_ready_task_ids()
            for ready_task_id in newly_ready:
                if self.task_board[ready_task_id]["status"] == "queued":
                    emit_event("task.ready", {
                        "task_id": ready_task_id,
                        "depends_on": self.task_board[ready_task_id]["depends_on"],
                        "phase": self.task_board[ready_task_id].get("phase", "unknown"),
                    })

    def mark_task_failed(self, task_id: str, error: str = "") -> None:
        """Mark a task as failed."""
        if task_id not in self.task_board:
            raise ValueError(f"Unknown task: {task_id}")

        self.task_board[task_id]["status"] = "failed"
        self.task_board[task_id]["error"] = error

        _LOG.error(f"Task {task_id} failed: {error}")
        increment("coordinator_task_failed_total")

    def all_tasks_done(self) -> bool:
        """Check if all tasks are in terminal state."""
        terminal = {"completed", "skipped", "failed"}
        for task in self.task_board.values():
            if task["status"] not in terminal:
                return False
        return True

    def get_task_summary(self) -> dict[str, Any]:
        """Get summary of all tasks for SSE emission."""
        return {
            "current_state": self.current_state,
            "tasks": self.task_board,
            "ready_tasks": self.get_ready_task_ids(),
            "replanning_count": self.replanning_count,
            "timestamp": datetime.utcnow().isoformat(),
        }

    # ============================================================================
    # Teammate Management
    # ============================================================================

    def next_teammate(self) -> str:
        """Get next teammate in round-robin order."""
        teammates = ["teammate-1", "teammate-2", "teammate-3"]
        idx = self.teammate_rotation % len(teammates)
        self.teammate_rotation += 1
        return teammates[idx]

    # ============================================================================
    # Checkpoint/Restore
    # ============================================================================

    def checkpoint(self) -> dict[str, Any]:
        """Serialize state for pause/resume."""
        return {
            "version": "1.0",
            "run_id": self.run_id,
            "project_id": self.project_id,
            "current_state": self.current_state,
            "requested_outputs": self.requested_outputs,
            "execution_plan": self.execution_plan.to_dict() if self.execution_plan else None,
            "task_board": self.task_board,
            "task_assignments": self.task_assignments,
            "teammate_rotation": self.teammate_rotation,
            "failure_context": self.failure_context,
            "replanning_count": self.replanning_count,
            "checkpoint_timestamp": datetime.utcnow().isoformat(),
        }

    @classmethod
    def restore(cls, checkpoint: dict) -> "CoordinatorStateManager":
        """Deserialize from checkpoint."""
        if checkpoint.get("version") != "1.0":
            raise ValueError(f"Unknown checkpoint version: {checkpoint.get('version')}")

        sm = cls(
            run_id=checkpoint.get("run_id", ""),
            project_id=checkpoint.get("project_id", ""),
            current_state=checkpoint.get("current_state", "init"),
            requested_outputs=checkpoint.get("requested_outputs", []),
            task_board=checkpoint.get("task_board", {}),
            task_assignments=checkpoint.get("task_assignments", {}),
            teammate_rotation=checkpoint.get("teammate_rotation", 0),
            failure_context=checkpoint.get("failure_context", {}),
            replanning_count=checkpoint.get("replanning_count", 0),
        )

        plan_data = checkpoint.get("execution_plan")
        if plan_data:
            sm.execution_plan = ExecutionPlanSnapshot.from_dict(plan_data)

        return sm

    # ============================================================================
    # Utilities
    # ============================================================================

    def __repr__(self) -> str:
        return (
            f"CoordinatorStateManager(state={self.current_state}, "
            f"tasks={len(self.task_board)}, "
            f"ready={len(self.get_ready_task_ids())}, "
            f"replans={self.replanning_count})"
        )
