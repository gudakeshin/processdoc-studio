"""Typed run-event schema and serializers."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, Literal

from app.core.config import settings

RunEventPhase = Literal[
    "lifecycle",
    "permission",
    "fanout",
    "execution",
    "qa",
    "guardrail",
    "retry",
    "hook",
    "heartbeat",
    "terminal",
]

EVENT_SCHEMA_VERSION = "run-events-v1"


@dataclass
class RunEventEnvelope:
    event_type: str
    phase: RunEventPhase
    ts_ms: int
    run_id: str
    payload: dict[str, Any]


def infer_phase(event_type: str) -> RunEventPhase:
    et = str(event_type or "").strip().lower()
    if et.startswith("message.") or et.startswith("thinking.") or et.startswith("skill.") or et.startswith("plan.") or et.startswith("questions.") or et.startswith("status.") or et.startswith("todo.") or et.startswith("task."):
        return "execution"
    if et.startswith("permission_") or et == "permission_stage":
        return "permission"
    if et.startswith("fanout_"):
        return "fanout"
    if et.startswith("hook_") or et == "hook_result":
        return "hook"
    if et.startswith("qa"):
        return "qa"
    if et.startswith("guardrail"):
        return "guardrail"
    if et.startswith("retry") or et == "recovery_mode":
        return "retry"
    if et == "heartbeat":
        return "heartbeat"
    if et in {"failed", "done", "review_ready"}:
        return "terminal"
    if et in {
        "step",
        "output_chunk",
        "skill_selection",
        "coordinator_started",
        "coordinator_completed",
        "coordinator_plan",
        "execution_plan",
        "agent_tool_round",
        "narrative_thinking_excerpt",
    }:
        return "execution"
    if et.startswith("swarm"):
        return "execution"
    return "lifecycle"


def canonical_event_aliases(*, event_type: str, payload: dict[str, Any]) -> list[str]:
    """
    Map legacy/internal run events to Cowork-facing canonical events.
    Keep existing event names and add aliases for backward compatibility.
    """
    et = str(event_type or "").strip().lower()
    status = str(payload.get("status") or "").strip().lower()
    aliases: list[str] = []

    if et == "output_chunk":
        aliases.append("message.token")
    if et in {"done", "failed"}:
        aliases.append("message.done")
    if et == "step" and status == "execution_started":
        aliases.append("message.start")
        aliases.append("plan.phase_start")
        aliases.append("status.update")
    if et == "step" and status == "review_ready":
        aliases.append("plan.phase_complete")
        aliases.append("status.update")
    if et == "step" and "block" in status:
        aliases.append("plan.task_complete")
        aliases.append("status.update")
    if et == "step" and ("start" in status or "run" in status):
        aliases.append("plan.task_start")
        aliases.append("status.update")
    if et == "step" and ("done" in status or "complete" in status or "finish" in status):
        aliases.append("plan.task_complete")
        aliases.append("status.update")
    if et == "skill_selection":
        aliases.append("skill.loading")
    if et == "agent_tool_round":
        aliases.append("skill.completed")
    if et == "qa_report":
        aliases.append("questions.refresh")
    if et == "visual_qa_report":
        aliases.append("thinking.start")

    # Stable order + dedupe
    seen: set[str] = set()
    out: list[str] = []
    for alias in aliases:
        if alias in seen:
            continue
        seen.add(alias)
        out.append(alias)
    return out


def build_event_payload(*, run_id: str, event_type: str, payload_obj: Any, phase: RunEventPhase | None = None) -> dict[str, Any]:
    payload = payload_obj if isinstance(payload_obj, dict) else {"value": payload_obj}
    env = RunEventEnvelope(
        event_type=str(event_type),
        phase=phase or infer_phase(event_type),
        ts_ms=int(time.time() * 1000),
        run_id=str(run_id),
        payload=payload,
    )
    # Keep legacy top-level fields for backward compatibility with existing UI consumers.
    out: dict[str, Any] = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_type": env.event_type,
        "phase": env.phase,
        "ts_ms": env.ts_ms,
        "run_id": env.run_id,
        "payload": env.payload,
    }
    if isinstance(payload, dict) and not bool(settings.event_contract_strict):
        for k, v in payload.items():
            out.setdefault(str(k), v)
    return out


def lifecycle_event(*, run_id: str, event_type: str, action: str, actor: str | None = None) -> dict[str, Any]:
    return build_event_payload(
        run_id=run_id,
        event_type=event_type,
        phase="lifecycle",
        payload_obj={"action": action, "actor": actor or "system"},
    )


def hook_exec_id(*, run_id: str, hook_point: str, hook_name: str) -> str:
    raw = f"{run_id}|{hook_point}|{hook_name}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

