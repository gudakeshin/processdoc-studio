# Phase 0: Coordinator Refactor to Agentic Loop

**Status:** In Progress
**Date:** 2026-04-04
**Owner:** Architecture Team

## Overview

This document describes the refactoring of `Coordinator.run()` from a linear pipeline to an event-driven agentic loop that:
- Uses the swarm task board for execution planning
- Adapts to failures via replanning
- Supports checkpoint/restore for pause/resume
- Maintains backward compatibility with existing behavior

## Current Architecture (Linear Pipeline)

```
Coordinator.run():
1. Parallel fanout (context, skills, plan validation)
2. DPDP redaction
3. Context assembly
4. Process extraction
5. LLM planning (_plan_with_reasoning)
6. Skill selection
7. Parallel/Sequential worker execution (ThreadPoolExecutor or contract nodes)
8. Deliverable quality loop
9. QA loop + remediation
10. Guardrails evaluation
11. Post-generation hooks
```

**Problems:**
- No replanning if workers fail
- No task-level granularity (can't pause/resume mid-execution)
- Fixed worker assignment (no dynamic adaptation)
- No queuing or scheduling (workers are spawned immediately)

## New Architecture (Event-Driven Loop)

### State Machine

```
init
  ↓
planning (call _plan_with_reasoning, build task board)
  ↓
task_assignment (assign ready tasks to teammates)
  ↓
execution (run assigned tasks, poll for completion)
  ↓ (if task fails)
replan_on_failure (lead re-plans strategy)
  ↓
... (back to task_assignment or end)
  ↓ (if all tasks done)
finalize (QA, guardrails, hooks)
  ↓
done
```

### CoordinatorStateManager Class

New file: `backend/app/agents/coordinator_state_manager.py`

Responsible for:
- Tracking loop state (current_state, tasks, assignments)
- Checkpoint serialization/deserialization
- State transitions
- Task status tracking
- Failure recovery

### Coordinator.run() Refactored

The main loop becomes:

```python
def run(self, state, emit_event=None, abort_check=None):
    sm = CoordinatorStateManager(state)

    while True:
        _coordinator_poll_abort()

        if sm.state == "init":
            sm.transition_to("planning")

        elif sm.state == "planning":
            # 1. Parallel fanout
            # 2. DPDP redaction
            # 3. Context assembly
            # 4. Process extraction
            # 5. LLM planning
            # 6. Skill selection
            # 7. Build task board

            sm.transition_to("task_assignment")

        elif sm.state == "task_assignment":
            # Get ready tasks from task board
            ready = sm.get_ready_task_ids()

            if not ready:
                if sm.all_tasks_done():
                    sm.transition_to("finalize")
                else:
                    # Wait for tasks to complete (poll)
                    time.sleep(0.1)
                    continue

            # Assign ready tasks to teammates
            for task_id in ready:
                teammate = sm.next_teammate()
                sm.assign_task(task_id, teammate)

            sm.transition_to("execution")

        elif sm.state == "execution":
            # Poll for task completion
            completed = sm.poll_task_completions(timeout=5.0)

            for task_id, result in completed.items():
                if result.status == "failed":
                    sm.transition_to("replan_on_failure", task_id=task_id)
                    break
                else:
                    sm.mark_task_done(task_id)

            if sm.state == "execution":  # No failures, continue
                sm.transition_to("task_assignment")

        elif sm.state == "replan_on_failure":
            task_id = sm.failure_context.get("task_id")
            error = sm.failure_context.get("error")

            # Call lead agent to replan
            new_plan = self._lead_replan(state, task_id, error)
            sm.update_plan(new_plan)
            sm.mark_task_failed(task_id)

            sm.transition_to("task_assignment")

        elif sm.state == "finalize":
            # QA, guardrails, hooks
            # ... existing code ...

            sm.transition_to("done")
            break

        # Emit state event for SSE
        emit_event("coordinator_state", {"state": sm.state, "tasks": sm.get_task_summary()})
```

## Key Components

### 1. CoordinatorStateManager

Location: `backend/app/agents/coordinator_state_manager.py`

Responsibilities:
- Initialize task board from output types and run_contract
- Track task statuses and assignments
- Compute ready task IDs (using swarm.ready_task_ids)
- Manage teammate pool (round-robin, health checks)
- Checkpoint/restore functionality
- State transitions with validation

```python
@dataclass
class CoordinatorStateManager:
    """Manages coordinator loop state and task board."""

    process_doc_state: ProcessDocState
    tasks: list[RunTask]
    task_assignments: dict[str, str]  # task_id -> teammate_id
    execution_plan: ExecutionPlan
    failure_context: dict[str, Any]
    current_state: str = "init"
    checkpoint: dict[str, Any] = field(default_factory=dict)

    def transition_to(self, new_state: str, **context) -> None:
        """Move to next state with validation."""

    def get_ready_task_ids(self) -> list[str]:
        """Task IDs that are queued and have all deps done."""

    def assign_task(self, task_id: str, teammate_id: str) -> None:
        """Mark task as assigned to teammate."""

    def mark_task_done(self, task_id: str) -> None:
        """Move task to completed status."""

    def mark_task_failed(self, task_id: str, error: str) -> None:
        """Move task to failed status."""

    def all_tasks_done(self) -> bool:
        """All tasks completed or failed?"""

    def checkpoint(self) -> dict[str, Any]:
        """Serialize for pause/resume."""

    @classmethod
    def restore(cls, checkpoint: dict) -> CoordinatorStateManager:
        """Deserialize from checkpoint."""
```

### 2. Task Board Integration

The coordinator will use RunTask DB model (already exists):

```python
from app.db.models import RunTask

def _build_task_board(self, state: ProcessDocState, execution_plan: ExecutionPlan) -> list[RunTask]:
    """Create RunTask rows for coordinator loop."""
    # Build from execution_plan.ordered_output_types
    # Use enrich_run_todos_with_dependencies to set dependencies
    # Persist to DB
```

### 3. Failure Handling & Replanning

New method: `_lead_replan()`

```python
def _lead_replan(
    self,
    state: ProcessDocState,
    failed_task_id: str,
    error: str,
) -> ExecutionPlan:
    """Call lead agent (LLM) to generate new plan after failure."""
    # Inject failure context into coordinator planning prompt
    # Call claude_generate_with_thinking
    # Return new ExecutionPlan
```

### 4. Checkpoint/Restore

For pause/resume:

```python
def checkpoint_state(sm: CoordinatorStateManager) -> dict:
    """Serialize for pause."""
    return {
        "coordinator_state": sm.current_state,
        "tasks": [serialize_task(t) for t in sm.tasks],
        "assignments": sm.task_assignments,
        "plan": sm.execution_plan.to_dict(),
        "failure_context": sm.failure_context,
    }

def restore_from_checkpoint(checkpoint: dict) -> CoordinatorStateManager:
    """Deserialize from pause."""
    # Validate checkpoint format
    # Reconstruct task board from checkpoint
    # Resume from last state
```

## Integration Points

### run_worker.py

The `run_worker.run_sync()` function will:
1. Create CoordinatorStateManager
2. Loop coordinator.run()
3. Checkpoint after each state transition (if checkpointing enabled)
4. Emit SSE events for UI

### SwarmPanel.tsx

UI will show:
- Current coordinator state
- Task board with statuses
- Ready tasks (can be manually overridden?)
- Failure messages with retry options

## Testing Strategy

### Unit Tests (test_coordinator_state_manager.py)

- [ ] State machine transitions
- [ ] Task board construction
- [ ] Ready task computation
- [ ] Checkpoint serialization/deserialization
- [ ] Teammate round-robin assignment

### Integration Tests (test_coordinator_refactor.py)

- [ ] 3-task DAG executes in dependency order
- [ ] Task failure triggers replan
- [ ] Pause/resume restores from checkpoint
- [ ] QA/guardrails still work after refactor
- [ ] Existing runs without swarm still work

### E2E Tests (CI/CD)

- [ ] Generate document with default settings
- [ ] Generate with swarm enabled
- [ ] Pause/resume workflow
- [ ] Verify output quality same as before

## Backward Compatibility

The refactor will maintain full backward compatibility:
- Without swarm enabled, behaves as linear pipeline
- Existing run_contract format still works
- Output quality metrics unchanged
- Same skill registry and agents

## Timeline

- Week 1: Design & state manager implementation
- Week 2: Coordinator.run() refactor + basic loop
- Week 3: Task board integration + failure handling
- Week 4: Checkpoint/restore + testing + hardening

---

## Design Decisions & Tradeoffs

### Decision 1: Synchronous vs Asynchronous Loop

**Choice:** Synchronous (blocking I/O with polling)

**Reasoning:**
- Simpler state tracking
- Works with existing ThreadPoolExecutor workers
- Easier debugging (linear execution)
- Can move to async in future if needed

**Tradeoff:**
- Less efficient than async (blocking on task polls)
- Can optimize with Redis queues in Phase 2

### Decision 2: Replanning Strategy

**Choice:** Lead agent replans on any task failure

**Reasoning:**
- Matches Cowork behavior
- Adapts to unexpected situations
- LLM cost is minimal (1-2 calls per failure, rare)

**Tradeoff:**
- More expensive than "fail fast" approach
- Need to bound replanning loops (max 3 replans?)

### Decision 3: Task Board Persistence

**Choice:** Use existing RunTask DB model

**Reasoning:**
- Already has necessary fields (id, status, depends_on_json, assigned_teammate_id)
- Swarm API already uses it
- Durable across restarts

**Tradeoff:**
- Heavy (JSON serialization for each poll)
- Can optimize with in-memory cache + periodic flush

### Decision 4: Checkpoint Format

**Choice:** JSON serialization of state + task board snapshot

**Reasoning:**
- Human-readable for debugging
- Easy to inspect/modify for manual recovery
- Compatible with existing event log

**Tradeoff:**
- Checkpoint size may be large (e.g., large context)
- Can compress if needed

