from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any
import json
from pathlib import Path

from app.core.config import settings

_LOCK = Lock()

_COUNTERS: dict[str, int] = defaultdict(int)
_LATENCY_TOTAL_MS: dict[str, float] = defaultdict(float)
_LATENCY_COUNT: dict[str, int] = defaultdict(int)
_GAUGES: dict[str, float] = defaultdict(float)
_RECENT_RUNS: list[dict[str, Any]] = []
_RECENT_LIMIT = 200
_SNAPSHOT_PATH = Path(settings.observability_snapshot_path).expanduser() if str(settings.observability_snapshot_path or "").strip() else None

# Optional HELP lines for /metrics/prometheus (metric name as stored in counters).
_PROMETHEUS_COUNTER_HELP: dict[str, str] = {
    "memory_items_injected_into_context_total": "MemoryItem lines merged into assemble_v2 context.",
    "memory_items_consent_skipped_total": "MemoryItem rows excluded due to consent_state.",
    "memory_items_ledger_blocked_total": "MemoryItem rows excluded: principal_id set but Consent Ledger not granted.",
    "memory_batch_create_total": "Items created via POST /api/memory/{pid}/batch.",
    "memory_events_written_total": "MemoryEvent rows appended.",
    "memory_events_pruned_total": "MemoryEvent rows deleted by retention policy.",
    "memory_events_deduped_total": "MemoryEvent append deduplicated by fingerprint.",
    "user_preference_learning_runs_bumped_total": "UserProjectPreference learning_signals.runs_completed increments after successful runs.",
    "coordinator_context_assemble_v2_total": "Coordinator calls to TieredContextEngine.assemble_v2.",
    "run_done_total": "Runs completed successfully.",
    "run_failed_total": "Runs failed.",
    "fanout_failures_total": "Parallel fanout stage failures.",
    "retry_transition_invalid_total": "Invalid retry FSM transitions detected.",
    "hook_timeout_total": "Hook executions timing out.",
    "hook_skip_total": "Hook executions skipped (idempotency or concurrency).",
    "sse_replay_continuity_check_total": "SSE replay continuity checks executed.",
    "deliverable_quality_runs_total": "Runs that entered contract-driven deliverable quality critique.",
    "deliverable_quality_pass_total": "Deliverable quality loops that met contract aggregate threshold.",
    "deliverable_quality_fail_total": "Deliverable quality loops that ended below threshold after max rounds.",
    "deliverable_quality_rounds_total": "Individual deliverable quality critique rounds executed.",
    "conversation_digest_built_total": "Runs where a non-empty HITL conversation digest was built for coordinator/workers.",
    "planner_excerpt_chars_total": "Sum of character lengths of planner retrieval excerpts attached to coordinator planning.",
    "narrative_thinking_used_total": "Narrative subagent calls that used extended thinking (when flag enabled).",
}


def increment(metric: str, value: int = 1) -> None:
    with _LOCK:
        _COUNTERS[metric] += int(value)
        _persist_snapshot_locked()


def observe_latency(metric: str, duration_ms: float) -> None:
    with _LOCK:
        _LATENCY_TOTAL_MS[metric] += float(duration_ms)
        _LATENCY_COUNT[metric] += 1
        _persist_snapshot_locked()


def set_gauge(metric: str, value: float) -> None:
    with _LOCK:
        _GAUGES[metric] = float(value)
        _persist_snapshot_locked()


def record_run_trace(event: str, *, project_id: str, run_id: str, extra: dict[str, Any] | None = None) -> None:
    payload = {"event": event, "project_id": project_id, "run_id": run_id, "extra": extra or {}}
    with _LOCK:
        _RECENT_RUNS.append(payload)
        if len(_RECENT_RUNS) > _RECENT_LIMIT:
            del _RECENT_RUNS[: len(_RECENT_RUNS) - _RECENT_LIMIT]
        _persist_snapshot_locked()


def _persist_snapshot_locked() -> None:
    if _SNAPSHOT_PATH is None:
        return
    try:
        _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "counters": dict(_COUNTERS),
            "gauges": dict(_GAUGES),
            "latency_total_ms": dict(_LATENCY_TOTAL_MS),
            "latency_count": dict(_LATENCY_COUNT),
            "recent_run_events": list(_RECENT_RUNS[-_RECENT_LIMIT:]),
        }
        _SNAPSHOT_PATH.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
    except Exception:
        return


def snapshot() -> dict[str, Any]:
    with _LOCK:
        latency_avg = {
            name: round(_LATENCY_TOTAL_MS[name] / _LATENCY_COUNT[name], 2)
            for name in _LATENCY_TOTAL_MS
            if _LATENCY_COUNT[name] > 0
        }
        return {
            "counters": dict(_COUNTERS),
            "gauges": dict(_GAUGES),
            "latency_avg_ms": latency_avg,
            "recent_run_events": list(_RECENT_RUNS[-50:]),
        }


def prometheus_text() -> str:
    snap = snapshot()
    lines: list[str] = []
    counters = snap.get("counters", {}) if isinstance(snap.get("counters"), dict) else {}
    gauges = snap.get("gauges", {}) if isinstance(snap.get("gauges"), dict) else {}
    latency = snap.get("latency_avg_ms", {}) if isinstance(snap.get("latency_avg_ms"), dict) else {}
    for name, value in counters.items():
        raw_name = str(name)
        metric = raw_name.replace("-", "_")
        help_text = _PROMETHEUS_COUNTER_HELP.get(raw_name) or _PROMETHEUS_COUNTER_HELP.get(metric)
        if help_text:
            safe = help_text.replace("\\", "\\\\").replace("\n", " ")
            lines.append(f"# HELP {metric} {safe}")
        lines.append(f"# TYPE {metric} counter")
        lines.append(f"{metric} {int(value)}")
    for name, value in latency.items():
        metric = f"{str(name).replace('-', '_')}_avg_ms"
        lines.append(f"# TYPE {metric} gauge")
        lines.append(f"{metric} {float(value)}")
    for name, value in gauges.items():
        metric = str(name).replace("-", "_")
        lines.append(f"# TYPE {metric} gauge")
        lines.append(f"{metric} {float(value)}")
    return "\n".join(lines) + ("\n" if lines else "")
