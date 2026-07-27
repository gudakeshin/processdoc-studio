"""Background run execution and persisted SSE events (survives reconnect)."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import contextvars
import hashlib
import json
import logging
import re
import threading
import time
import traceback
from datetime import datetime, timedelta
from app.core.tz import IST
from time import perf_counter
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agents.coordinator import Coordinator
from app.core.config import settings
from app.core.exceptions import RunBudgetExceeded
from app.core.narrative_feedback import (
    build_narrative_feedback_hints,
    extract_narrative_signals,
    narrative_signals_from_run_dir,
    persist_narrative_signals,
)
from app.core.run_control import RunAborted
from app.core.sanitization import sanitize_memory_payload_dict
from app.db.models import MemoryEvent, Project, ProjectMemoryProfile, Run, RunEvent, RunTask, UserProjectPreference, utcnow
from app.db.session import SessionLocal
from app.schemas.coordinator_run import CoordinatorRunInput
from app.schemas.run_payloads import GuardrailReportDoc, QaReportDoc
from app.services.conversation_digest import build_conversation_digest_for_run_with_trace
from app.services.hooks import hook_execution_exists, record_hook_execution, run_hooks_sync, sync_disabled_hooks_from_db
from app.services.langfuse_tracing import langfuse_event, langfuse_span
from app.services.observability import increment, observe_latency, record_run_trace, set_gauge
from app.services.permission_pipeline import evaluate_permission_pipeline
from app.services.proposal_policy import PROPOSAL_SKILL_ID
from app.services.run_evaluator_pipeline import (
    _build_evaluator_pipeline,
    _guardrail_regeneration_directive,
    _pptx_evidence_gate_from_run_dir,
)
from app.services.run_visual_qa_augment import (
    _augment_visual_qa_with_design_review,
    _augment_visual_qa_with_render_hints,
    _persist_pptx_visual_critic_signals,
)
from app.services.otel_tracing import start_span
from app.services.retry_policy import (
    classify_retry_mode,
    compute_rate_limit_backoff,
    fallback_strategy_for_output,
    heartbeat_event,
    overflow_recovery_event,
    should_apply_fallback,
    validate_retry_transition,
)
from app.services.run_budget import get_run_usage, project_token_context, run_llm_budget
from app.services.llm_pricing import calculate_run_cost_usd
from app.services.run_events import hook_exec_id
from app.services.run_event_service import RunEventService
from app.services.run_queue.runtime import RunQueueRuntime
from app.services.run_tasks import sync_run_tasks_from_snapshot
from app.services.run_todo_snapshot import emit_run_todo_snapshot, todo_set_status
from app.services.storage import save_run_artifacts, workspace_path
from app.services.swarm import enrich_run_todos_with_dependencies, ensure_swarm_team
from app.services.visual_qa import run_visual_quality_check, save_visual_qa_report
from app.services.visual_qa_chat import persist_visual_qa_assistant_message
from app.services.wiki_maintenance import run_weekly_librarian_tick
from app.services.wiki_graph import build_relationships_incremental

_queue_rt = RunQueueRuntime(settings)
_run_event_service = RunEventService(publish_event=_queue_rt.publish_run_event)
_log = logging.getLogger(__name__)
_embedded_redis_consumer_lock = threading.Lock()
_embedded_redis_consumer_started = False
_last_librarian_tick_ts = 0.0
_librarian_tick_interval_sec = 7 * 24 * 60 * 60
_stuck_sweep_interval_sec = 30.0
_stuck_watchdog_lock = threading.Lock()
_stuck_watchdog_started = False

# Graceful shutdown: set by drain_execution_worker() on SIGTERM/SIGINT (via the
# FastAPI lifespan shutdown hook) so dispatch loops stop pulling new jobs while
# in-flight runs are given a bounded window to finish instead of being killed
# mid-execution when the process exits.
_draining = threading.Event()
_active_futures: set[concurrent.futures.Future] = set()
_active_futures_lock = threading.Lock()


def _consume_wiki_rebuild_events() -> None:
    """Best-effort consumer for wiki rebuild events emitted by ingest."""
    if not bool(getattr(settings, "wiki_evented_graph_rebuild_enabled", False)):
        return
    root = workspace_path("")
    event_files = list(root.glob("*/wiki/.meta/wiki_rebuild_events.jsonl"))
    event_files.append(root / "leading_practices" / "wiki" / ".meta" / "wiki_rebuild_events.jsonl")
    for events_file in event_files:
        if not events_file.exists():
            continue
        try:
            lines = [ln for ln in events_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if not lines:
                continue
            latest = json.loads(lines[-1])
            wiki_type = str(latest.get("wiki_type") or "project")
            project_id = latest.get("project_id")
            if wiki_type == "project" and not project_id:
                continue
            build_relationships_incremental(wiki_type, project_id)
            events_file.write_text("", encoding="utf-8")
        except Exception as exc:
            _log.debug("wiki rebuild event consume skipped for %s: %s", events_file, exc)

# Auto re-run after Visual / evaluator gate failure: max remediation enqueue rounds.
MAX_EVALUATOR_REMEDIATION_ROUNDS = 3

_PLAN_KEYS_TO_CLEAR_AFTER_SUCCESSFUL_EVALUATOR: tuple[str, ...] = (
    "prior_pptx_slides",
    "pptx_visual_feedback",
    "docx_visual_feedback",
    "xlsx_visual_feedback",
    "pdf_visual_feedback",
    "process_map_visual_feedback",
    "docx_narrative_feedback",
    "pdf_narrative_feedback",
    "pptx_narrative_feedback",
)


def _strip_visual_remediation_from_plan(plan_json: str | None) -> str | None:
    """Remove one-shot Visual QA retry fields so later actions do not reuse stale decks."""
    if not plan_json:
        return plan_json
    try:
        obj = json.loads(plan_json)
        if not isinstance(obj, dict):
            return plan_json
        for k in _PLAN_KEYS_TO_CLEAR_AFTER_SUCCESSFUL_EVALUATOR:
            obj.pop(k, None)
        return json.dumps(obj)
    except Exception:
        return plan_json


def _sanitize_memory_payload(payload_obj: Any) -> dict[str, Any]:
    return sanitize_memory_payload_dict(payload_obj)


def _canonical_memory_payload(payload_obj: Any) -> str:
    payload = _sanitize_memory_payload(payload_obj)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _memory_fingerprint(*, project_id: str, run_id: str, event_type: str, canonical_payload: str) -> str:
    raw = f"{project_id}|{run_id}|{event_type}|{canonical_payload}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _dedupe_text_list(items: Any, *, max_items: int = 40) -> list[str]:
    if not isinstance(items, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        key = re.sub(r"\s+", " ", text).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max_items:
            break
    return out


def _project_retention_days(project_id: str) -> int:
    default_days = int(getattr(settings, "memory_events_retention_days", 30))
    settings_path = workspace_path(project_id) / "settings.json"
    if not settings_path.exists():
        return default_days
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "memory_events_retention_days" in data:
            return int(data["memory_events_retention_days"])
    except Exception:
        return default_days
    return default_days


# Track last prune time per project to avoid a DELETE on every single event write.
# Pruning is idempotent, so running it once per hour per project is sufficient.
_prune_last_run: dict[str, float] = {}
_PRUNE_MIN_INTERVAL_S = 3600


def _prune_old_memory_events(session: Session, *, project_id: str) -> None:
    retention_days = _project_retention_days(project_id)
    if retention_days <= 0:
        return
    cutoff = datetime.now(IST).replace(tzinfo=None) - timedelta(days=retention_days)
    result = session.execute(
        delete(MemoryEvent).where(
            MemoryEvent.project_id == project_id,
            MemoryEvent.created_at < cutoff,
        )
    )
    deleted_count = int(result.rowcount or 0)
    if deleted_count > 0:
        increment("memory_events_pruned_total", deleted_count)


def append_memory_event(
    session: Session,
    *,
    project_id: str,
    run_id: str,
    event_type: str,
    payload_obj: Any,
) -> MemoryEvent:
    canonical_payload = _canonical_memory_payload(payload_obj)
    fingerprint = _memory_fingerprint(
        project_id=project_id,
        run_id=run_id,
        event_type=event_type,
        canonical_payload=canonical_payload,
    )
    existing = session.scalar(
        select(MemoryEvent).where(
            MemoryEvent.project_id == project_id,
            MemoryEvent.run_id == run_id,
            MemoryEvent.event_type == event_type,
            MemoryEvent.fingerprint == fingerprint,
        )
    )
    if existing is not None:
        increment("memory_events_deduped_total")
        return existing
    ev = MemoryEvent(
        project_id=project_id,
        run_id=run_id,
        event_type=event_type,
        fingerprint=fingerprint,
        payload=canonical_payload,
    )
    session.add(ev)
    session.flush()
    now = time.time()
    if now - _prune_last_run.get(project_id, 0.0) >= _PRUNE_MIN_INTERVAL_S:
        _prune_old_memory_events(session, project_id=project_id)
        _prune_last_run[project_id] = now
    increment("memory_events_written_total")
    return ev


def upsert_project_memory_profile(session: Session, project_id: str, summary_obj: dict[str, Any]) -> None:
    row = session.scalar(select(ProjectMemoryProfile).where(ProjectMemoryProfile.project_id == project_id))
    normalized = _sanitize_memory_payload(summary_obj)
    normalized["non_negotiables"] = _dedupe_text_list(normalized.get("non_negotiables"), max_items=30)
    normalized["recent_changes"] = _dedupe_text_list(normalized.get("recent_changes"), max_items=50)
    payload = json.dumps(normalized, sort_keys=True)
    if row is None:
        row = ProjectMemoryProfile(project_id=project_id, summary_json=payload)
        session.add(row)
    else:
        row.summary_json = payload
    session.flush()


def _bump_learning_runs_completed(session: Session, user_id: str, project_id: str) -> None:
    """Increment learning_signals.runs_completed for v4-style behavioral analytics (best-effort)."""
    if not user_id or not project_id:
        return
    row = session.scalar(
        select(UserProjectPreference).where(
            UserProjectPreference.user_id == user_id,
            UserProjectPreference.project_id == project_id,
        )
    )
    base: dict[str, Any] = {}
    if row and row.preferences_json:
        try:
            parsed = json.loads(row.preferences_json)
            if isinstance(parsed, dict):
                base = parsed
        except Exception:
            base = {}
    ls = base.get("learning_signals")
    if not isinstance(ls, dict):
        ls = {}
    n = int(ls.get("runs_completed", 0)) + 1
    ls["runs_completed"] = min(n, 1_000_000)
    base["learning_signals"] = ls
    payload = json.dumps(base, sort_keys=True)
    now = datetime.now(IST).replace(tzinfo=None)
    if row is None:
        session.add(
            UserProjectPreference(
                user_id=user_id,
                project_id=project_id,
                preferences_json=payload,
                updated_at=now,
            )
        )
    else:
        row.preferences_json = payload
        row.updated_at = now
    increment("user_preference_learning_runs_bumped_total")


def append_run_event(session: Session, run_id: str, event_type: str, payload_obj: Any) -> RunEvent:
    return _run_event_service.record_event(
        session,
        run_id=run_id,
        event_type=event_type,
        payload_obj=payload_obj,
    )


def _emit_and_sync_todo_snapshot(
    session: Session,
    *,
    project_id: str,
    run_id: str,
    run_todos: list[dict[str, Any]],
) -> None:
    todos_for_sync: list[dict[str, Any]] = [dict(x) for x in run_todos]
    swarm_team_id: str | None = None
    if bool(getattr(settings, "swarm_orchestration_enabled", False)):
        team = ensure_swarm_team(session, project_id=project_id, run_id=run_id)
        swarm_team_id = team.id
        todos_for_sync = enrich_run_todos_with_dependencies(todos_for_sync)
    emit_run_todo_snapshot(lambda et, pl: append_run_event(session, run_id, et, pl), todos_for_sync)
    had_existing = bool(
        session.scalar(select(func.count()).select_from(RunTask).where(RunTask.run_id == run_id)) or 0
    )
    transitions = sync_run_tasks_from_snapshot(
        session,
        project_id=project_id,
        run_id=run_id,
        todos=todos_for_sync,
        swarm_team_id=swarm_team_id,
    )
    if not had_existing:
        append_run_event(
            session,
            run_id,
            "todo.checklist_created",
            {"tasks": [{"id": t.get("id"), "label": t.get("label"), "status": t.get("status")} for t in todos_for_sync]},
        )
    for t in transitions:
        et = str(t.get("event") or "")
        if not et:
            continue
        append_run_event(session, run_id, et, t)


def _start_embedded_redis_consumer_once() -> None:
    """Run Redis queue consumer inside the API process (solo dev / single node only)."""
    global _embedded_redis_consumer_started
    if not bool(getattr(settings, "run_queue_embed_redis_consumer", False)):
        return
    with _embedded_redis_consumer_lock:
        if _embedded_redis_consumer_started:
            return
        client = _queue_rt.get_redis_client()
        if client is None:
            _log.error(
                "run_queue_embed_redis_consumer=true but Redis is unavailable; "
                "runs will stay queued until Redis is up or you start a dedicated worker."
            )
            return
        _embedded_redis_consumer_started = True
    threading.Thread(target=run_redis_worker_loop, name="run-queue-redis-consumer", daemon=True).start()
    _log.info("Started embedded Redis run-execution consumer (RUN_QUEUE_EMBED_REDIS_CONSUMER=true).")


def _stuck_watchdog_loop() -> None:
    """Auto-fail stuck runs on a fixed timer, independent of queue activity.

    The dispatch loop blocks in local_wait_pop_job() while the queue is idle — which is
    exactly when a wedged run needs sweeping — so the watchdog runs in its own thread.
    """
    while True:
        try:
            auto_fail_stuck_runs()
        except Exception as exc:  # never let the watchdog thread die
            _log.warning("stuck-run watchdog tick error: %s", exc)
        time.sleep(_stuck_sweep_interval_sec)


def _start_stuck_watchdog_once() -> None:
    global _stuck_watchdog_started
    if int(getattr(settings, "run_stuck_timeout_sec", 0) or 0) <= 0:
        return
    with _stuck_watchdog_lock:
        if _stuck_watchdog_started:
            return
        _stuck_watchdog_started = True
    threading.Thread(target=_stuck_watchdog_loop, name="run-stuck-watchdog", daemon=True).start()
    _log.info(
        "Started stuck-run watchdog (interval=%ss, timeout=%ss).",
        _stuck_sweep_interval_sec,
        settings.run_stuck_timeout_sec,
    )


def start_execution_worker() -> None:
    _start_stuck_watchdog_once()
    if _queue_rt.queue_backend == "redis":
        if not bool(getattr(settings, "run_queue_embed_redis_consumer", False)):
            _log.warning(
                "RUN_QUEUE_BACKEND=redis but no in-process consumer: enqueue_run_execution will push "
                "to Redis and runs will stall until you start "
                "`python -m app.workers.run_execution_worker` or set "
                "RUN_QUEUE_EMBED_REDIS_CONSUMER=true (single-process / dev only)."
            )
        _start_embedded_redis_consumer_once()
        return
    _queue_rt.start_local_daemon(_queue_worker_loop)


def drain_execution_worker(timeout_sec: float = 30.0) -> None:
    """Stop dispatching new local-queue jobs and wait (bounded) for in-flight runs to finish.

    Called from the FastAPI lifespan shutdown hook so SIGTERM/SIGINT (docker stop,
    rolling deploy) doesn't kill a run mid-composition. Daemon threads are otherwise
    killed outright on process exit with no chance to persist state.
    """
    if _queue_rt.queue_backend == "redis":
        # The embedded Redis consumer isn't the primary deployment path (a dedicated
        # `run_execution_worker` process is); nothing local to drain here.
        return
    _draining.set()
    with _active_futures_lock:
        futures = list(_active_futures)
    if not futures:
        return
    _log.warning("Draining %d in-flight run(s) before shutdown (up to %ss)...", len(futures), timeout_sec)
    done, not_done = concurrent.futures.wait(futures, timeout=timeout_sec)
    if not_done:
        _log.critical(
            "%d run(s) still executing after %ss drain timeout; process is exiting with work in flight.",
            len(not_done),
            timeout_sec,
        )
    else:
        _log.info("Drained %d in-flight run(s) cleanly.", len(done))


def enqueue_run_execution(project_id: str, run_id: str) -> bool:
    """Queue run for execution once approved (exactly-once per process)."""
    key = f"{project_id}:{run_id}"
    lock = _queue_rt.lock_for(run_id)
    with lock:
        session = SessionLocal()
        try:
            run = session.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
            if not run or run.status not in {"approved", "running"}:
                return False
            if _queue_rt.queue_backend == "redis":
                client = _queue_rt.get_redis_client()
                if client is not None:
                    dedupe_key = f"{_queue_rt.redis_enqueue_dedupe_prefix}:{project_id}:{run_id}"
                    # Cross-instance idempotency guard for enqueue operations.
                    inserted = bool(
                        client.set(dedupe_key, "1", nx=True, ex=_queue_rt.redis_enqueue_dedupe_ttl_sec)
                    )
                    if not inserted:
                        increment("run_execution_enqueue_duplicate_total")
                        return False
                    payload = {
                        "project_id": project_id,
                        "run_id": run_id,
                        "attempt": 0,
                        "enqueued_at_ms": int(time.time() * 1000),
                    }
                    client.rpush(_queue_rt.redis_queue_name, json.dumps(payload))
                    increment("run_execution_enqueued_total")
                    langfuse_span(
                        trace_id=run_id,
                        name="queue.enqueue",
                        input_payload={"project_id": project_id, "backend": "redis"},
                    )
                    append_run_event(session, run_id, "step", {"status": "execution_enqueued", "backend": "redis"})
                    session.commit()
                    return True
                # Redis mode requires a dedicated redis worker; fail fast instead of silently falling back.
                append_run_event(
                    session,
                    run_id,
                    "step",
                    {
                        "status": "execution_enqueue_failed",
                        "backend": "redis",
                        "reason": "redis_unavailable",
                        "message": "Redis backend configured but Redis client is unavailable.",
                    },
                )
                run.status = "failed"
                session.commit()
                return False
            # Fallback local queue path.
            start_execution_worker()
            job = {
                "project_id": project_id,
                "run_id": run_id,
                "attempt": 0,
                "enqueued_at_ms": int(time.time() * 1000),
            }
            if not _queue_rt.local_try_enqueue(key, job):
                return False
            increment("run_execution_enqueued_total")
            langfuse_span(
                trace_id=run_id,
                name="queue.enqueue",
                input_payload={"project_id": project_id, "backend": "local"},
            )
            append_run_event(session, run_id, "step", {"status": "execution_enqueued", "backend": "local"})
            session.commit()
            return True
        finally:
            session.close()


def _run_has_execution_enqueued_not_started(session: Session, run_id: str) -> bool:
    return _run_event_service.has_execution_enqueued_not_started(session, run_id=run_id)


_STARTUP_RECONCILE_LOCK_KEY = "processdoc:run-queue:startup-reconcile"
_STARTUP_RECONCILE_LOCK_TTL_SEC = 45


def _acquire_startup_reconcile_lock() -> bool:
    """Best-effort: only one process reconciles when Redis is reachable."""
    client = _queue_rt.get_redis_client()
    if client is None:
        return True
    try:
        return bool(client.set(_STARTUP_RECONCILE_LOCK_KEY, "1", nx=True, ex=_STARTUP_RECONCILE_LOCK_TTL_SEC))
    except Exception:
        return True


def reconcile_stalled_approved_runs_on_startup() -> None:
    """Re-fill the local in-memory queue after API restart when the DB still shows a stalled enqueue."""
    if not settings.run_queue_startup_reconcile:
        return
    if _queue_rt.queue_backend != "local":
        return
    if not _acquire_startup_reconcile_lock():
        _log.info("run_queue startup reconcile skipped (another instance holds Redis lock)")
        return
    session = SessionLocal()
    try:
        approved = session.scalars(select(Run).where(Run.status == "approved")).all()
        re_enqueued = 0
        for run in approved:
            if not _run_has_execution_enqueued_not_started(session, run.id):
                continue
            ok = enqueue_run_execution(run.project_id, run.id)
            if ok:
                re_enqueued += 1
            _log.info(
                "run_queue startup reconcile: run_id=%s project_id=%s re_enqueued=%s",
                run.id,
                run.project_id,
                ok,
            )
        if re_enqueued:
            _log.info("run_queue startup reconcile: total re_enqueued=%s", re_enqueued)
        # A run still in status="running" on a fresh process is definitionally orphaned: the
        # worker thread that owned it died with the previous process. Fail it so its admission
        # slot frees and the UI stops showing it as active.
        orphaned = session.scalars(select(Run).where(Run.status == "running")).all()
        for run in orphaned:
            run.status = "failed"
            run.abort_requested = True
            run.error_message = "Orphaned by restart: worker thread no longer running."
            session.commit()
            append_run_event(session, run.id, "stuck_auto_failed", {"reason": "orphaned_by_restart"})
            session.commit()
        if orphaned:
            _log.info("run_queue startup reconcile: failed %s orphaned running run(s)", len(orphaned))
    except SQLAlchemyError as exc:
        _log.warning("run_queue startup reconcile failed: %s", exc)
    finally:
        session.close()


def auto_fail_stuck_runs() -> int:
    """Fail runs wedged in status="running" with no RunEvent newer than run_stuck_timeout_sec.

    Backstop for the cooperative deadline in _execute_run_job: catches runs whose coordinator
    never yields (so _abort_check is never polled) or whose worker thread died without flipping
    status. Flipping status to "failed" frees the admission slot immediately; with the local
    fixed thread pool a truly wedged OS thread is only reclaimed on process restart.
    Returns the number of runs auto-failed.
    """
    timeout_sec = int(getattr(settings, "run_stuck_timeout_sec", 0) or 0)
    if timeout_sec <= 0:
        return 0
    cutoff = utcnow() - timedelta(seconds=timeout_sec)
    failed = 0
    session = SessionLocal()
    try:
        running = session.scalars(select(Run).where(Run.status == "running")).all()
        for run in running:
            last_event_at = session.scalar(
                select(func.max(RunEvent.created_at)).where(RunEvent.run_id == run.id)
            )
            ref = last_event_at or run.approved_at or run.created_at
            if ref is None or ref > cutoff:
                continue
            run.abort_requested = True
            run.status = "failed"
            run.error_message = f"Auto-failed: no progress for over {timeout_sec}s (stuck-run watchdog)."
            session.commit()
            append_run_event(
                session,
                run.id,
                "stuck_auto_failed",
                {
                    "reason": "no_progress",
                    "timeout_sec": timeout_sec,
                    "last_event_at": ref.isoformat() if ref else None,
                },
            )
            session.commit()
            failed += 1
            _log.warning(
                "stuck-run watchdog auto-failed run_id=%s project_id=%s (idle since %s)",
                run.id,
                run.project_id,
                ref.isoformat() if ref else "n/a",
            )
    except SQLAlchemyError as exc:
        _log.warning("stuck-run watchdog failed: %s", exc)
    finally:
        session.close()
    return failed


def admission_status(project_id: str, *, user_id: str | None = None) -> dict[str, Any]:
    """
    Admission control snapshot for fairness and backpressure.
    Active runs are statuses: approved|running.
    """
    project_active = 0
    global_active = 0
    user_active = 0
    session = SessionLocal()
    try:
        project_active = int(
            session.scalar(
                select(func.count())
                .select_from(Run)
                .where(Run.project_id == project_id, Run.status.in_(["approved", "running"]))
            )
            or 0
        )
        global_active = int(
            session.scalar(select(func.count()).select_from(Run).where(Run.status.in_(["approved", "running"]))) or 0
        )
        if user_id:
            user_active = int(
                session.scalar(
                    select(func.count())
                    .select_from(Run)
                    .where(Run.approved_by == user_id, Run.status.in_(["approved", "running"]))
                )
                or 0
            )
    except SQLAlchemyError:
        # Graceful fallback for startup/test edge-cases before migrations/tables exist.
        project_active = 0
        global_active = 0
        user_active = 0
    finally:
        session.close()

    queue_stats = queue_runtime_stats()
    project_allowed = project_active < _queue_rt.max_active_runs_per_project
    global_allowed = global_active < _queue_rt.max_active_runs_global
    user_allowed = True if not user_id else user_active < _queue_rt.max_active_runs_per_user
    workers = int(queue_stats.get("worker_count") or 1)
    queue_depth = int(queue_stats.get("depth") or 0)
    retry_after_sec = max(1, min(60, ((queue_depth // max(1, workers)) + 1) * 2))
    return {
        "project_id": project_id,
        "project_active_runs": project_active,
        "project_limit": _queue_rt.max_active_runs_per_project,
        "global_active_runs": global_active,
        "global_limit": _queue_rt.max_active_runs_global,
        "user_id": user_id,
        "user_active_runs": user_active if user_id else None,
        "user_limit": _queue_rt.max_active_runs_per_user if user_id else None,
        "queue_depth": queue_depth,
        "queue_backend": queue_stats.get("backend"),
        "retry_after_sec": retry_after_sec,
        "allowed": bool(project_allowed and global_allowed and user_allowed),
    }


def maybe_start_run_execution(project_id: str, run_id: str) -> None:
    """Backward-compatible alias to enqueue execution."""
    enqueue_run_execution(project_id, run_id)


def _queue_worker_loop() -> None:
    """Dispatch loop: pops jobs and submits them to a thread pool so multiple runs execute concurrently."""
    max_workers = int(getattr(settings, "run_queue_local_max_workers", 4))
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="run-exec",
    )
    while not _draining.is_set():
        _queue_rt.mark_worker_heartbeat()
        global _last_librarian_tick_ts
        now = time.time()
        if now - _last_librarian_tick_ts >= _librarian_tick_interval_sec:
            try:
                run_weekly_librarian_tick("leading_practice", None)
            except Exception as exc:
                _log.warning("%s: suppressed error: %s", '_queue_worker_loop', exc)
            _last_librarian_tick_ts = now
        _consume_wiki_rebuild_events()
        job = _queue_rt.local_wait_pop_job(timeout=1.0)
        if job is None:
            continue
        project_id = str(job.get("project_id", ""))
        run_id = str(job.get("run_id", ""))
        attempt = int(job.get("attempt", 0) or 0)
        attempt_history = job.get("attempt_history")
        if not isinstance(attempt_history, list):
            attempt_history = []
        key = f"{project_id}:{run_id}"
        _queue_rt.local_discard_key(key)

        def _on_done(future, _pid=project_id, _rid=run_id, _att=attempt, _hist=attempt_history, _key=key):
            try:
                success, error_detail = future.result()
                if success:
                    _queue_rt.bump_processed()
                else:
                    _handle_failed_job(
                        project_id=_pid,
                        run_id=_rid,
                        attempt=_att,
                        last_error=error_detail,
                        prior_attempt_history=_hist,
                        backend="local",
                    )
            except Exception as exc:
                _handle_failed_job(
                    project_id=_pid,
                    run_id=_rid,
                    attempt=_att,
                    last_error=str(exc),
                    prior_attempt_history=_hist,
                    backend="local",
                )
            finally:
                _queue_rt.local_discard_key(_key)
                with _active_futures_lock:
                    _active_futures.discard(future)

        future = executor.submit(_execute_run_job, project_id, run_id, job)
        with _active_futures_lock:
            _active_futures.add(future)
        future.add_done_callback(_on_done)


def run_redis_worker_loop() -> None:
    """Blocking worker loop for distributed queue consumers."""
    _queue_rt.run_redis_consumer_loop(_execute_run_job, _handle_failed_job)


def queue_runtime_stats() -> dict[str, Any]:
    return _queue_rt.queue_runtime_stats()


def list_worker_heartbeats() -> list[dict[str, Any]]:
    return _queue_rt.list_worker_heartbeats()


def _record_dead_letter(item: dict[str, Any]) -> dict[str, Any]:
    return _queue_rt.record_dead_letter(item)


def list_dead_letter_items(*, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    return _queue_rt.list_dead_letter_items(project_id=project_id, limit=limit)


def replay_dead_letter_item(item_id: str) -> dict[str, Any] | None:
    client = _queue_rt.get_redis_client() if _queue_rt.queue_backend == "redis" else None
    replayable = RunQueueRuntime.REPLAYABLE_DEAD_LETTER_REASONS
    if client is not None:
        key = f"{_queue_rt.redis_dead_letter_item_prefix}:{item_id}"
        raw = client.get(key)
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            payload = parsed if isinstance(parsed, dict) else None
        except Exception as exc:
            _log.warning("%s: suppressed error: %s", 'replay_dead_letter_item', exc)
            return None
        if payload is None:
            return None
        if str(payload.get("status")) != "open":
            payload["replay_blocked_reason"] = "not_open"
            return payload
        if str(payload.get("reason")) not in replayable:
            payload["replay_blocked_reason"] = "reason_not_replayable"
            return payload
        attempts = int(payload.get("replay_attempts") or 0)
        max_attempts = int(payload.get("max_replay_attempts") or _queue_rt.dead_letter_max_replay_attempts)
        cooldown_until = int(payload.get("replay_cooldown_until_ms") or 0)
        if cooldown_until > int(time.time() * 1000):
            payload["replay_blocked_reason"] = "replay_cooldown_active"
            return payload
        if attempts >= max_attempts:
            payload["replay_blocked_reason"] = "max_replay_attempts_exceeded"
            return payload
        project_id = str(payload.get("project_id") or "")
        run_id = str(payload.get("run_id") or "")
        payload["replay_attempts"] = attempts + 1
        if project_id and run_id:
            enqueue_run_execution(project_id, run_id)
        payload["status"] = "replayed"
        payload["replayed_at_ms"] = int(time.time() * 1000)
        client.set(key, json.dumps(payload))
        return payload

    payload = _queue_rt.dead_letter_local.get(item_id)
    if not payload:
        return None
    if str(payload.get("status")) != "open":
        payload["replay_blocked_reason"] = "not_open"
        return payload
    if str(payload.get("reason")) not in replayable:
        payload["replay_blocked_reason"] = "reason_not_replayable"
        return payload
    attempts = int(payload.get("replay_attempts") or 0)
    max_attempts = int(payload.get("max_replay_attempts") or _queue_rt.dead_letter_max_replay_attempts)
    cooldown_until = int(payload.get("replay_cooldown_until_ms") or 0)
    if cooldown_until > int(time.time() * 1000):
        payload["replay_blocked_reason"] = "replay_cooldown_active"
        return payload
    if attempts >= max_attempts:
        payload["replay_blocked_reason"] = "max_replay_attempts_exceeded"
        return payload
    project_id = str(payload.get("project_id") or "")
    run_id = str(payload.get("run_id") or "")
    payload["replay_attempts"] = attempts + 1
    if project_id and run_id:
        enqueue_run_execution(project_id, run_id)
    payload["status"] = "replayed"
    payload["replayed_at_ms"] = int(time.time() * 1000)
    _queue_rt.dead_letter_local[item_id] = payload
    return payload


def reset_dead_letter_attempts(item_id: str, *, actor: str | None = None) -> dict[str, Any] | None:
    client = _queue_rt.get_redis_client() if _queue_rt.queue_backend == "redis" else None
    if client is not None:
        key = f"{_queue_rt.redis_dead_letter_item_prefix}:{item_id}"
        raw = client.get(key)
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except Exception as exc:
            _log.warning("%s: suppressed error: %s", 'reset_dead_letter_attempts', exc)
            return None
        if not isinstance(payload, dict):
            return None
        payload["replay_attempts"] = 0
        payload["status"] = "open"
        payload["replay_blocked_reason"] = None
        payload["attempts_reset_at_ms"] = int(time.time() * 1000)
        if actor:
            payload["attempts_reset_by"] = actor
        client.set(key, json.dumps(payload))
        return payload

    payload = _queue_rt.dead_letter_local.get(item_id)
    if not payload:
        return None
    payload["replay_attempts"] = 0
    payload["status"] = "open"
    payload["replay_blocked_reason"] = None
    payload["attempts_reset_at_ms"] = int(time.time() * 1000)
    if actor:
        payload["attempts_reset_by"] = actor
    _queue_rt.dead_letter_local[item_id] = payload
    return payload


def _handle_failed_job(
    *,
    project_id: str,
    run_id: str,
    attempt: int,
    last_error: str | None,
    prior_attempt_history: list[dict[str, Any]] | None,
    backend: str,
) -> None:
    next_attempt = attempt + 1
    now_ms = int(time.time() * 1000)
    history_item: dict[str, Any] = {
        "attempt": next_attempt,
        "failed_at_ms": now_ms,
        "error": (last_error or "unknown_error")[:500],
        "backend": backend,
    }
    history = [*(prior_attempt_history or []), history_item]
    retry_mode = classify_retry_mode(
        retry_after_sec=None,
        cooldown_threshold_sec=float(settings.retry_cooldown_threshold_sec),
    )
    max_attempts = _queue_rt.execution_retry_max_attempts
    if bool(settings.run_retry_indefinite_for_scheduled):
        max_attempts = max(max_attempts, 999999)
    if next_attempt <= max_attempts:
        if not validate_retry_transition("executing", "scheduled"):
            increment("retry_transition_invalid_total")
            _record_dead_letter(
                {
                    "project_id": project_id,
                    "run_id": run_id,
                    "reason": "retry_transition_invalid",
                    "payload": {"current_state": "executing", "next_state": "scheduled"},
                }
            )
            return
        delay_sec = compute_rate_limit_backoff(
            retry_after_sec=None,
            attempt=attempt,
            base_sec=_queue_rt.execution_retry_backoff_base_sec,
            max_sec=_queue_rt.execution_retry_backoff_max_sec,
        )
        increment("run_execution_retry_scheduled_total")
        if backend == "redis":
            client = _queue_rt.get_redis_client()
            if client is not None:
                retry_payload = {
                    "project_id": project_id,
                    "run_id": run_id,
                    "attempt": next_attempt,
                    "enqueued_at_ms": int(time.time() * 1000),
                    "retry_mode": retry_mode,
                    "retry_state": "scheduled",
                    "attempt_history": history,
                }
                _queue_rt.schedule_redis_retry(delay_sec, retry_payload)
                return
        else:
            job = {
                "project_id": project_id,
                "run_id": run_id,
                "attempt": next_attempt,
                "enqueued_at_ms": int(time.time() * 1000),
                "retry_mode": retry_mode,
                "retry_state": "scheduled",
                "attempt_history": history,
            }
            _queue_rt.schedule_local_retry(delay_sec, project_id, run_id, job)
            return
    _record_dead_letter(
        {
            "project_id": project_id,
            "run_id": run_id,
            "reason": "execution_failed",
            "payload": {"error": (last_error or "unknown_error")[:400]},
            "last_error": (last_error or "unknown_error")[:1000],
            "error_class": "execution_exception",
            "final_attempt": next_attempt,
            "retry_policy": {
                "max_attempts": max_attempts,
                "base_backoff_sec": _queue_rt.execution_retry_backoff_base_sec,
                "max_backoff_sec": _queue_rt.execution_retry_backoff_max_sec,
            },
            "retry_mode": "retry_exhausted_dead_letter",
            "attempt_history": history,
            "replay_cooldown_until_ms": now_ms + (_queue_rt.dead_letter_replay_cooldown_sec * 1000),
        }
    )
    increment("run_execution_retry_exhausted_total")


def _write_token_usage(run: Run, usage: dict[str, int], cost: float | None) -> None:
    """Write accumulated token counts and cost to the Run row. Best-effort — never raises."""
    if not usage:
        return
    try:
        run.tokens_input = usage.get("input_tokens", 0)
        run.tokens_output = usage.get("output_tokens", 0)
        run.tokens_cache_read = usage.get("cache_read_tokens", 0)
        run.tokens_cache_creation = usage.get("cache_creation_tokens", 0)
        run.cost_usd = cost
    except Exception as _exc:
        _log.warning("Failed to set token usage on run %s: %s", getattr(run, "id", "?"), _exc)


def _execute_run_job(
    project_id: str,
    run_id: str,
    queue_payload: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    started_at = perf_counter()
    _run_usage: dict[str, int] = {}
    _run_cost: float | None = None
    session = SessionLocal()
    try:
        run = session.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
        if not run:
            return True, None
        qpayload = queue_payload if isinstance(queue_payload, dict) else {}
        rs = str(qpayload.get("retry_state") or "").strip().lower()
        if rs == "scheduled" and not validate_retry_transition("scheduled", "executing"):
            increment("retry_transition_invalid_total")
            append_run_event(
                session,
                run_id,
                "retry_watchdog",
                {"reason": "retry_transition_invalid", "from": "scheduled", "to": "executing"},
            )
            session.commit()
            return False, "retry_transition_invalid"
        try:
            _pp = json.loads(run.plan_payload) if run.plan_payload else {}
        except Exception:
            _pp = {}
        _control = _pp.get("control_state") if isinstance(_pp, dict) and isinstance(_pp.get("control_state"), dict) else {}
        if bool(_control.get("abort_requested")) or bool(run.abort_requested):
            run.status = "failed"
            run.error_message = "Aborted via persisted control_state before execution."
            session.commit()
            append_run_event(session, run_id, "run_aborted", {"reason": "persisted_abort_requested"})
            session.commit()
            return False, run.error_message
        try:
            requested_for_gate = json.loads(run.output_types) if run.output_types else []
        except json.JSONDecodeError:
            requested_for_gate = []
        try:
            plan_payload_obj = json.loads(run.plan_payload) if run.plan_payload else {}
        except Exception:
            plan_payload_obj = {}
        workspace_ready = bool(workspace_path(project_id).exists())
        # Keep human approval sticky across remediation/retry cycles:
        # once a run has approved_by set, permission evaluation should not
        # regress purely because an intermediate attempt marked status=failed.
        effective_run_status = "approved" if run.approved_by else str(run.status or "")
        gate_decisions = evaluate_permission_pipeline(
            run_status=effective_run_status,
            has_approval=bool(run.approved_by),
            requested_outputs=requested_for_gate if isinstance(requested_for_gate, list) else [],
            workspace_ready=workspace_ready,
            classifier_score=1.0,
            classifier_threshold=float(settings.policy_classifier_threshold),
            enforce_policy=bool(settings.policy_enforce_enabled),
            plan_payload=plan_payload_obj if isinstance(plan_payload_obj, dict) else None,
            agentic_loop_enabled=bool(settings.coordinator_agentic_loop_enabled),
        )
        for d in gate_decisions:
            append_run_event(
                session,
                run_id,
                "permission_stage",
                {
                    "stage": d.stage,
                    "allowed": d.allowed,
                    "code": d.code,
                    "reason": d.reason,
                    "metadata": d.metadata or {},
                    "warnings": d.warnings or [],
                },
            )
        if any(not d.allowed for d in gate_decisions):
            run.status = "failed"
            run.error_message = "permission_pipeline_denied"
            session.commit()
            append_run_event(session, run_id, "failed", {"error": run.error_message})
            session.commit()
            return False, run.error_message
        if run.status == "approved":
            was_resume_requested = bool(run.resume_requested)
            run.status = "running"
            run.pause_requested = False
            run.resume_requested = False
            session.commit()
            if was_resume_requested:
                resume_state = _run_event_service.load_resume_state(session, run_id=run_id)
                append_run_event(session, run_id, "resume_state_loaded", resume_state)
            append_run_event(session, run_id, "step", {"status": "execution_started"})
            append_run_event(session, run_id, "heartbeat", heartbeat_event(run_id=run_id, phase="execution_started"))
            session.commit()
        elif run.status in {"done", "failed"}:
            return True, None
        try:
            sync_disabled_hooks_from_db(session, project_id=project_id)
            pre_hooks = run_hooks_sync(
                "pre_run_execution",
                {"project_id": project_id, "run_id": run_id, "instruction": run.instruction},
                project_id=project_id,
            )
            for h in pre_hooks:
                hxid = hook_exec_id(run_id=run_id, hook_point="pre_run_execution", hook_name=h.hook_name)
                if hook_execution_exists(session, run_id=run_id, hook_exec_id_value=hxid):
                    continue
                append_run_event(
                    session,
                    run_id,
                    "hook_result",
                    {
                        "hook_exec_id": hxid,
                        "hook_point": "pre_run_execution",
                        "hook_name": h.hook_name,
                        "outcome": h.outcome,
                        "message": h.message,
                    },
                )
                record_hook_execution(
                    session,
                    run_id=run_id,
                    hook_point="pre_run_execution",
                    hook_name=h.hook_name,
                    hook_exec_id_value=hxid,
                    idempotency_key=hxid,
                    outcome=h.outcome,
                )
                if h.outcome == "ABORT":
                    run.status = "failed"
                    run.error_message = f"pre_run_hook_abort:{h.hook_name}"
                    session.commit()
                    append_run_event(session, run_id, "failed", {"error": run.error_message})
                    session.commit()
                    return False, run.error_message
            # Checkpoint before generation
            session.refresh(run)
            if run.abort_requested:
                append_run_event(session, run_id, "run_control_applied", {"action": "abort", "checkpoint": "before_generation"})
                run.status = "failed"
                run.error_message = "Aborted before generation."
                session.commit()
                return False, run.error_message
            record_run_trace("run_execution_started", project_id=project_id, run_id=run_id)
            langfuse_span(
                trace_id=run_id,
                name="run.execution",
                input_payload={"project_id": project_id, "instruction": run.instruction[:500]},
            )
            coord = Coordinator()
            try:
                requested = json.loads(run.output_types) if run.output_types else []
            except json.JSONDecodeError:
                requested = []

            qa_threshold = 0.8
            max_qa_loops = 2
            hard_gate_enabled = True
            output_type_representations: dict[str, str] = {}
            format_v2_enabled = settings.format_negotiation_v2_enabled
            if format_v2_enabled and run.plan_payload:
                try:
                    plan = json.loads(run.plan_payload)
                    if isinstance(plan, dict) and isinstance(plan.get("output_type_representations"), dict):
                        output_type_representations = {
                            str(k): str(v)
                            for k, v in plan.get("output_type_representations", {}).items()
                        }
                except Exception:
                    output_type_representations = {}
            settings_path = workspace_path(project_id) / "settings.json"
            if settings_path.exists():
                try:
                    settings_data = json.loads(settings_path.read_text(encoding="utf-8"))
                    if isinstance(settings_data, dict) and "qa_threshold" in settings_data:
                        qa_threshold = float(settings_data["qa_threshold"])
                    if isinstance(settings_data, dict) and "max_qa_loops" in settings_data:
                        max_qa_loops = max(1, min(5, int(settings_data["max_qa_loops"])))
                    if isinstance(settings_data, dict) and "hard_gate_enabled" in settings_data:
                        hard_gate_enabled = bool(settings_data["hard_gate_enabled"])
                except Exception:
                    qa_threshold = 0.8
            try:
                plan_payload_obj = json.loads(run.plan_payload) if run.plan_payload else {}
                if not isinstance(plan_payload_obj, dict):
                    plan_payload_obj = {}
            except Exception:
                plan_payload_obj = {}
            conv_id: str | None = None
            _raw_cid = plan_payload_obj.get("conversation_id")
            if isinstance(_raw_cid, str) and _raw_cid.strip():
                conv_id = _raw_cid.strip()
            digest = ""
            digest_trace_payload: dict[str, Any] | None = None
            if conv_id:
                digest, digest_trace = build_conversation_digest_for_run_with_trace(
                    session=session,
                    project_id=project_id,
                    conversation_id=conv_id,
                    char_cap=settings.conversation_digest_max_chars,
                    message_limit=settings.conversation_digest_message_limit,
                )
                if digest:
                    increment("conversation_digest_built_total")
                if digest_trace.tiers_applied:
                    increment("conversation_digest_tiered_compaction_total")
                digest_trace_payload = {
                    "conversation_id": conv_id,
                    "char_cap": int(settings.conversation_digest_max_chars),
                    "message_limit": int(settings.conversation_digest_message_limit),
                    "trace": digest_trace.to_dict(),
                }
                append_run_event(session, run_id, "context_trace", {"conversation_digest": digest_trace_payload})
                record_run_trace(
                    "conversation_digest_trace",
                    project_id=project_id,
                    run_id=run_id,
                    extra={"tiers_applied": list(digest_trace.tiers_applied), "final_char_count": digest_trace.final_char_count},
                )
            inp = CoordinatorRunInput(
                raw_text=run.instruction or "",
                user_instruction=run.instruction or "",
                requested_outputs=requested,
                project_id=project_id,
                run_id=run_id,
                plan_payload=plan_payload_obj,
                dpdp_flags={"enabled": True},
                qa_threshold=qa_threshold,
                max_qa_loops=max_qa_loops,
                output_type_representations=output_type_representations,
                user_id=run.approved_by if run.approved_by else None,
            )
            init_state = inp.to_initial_state()
            if digest:
                init_state["conversation_digest"] = digest

            _timeout_sec = int(getattr(settings, "run_stuck_timeout_sec", 0) or 0)
            _deadline = perf_counter() + _timeout_sec if _timeout_sec > 0 else None
            _timeout_tripped = {"v": False}

            def _abort_check() -> bool:
                # Wall-clock deadline first: a slow-but-yielding coordinator self-terminates
                # via the existing RunAborted path (emitted as execution_timeout below).
                if _deadline is not None and perf_counter() >= _deadline:
                    _timeout_tripped["v"] = True
                    return True
                session.refresh(run)
                return bool(run.abort_requested)

            async def _consume_coordinator() -> dict[str, Any]:
                final_state: dict[str, Any] = {}
                async for ev in coord.coordinate(init_state, abort_check=_abort_check):
                    et = str(ev.get("event_type") or "")
                    payload = ev.get("payload")
                    if et == "coordinator_state" and isinstance(payload, dict):
                        state_obj = payload.get("state")
                        if isinstance(state_obj, dict):
                            final_state = state_obj
                        continue
                    append_run_event(
                        session,
                        run_id,
                        et or "step",
                        payload if isinstance(payload, dict) else {"value": str(payload)},
                    )
                return final_state

            def _run_coordinator_async() -> dict[str, Any]:
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    return asyncio.run(_consume_coordinator())

                result_holder: dict[str, Any] = {}
                err_holder: dict[str, BaseException] = {}

                def _runner() -> None:
                    try:
                        result_holder["value"] = asyncio.run(_consume_coordinator())
                    except BaseException as exc:
                        err_holder["error"] = exc

                _ctx_copy = contextvars.copy_context()
                t = threading.Thread(target=_ctx_copy.run, args=(_runner,), daemon=True)
                t.start()
                t.join()
                if "error" in err_holder:
                    raise err_holder["error"]
                return result_holder.get("value", {})

            try:
                with project_token_context(project_id), run_llm_budget(int(settings.anthropic_max_tokens_per_run or 0), run_id=run_id):
                    try:
                        with start_span(
                            "run.coordinator",
                            attributes={"project_id": project_id, "run_id": run_id},
                        ):
                            state = _run_coordinator_async()
                    finally:
                        _run_usage = get_run_usage()
                        _run_cost = calculate_run_cost_usd(**_run_usage)
            except RunAborted:
                session.refresh(run)
                if _timeout_tripped["v"]:
                    append_run_event(
                        session,
                        run_id,
                        "execution_timeout",
                        {"timeout_sec": _timeout_sec, "checkpoint": "during_generation"},
                    )
                    run.error_message = f"Execution timed out after {_timeout_sec}s without completing."
                else:
                    append_run_event(
                        session,
                        run_id,
                        "run_control_applied",
                        {"action": "abort", "checkpoint": "during_generation"},
                    )
                    run.error_message = "Aborted during generation."
                _write_token_usage(run, _run_usage, _run_cost)
                run.status = "failed"
                session.commit()
                return False, run.error_message
            except RunBudgetExceeded as budget_exc:
                session.refresh(run)
                append_run_event(
                    session,
                    run_id,
                    "failed",
                    {"error": "run_token_budget_exhausted", "detail": str(budget_exc)[:500]},
                )
                _write_token_usage(run, _run_usage, _run_cost)
                run.status = "failed"
                run.error_message = str(budget_exc)[:2000]
                session.commit()
                return False, str(budget_exc)
            for _rep_key, _rep_model in (("qa_report", QaReportDoc), ("guardrail_report", GuardrailReportDoc)):
                _raw_rep = state.get(_rep_key)
                if isinstance(_raw_rep, dict):
                    with contextlib.suppress(Exception):
                        state[_rep_key] = _rep_model.model_validate(_raw_rep).model_dump()
            session.refresh(run)
            if run.abort_requested:
                append_run_event(session, run_id, "run_control_applied", {"action": "abort", "checkpoint": "after_generation"})
                run.status = "failed"
                run.error_message = "Aborted after generation."
                session.commit()
                return False, run.error_message
            run_todos = list(state.get("run_todos") or [])
            if run_todos:
                _emit_and_sync_todo_snapshot(
                    session,
                    project_id=project_id,
                    run_id=run_id,
                    run_todos=run_todos,
                )
            langfuse_span(
                trace_id=run_id,
                name="coordinator.run",
                output_payload={
                    "has_qa_report": isinstance(state.get("qa_report"), dict),
                    "has_guardrail_report": isinstance(state.get("guardrail_report"), dict),
                },
            )
            expected_missing: list[str] = []
            if "process_map" in requested:
                process_pref = output_type_representations.get("process_map", "drawio_xml")
                if process_pref == "mermaid":
                    if not isinstance(state.get("process_map_mermaid"), str) or not str(state.get("process_map_mermaid")).strip():
                        expected_missing.append("process_map_mermaid")
                else:
                    if not isinstance(state.get("drawio_xml"), str) or not str(state.get("drawio_xml")).strip():
                        expected_missing.append("drawio_xml")
            if "raci" in requested:
                raci_pref = output_type_representations.get("raci", "html")
                if raci_pref == "markdown":
                    if not isinstance(state.get("raci_markdown"), str) or not str(state.get("raci_markdown")).strip():
                        expected_missing.append("raci_markdown")
                elif raci_pref == "xlsx":
                    # XLSX is derived from tabular RACI source in storage layer; ensure source exists.
                    if not (
                        (isinstance(state.get("raci_markdown"), str) and str(state.get("raci_markdown")).strip())
                        or (isinstance(state.get("raci_html"), str) and str(state.get("raci_html")).strip())
                    ):
                        expected_missing.append("raci_xlsx_source")
                else:
                    if not isinstance(state.get("raci_html"), str) or not str(state.get("raci_html")).strip():
                        expected_missing.append("raci_html")
            if expected_missing:
                if run_todos:
                    for row in run_todos:
                        if str(row.get("id") or "").startswith("out:"):
                            row["status"] = "failed"
                    todo_set_status(run_todos, "finalize", "failed")
                    _emit_and_sync_todo_snapshot(
                        session,
                        project_id=project_id,
                        run_id=run_id,
                        run_todos=run_todos,
                    )
                append_run_event(
                    session,
                    run_id,
                    "qa_report",
                    {"passed": False, "reason": "expected_output_missing", "missing_outputs": expected_missing},
                )
                run.status = "failed"
                run.error_message = f"Expected output missing: {', '.join(expected_missing)}"
                session.commit()
                append_run_event(session, run_id, "failed", {"error": run.error_message})
                session.commit()
                increment("run_failed_total")
                observe_latency("run_execution", (perf_counter() - started_at) * 1000.0)
                record_run_trace(
                    "run_execution_failed",
                    project_id=project_id,
                    run_id=run_id,
                    extra={"error": run.error_message[:200]},
                )
                return False, run.error_message
            append_run_event(
                session,
                run_id,
                "skill_selection",
                state.get("skill_card") or {},
            )
            save_run_artifacts(project_id, run_id, state)

            run_dir = workspace_path(project_id) / "runs" / run_id
            final_artifact_report: dict[str, Any] = {}
            if settings.final_artifact_qa_enabled:
                from app.services.final_artifact_qa import verify_final_artifacts, write_final_artifact_qa

                try:
                    final_artifact_report = verify_final_artifacts(
                        run_dir,
                        qa_report=state.get("qa_report") if isinstance(state.get("qa_report"), dict) else {},
                        guardrail_report=state.get("guardrail_report")
                        if isinstance(state.get("guardrail_report"), dict)
                        else {},
                        remediation_notes=str(state.get("qa_remediation_notes") or ""),
                    )
                    write_final_artifact_qa(run_dir, final_artifact_report)
                    langfuse_span(
                        trace_id=str(project_id),
                        name="final_artifact_qa",
                        input_payload={"run_id": run_id},
                        output_payload={
                            "passed": bool(final_artifact_report.get("passed")),
                            "issues": final_artifact_report.get("issues") or [],
                        },
                    )
                except Exception as exc:
                    _log.warning("final_artifact_qa failed for run %s: %s", run_id, exc)
                if (
                    isinstance(final_artifact_report, dict)
                    and not final_artifact_report.get("passed")
                    and isinstance(state.get("qa_report"), dict)
                ):
                    qa_state = dict(state["qa_report"])
                    qa_state["remediation_converged"] = False
                    qa_state["final_artifact_qa_failed"] = True
                    state["qa_report"] = qa_state

            # Stream output chunks after generation completes (coarse-grained chunking for now).
            raci_pref = output_type_representations.get("raci")
            if raci_pref in {"markdown", "xlsx"}:
                raci_chunk = state.get("raci_markdown", "")
            else:
                raci_chunk = state.get("raci_html", "")
            process_chunk = state.get("process_map_mermaid", "") if output_type_representations.get("process_map") == "mermaid" else state.get("drawio_xml", "")
            output_chunks = [
                ("narrative", state.get("narrative_md", "")),
                ("raci", raci_chunk),
                ("sop", state.get("sop_markdown", "")),
                ("process_map", process_chunk),
            ]
            for output_type, text in output_chunks:
                if not isinstance(text, str) or not text.strip():
                    continue
                chunk_size = 600
                chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
                for idx, chunk in enumerate(chunks):
                    append_run_event(
                        session,
                        run_id,
                        "output_chunk",
                        {
                            "output_type": output_type,
                            "chunk_index": idx,
                            "chunk_total": len(chunks),
                            "chunk": chunk,
                        },
                    )
            if run_todos:
                todo_set_status(run_todos, "visual_qa", "running")
                _emit_and_sync_todo_snapshot(
                    session,
                    project_id=project_id,
                    run_id=run_id,
                    run_todos=run_todos,
                )
            visual_qa_report = run_visual_quality_check(project_id, run_id, run_dir)
            if isinstance(visual_qa_report, dict):
                visual_qa_report = _augment_visual_qa_with_render_hints(visual_qa_report, run_dir)
                visual_qa_report = _augment_visual_qa_with_design_review(visual_qa_report, run_dir)
                _persist_pptx_visual_critic_signals(run_dir, visual_qa_report)
            save_visual_qa_report(run_dir, visual_qa_report)
            try:
                unified_reports_for_narrative = state.get("unified_quality_reports")
                if isinstance(unified_reports_for_narrative, dict):
                    narrative_signals = extract_narrative_signals(unified_reports_for_narrative)
                    if narrative_signals:
                        persist_narrative_signals(run_dir, narrative_signals)
            except Exception as exc:
                _log.warning("narrative_feedback persist failed for run %s: %s", run_id, exc)
            guardrail_report = state.get("guardrail_report") if isinstance(state.get("guardrail_report"), dict) else {}
            (run_dir / "guardrail_report.json").write_text(json.dumps(guardrail_report, indent=2), encoding="utf-8")
            for gate_event in guardrail_report.get("guardrail_events") or []:
                append_run_event(session, run_id, "guardrail_event", gate_event)
            append_run_event(session, run_id, "visual_qa_report", visual_qa_report)
            if run_todos:
                todo_set_status(run_todos, "visual_qa", "done")
                _emit_and_sync_todo_snapshot(
                    session,
                    project_id=project_id,
                    run_id=run_id,
                    run_todos=run_todos,
                )
            if isinstance(visual_qa_report, dict):
                try:
                    proj_row = session.scalar(select(Project).where(Project.id == project_id))
                    recipient_ids = {uid for uid in (run.approved_by, proj_row.created_by if proj_row else None) if uid}
                    for uid in recipient_ids:
                        persist_visual_qa_assistant_message(
                            session,
                            project_id=project_id,
                            user_id=uid,
                            run_id=run_id,
                            report=visual_qa_report,
                        )
                except Exception as exc:
                    _log.warning(
                        "persist_visual_qa_assistant_message failed for run %s: %s",
                        run_id,
                        exc,
                        exc_info=True,
                    )
            append_run_event(session, run_id, "qa_report", state.get("qa_report") or {})
            append_run_event(session, run_id, "guardrail_report", guardrail_report)
            append_memory_event(
                session,
                project_id=project_id,
                run_id=run_id,
                event_type="qa_outcome",
                payload_obj={
                    "summary": "pass" if (state.get("qa_report") or {}).get("passed") else "fail",
                    "scores": (state.get("qa_report") or {}).get("scores"),
                },
            )
            if (state.get("qa_report") or {}).get("remediation_applied"):
                append_memory_event(
                    session,
                    project_id=project_id,
                    run_id=run_id,
                    event_type="qa_remediation",
                    payload_obj={
                        "summary": "qa remediation applied",
                        "converged": bool((state.get("qa_report") or {}).get("remediation_converged")),
                    },
                )
            append_memory_event(
                session,
                project_id=project_id,
                run_id=run_id,
                event_type="guardrail_outcome",
                payload_obj={
                    "summary": str(guardrail_report.get("status") or "unknown"),
                },
            )
            snapshot = state.get("compaction_snapshot")
            if isinstance(snapshot, dict):
                increment("context_compaction_runs_total")
                section_sizes = snapshot.get("section_sizes")
                dropped = snapshot.get("dropped_items")
                if isinstance(section_sizes, dict):
                    set_gauge("context_sections_chars", float(sum(int(v or 0) for v in section_sizes.values())))
                    for section, size in section_sizes.items():
                        set_gauge(f"context_sections_chars_{section.lower()}", float(size or 0))
                if isinstance(dropped, dict):
                    dropped_total = float(sum(int(v or 0) for v in dropped.values()))
                    kept_total = float(
                        sum(int(v or 0) for v in (section_sizes.values() if isinstance(section_sizes, dict) else []))
                    )
                    if kept_total > 0:
                        set_gauge("context_compaction_drop_ratio", dropped_total / max(1.0, kept_total))

            with start_span(
                "run.evaluator_pipeline",
                attributes={"project_id": project_id, "run_id": run_id},
            ):
                evidence_gate = _pptx_evidence_gate_from_run_dir(run_dir)
                evaluator_pipeline = _build_evaluator_pipeline(
                    requested_outputs=requested,
                    plan_payload=plan_payload_obj,
                    qa_report=state.get("qa_report") if isinstance(state.get("qa_report"), dict) else {},
                    visual_qa_report=visual_qa_report if isinstance(visual_qa_report, dict) else {},
                    guardrail_report=guardrail_report if isinstance(guardrail_report, dict) else {},
                    final_artifact_report=final_artifact_report if isinstance(final_artifact_report, dict) else {},
                    evidence_gate=evidence_gate,
                )
            append_run_event(session, run_id, "evaluator_pipeline", evaluator_pipeline)
            if hard_gate_enabled and evaluator_pipeline["status"] != "pass":
                prior_retry_count = int(
                    session.scalar(
                        select(func.count()).select_from(RunEvent).where(
                            RunEvent.run_id == run_id, RunEvent.event_type == "evaluator_retry_requested"
                        )
                    )
                    or 0
                )
                if prior_retry_count < MAX_EVALUATOR_REMEDIATION_ROUNDS:
                    run.status = "approved"
                    nxt = prior_retry_count + 1
                    fallback_applied = should_apply_fallback(consecutive_failures=nxt, threshold=3)
                    state["fallback_applied"] = bool(fallback_applied)
                    run.error_message = (
                        f"Evaluator checks failed; auto-remediation {nxt}/{MAX_EVALUATOR_REMEDIATION_ROUNDS}."
                    )
                    # ── Inject per-artifact visual feedback into plan_payload so each
                    # agent receives targeted remediation hints on the retry pass.
                    # Mapping: per_artifact key → plan_payload key that agent reads.
                    _hint_map = {
                        "pptx":        "pptx_visual_feedback",
                        "docx":        "docx_visual_feedback",
                        "xlsx":        "xlsx_visual_feedback",
                        "pdf":         "pdf_visual_feedback",
                        "process_map": "process_map_visual_feedback",
                    }
                    per_artifact = (visual_qa_report or {}).get("per_artifact") or {}
                    # Backward-compat: also honour top-level pptx_assessment
                    if "pptx" not in per_artifact:
                        pptx_top = (visual_qa_report or {}).get("pptx_assessment")
                        if pptx_top:
                            per_artifact = dict(per_artifact, pptx=pptx_top)
                    hints_injected: dict[str, int] = {}
                    findings_excerpt: list[str] = []
                    raw_findings = (visual_qa_report or {}).get("findings") or []
                    if isinstance(raw_findings, list):
                        findings_excerpt = [
                            str(x).strip() for x in raw_findings[:20] if str(x).strip()
                        ]
                    try:
                        retry_plan = json.loads(run.plan_payload) if run.plan_payload else {}
                        if not isinstance(retry_plan, dict):
                            retry_plan = {}
                        for artifact_key, payload_key in _hint_map.items():
                            assessment = per_artifact.get(artifact_key)
                            if not isinstance(assessment, dict):
                                continue
                            st = str(assessment.get("status") or "").lower()
                            if st in {"pass", "skip"}:
                                continue
                            hints = assessment.get("remediation_hints") or []
                            if not hints:
                                continue
                            retry_plan[payload_key] = hints
                            hints_injected[artifact_key] = len(hints)
                        # Evidence hard-fail: inject per-slide unsupported-claim fixes so the
                        # PPTX agent can remove or re-source fabricated numbers on retry.
                        if evidence_gate.get("hard_fail"):
                            evidence_hints = evidence_gate.get("remediation_hints") or []
                            if evidence_hints:
                                prior_pptx_hints = retry_plan.get("pptx_visual_feedback")
                                merged_evidence = (
                                    list(prior_pptx_hints)
                                    if isinstance(prior_pptx_hints, list)
                                    else []
                                )
                                merged_evidence.extend(evidence_hints)
                                retry_plan["pptx_visual_feedback"] = merged_evidence
                                hints_injected["pptx_evidence"] = len(evidence_hints)
                            prior_regen = str(retry_plan.get("regeneration_directive") or "").strip()
                            evidence_directive = (
                                "Evidence hard-fail remediation required. Remove unsupported "
                                "numeric claims or replace them with values present in retrieved "
                                "client source documents, and cite Source: <filename, sheet/page>."
                            )
                            retry_plan["regeneration_directive"] = (
                                f"{prior_regen}\n\n{evidence_directive}".strip()
                                if prior_regen
                                else evidence_directive
                            )
                            hints_injected.setdefault(
                                "pptx_evidence",
                                int(evidence_gate.get("unsupported_claims_count") or 1),
                            )
                        # Narrative coherence feedback: mirror pptx_visual_feedback
                        # by loading persisted narrative_signals.json (or deriving from
                        # unified_quality_reports) and injecting per-output hints for
                        # docx/pdf subagents to consume on retry. Fail-open.
                        try:
                            narrative_signals = narrative_signals_from_run_dir(run_dir)
                            if not narrative_signals:
                                unified_reports_for_narrative = state.get("unified_quality_reports")
                                if isinstance(unified_reports_for_narrative, dict):
                                    narrative_signals = extract_narrative_signals(
                                        unified_reports_for_narrative
                                    )
                            for narrative_output in ("docx", "pdf"):
                                narrative_hints = build_narrative_feedback_hints(
                                    narrative_signals, narrative_output
                                )
                                if not narrative_hints:
                                    continue
                                narrative_key = f"{narrative_output}_narrative_feedback"
                                retry_plan[narrative_key] = narrative_hints
                                hints_injected[narrative_key] = len(narrative_hints)
                            # Also surface narrative arc issues to the PPTX agent so it can
                            # tighten slide titles and story flow on retry.
                            _pptx_narrative_src = next(
                                (
                                    t for t in ("docx", "pdf")
                                    if isinstance(narrative_signals.get(t), dict)
                                    and not narrative_signals[t].get("passed")
                                ),
                                None,
                            )
                            if _pptx_narrative_src:
                                _pptx_narrative_hints = build_narrative_feedback_hints(
                                    narrative_signals, _pptx_narrative_src
                                )
                                if _pptx_narrative_hints:
                                    retry_plan["pptx_narrative_feedback"] = _pptx_narrative_hints
                                    hints_injected["pptx_narrative_feedback"] = len(_pptx_narrative_hints)
                        except Exception as narrative_exc:
                            _log.debug(
                                "narrative_feedback retry injection skipped for run %s: %s",
                                run_id,
                                narrative_exc,
                            )
                        # PPTX: keep prior slide JSON so the agent can patch only failing slides.
                        prior_path = run_dir / "pptx_slides.json"
                        if prior_path.exists():
                            try:
                                prior_slides = json.loads(prior_path.read_text(encoding="utf-8"))
                                if isinstance(prior_slides, list):
                                    retry_plan["prior_pptx_slides"] = prior_slides
                            except Exception:  # noqa: S110 — best-effort, non-fatal
                                pass
                        failed_gate = str((guardrail_report or {}).get("failed_gate") or "").strip()
                        if failed_gate:
                            guardrail_directive = _guardrail_regeneration_directive(guardrail_report)
                            prior_regen = str(retry_plan.get("regeneration_directive") or "").strip()
                            retry_plan["regeneration_directive"] = (
                                f"{prior_regen}\n\n{guardrail_directive}".strip()
                                if prior_regen
                                else guardrail_directive
                            )
                        if hints_injected or retry_plan.get("prior_pptx_slides") or failed_gate:
                            run.plan_payload = json.dumps(retry_plan)
                    except Exception:  # noqa: S110 — best-effort, non-fatal
                        pass
                    append_run_event(
                        session,
                        run_id,
                        "evaluator_retry_requested",
                        {
                            "reason": "pre_review_evaluator_failed",
                            "evaluator_pipeline": evaluator_pipeline,
                            "retry_index": nxt,
                            "max_remediation_rounds": MAX_EVALUATOR_REMEDIATION_ROUNDS,
                            "visual_hints_injected": hints_injected,
                            "findings_excerpt": findings_excerpt,
                            "visual_qa_summary": str((visual_qa_report or {}).get("summary") or ""),
                            "fallback_applied": bool(state.get("fallback_applied")),
                            "fallback_strategy": {
                                out: fallback_strategy_for_output(out) for out in requested
                            },
                            "retry_state": "scheduled",
                        },
                    )
                    session.commit()
                    enqueue_run_execution(project_id, run_id)
                    return True, None
                guardrails_only_failure = (
                    not evaluator_pipeline.get("guardrails_passed")
                    and evaluator_pipeline.get("qa_passed", True)
                    and evaluator_pipeline.get("visual_qa_passed", True)
                    and evaluator_pipeline.get("final_artifact_qa_passed", True)
                    and evaluator_pipeline.get("evidence_passed", True)
                )
                if guardrails_only_failure and getattr(settings, "guardrails_fail_open_enabled", False):
                    _write_token_usage(run, _run_usage, _run_cost)
                    run.status = "review_ready"
                    run.error_message = (
                        "Completed with guardrail failures — review recommended before distribution."
                    )
                    run.plan_payload = _strip_visual_remediation_from_plan(run.plan_payload)
                    session.commit()
                    append_run_event(
                        session,
                        run_id,
                        "completed_with_guardrail_failures",
                        {"evaluator_pipeline": evaluator_pipeline},
                    )
                    session.commit()
                    if run_todos:
                        todo_set_status(run_todos, "finalize", "done")
                        _emit_and_sync_todo_snapshot(
                            session,
                            project_id=project_id,
                            run_id=run_id,
                            run_todos=run_todos,
                        )
                    observe_latency("run_execution", (perf_counter() - started_at) * 1000.0)
                    return True, None

                run.status = "failed"
                if not evaluator_pipeline.get("evidence_passed", True):
                    unsupported = int(
                        ((evaluator_pipeline.get("evidence_gate") or {}).get("unsupported_claims_count")) or 0
                    )
                    run.error_message = (
                        f"Evidence hard-fail: {unsupported} unsupported numeric claim(s) in the PPTX "
                        f"after {MAX_EVALUATOR_REMEDIATION_ROUNDS} remediation attempt(s). "
                        "Replace fabricated figures with sourced client data or remove them."
                    )
                else:
                    run.error_message = (
                        f"Pre-review evaluator pipeline failed after {MAX_EVALUATOR_REMEDIATION_ROUNDS} "
                        "remediation attempt(s). See visual_qa_report and run events."
                    )
                session.commit()
                if run_todos:
                    todo_set_status(run_todos, "finalize", "failed")
                    _emit_and_sync_todo_snapshot(
                        session,
                        project_id=project_id,
                        run_id=run_id,
                        run_todos=run_todos,
                    )
                append_run_event(session, run_id, "failed", {"error": run.error_message, "evaluator_pipeline": evaluator_pipeline})
                session.commit()
                increment("run_failed_total")
                observe_latency("run_execution", (perf_counter() - started_at) * 1000.0)
                record_run_trace(
                    "run_execution_failed",
                    project_id=project_id,
                    run_id=run_id,
                    extra={"error": run.error_message[:200]},
                )
                return False, run.error_message

            _write_token_usage(run, _run_usage, _run_cost)
            run.status = "review_ready"
            run.error_message = None
            run.plan_payload = _strip_visual_remediation_from_plan(run.plan_payload)
            session.commit()
            if run_todos:
                todo_set_status(run_todos, "finalize", "running")
                _emit_and_sync_todo_snapshot(
                    session,
                    project_id=project_id,
                    run_id=run_id,
                    run_todos=run_todos,
                )
            append_run_event(session, run_id, "step", {"status": "review_ready"})
            append_run_event(session, run_id, "heartbeat", heartbeat_event(run_id=run_id, phase="review_ready"))
            if run_todos:
                todo_set_status(run_todos, "finalize", "done")
                _emit_and_sync_todo_snapshot(
                    session,
                    project_id=project_id,
                    run_id=run_id,
                    run_todos=run_todos,
                )
            artifact_summary = {
                "summary": (
                    f"Generated outputs: {', '.join([k for k in ['narrative_md', 'raci_html', 'raci_markdown', 'sop_markdown', 'drawio_xml', 'process_map_mermaid'] if state.get(k)])}"
                ),
                "fallback_applied": bool(state.get("fallback_applied")),
            }
            append_memory_event(
                session,
                project_id=project_id,
                run_id=run_id,
                event_type="artifact_summary",
                payload_obj=artifact_summary,
            )
            profile_obj = {
                "last_run_id": run_id,
                "non_negotiables": state.get("memory_summary", {}).get("non_negotiables", []),
                "recent_changes": state.get("memory_summary", {}).get("recent_changes", []),
            }
            proposal_discovery = state.get("proposal_discovery")
            if isinstance(proposal_discovery, dict):
                profile_obj["proposal_discovery"] = {
                    "client": proposal_discovery.get("client") if isinstance(proposal_discovery.get("client"), dict) else {},
                    "outcome": proposal_discovery.get("outcome") if isinstance(proposal_discovery.get("outcome"), dict) else {},
                    "audience": str(proposal_discovery.get("audience") or "").strip(),
                    "win_themes": proposal_discovery.get("win_themes") if isinstance(proposal_discovery.get("win_themes"), list) else [],
                }
            upsert_project_memory_profile(session, project_id, profile_obj)
            if run.approved_by:
                _bump_learning_runs_completed(session, run.approved_by, project_id)
            session.commit()
            post_hooks = run_hooks_sync(
                "post_finalization",
                {"project_id": project_id, "run_id": run_id, "status": "review_ready"},
                project_id=project_id,
            )
            for h in post_hooks:
                hxid = hook_exec_id(run_id=run_id, hook_point="post_finalization", hook_name=h.hook_name)
                if hook_execution_exists(session, run_id=run_id, hook_exec_id_value=hxid):
                    continue
                append_run_event(
                    session,
                    run_id,
                    "hook_result",
                    {
                        "hook_exec_id": hxid,
                        "hook_point": "post_finalization",
                        "hook_name": h.hook_name,
                        "outcome": h.outcome,
                        "message": h.message,
                    },
                )
                record_hook_execution(
                    session,
                    run_id=run_id,
                    hook_point="post_finalization",
                    hook_name=h.hook_name,
                    hook_exec_id_value=hxid,
                    idempotency_key=hxid,
                    outcome=h.outcome,
                )
            session.commit()
            increment("run_done_total")
            observe_latency("run_execution", (perf_counter() - started_at) * 1000.0)
            elapsed_ms = (perf_counter() - started_at) * 1000.0
            if elapsed_ms > 30_000:
                append_run_event(
                    session,
                    run_id,
                    "retry_watchdog",
                    {"mode": "heartbeat", "elapsed_ms": int(elapsed_ms), "status": "long_running_completed"},
                )
            # Checkpoint before terminal return
            session.refresh(run)
            if run.abort_requested:
                append_run_event(session, run_id, "run_control_applied", {"action": "abort", "checkpoint": "before_terminal_commit"})
                run.status = "failed"
                run.error_message = "Aborted before terminal commit."
                session.commit()
                return False, run.error_message
            record_run_trace("run_execution_done", project_id=project_id, run_id=run_id)
            return True, None
        except Exception as exc:  # noqa: BLE001 — surface as run failure
            tb = traceback.format_exc()
            session.rollback()
            append_run_event(
                session,
                run_id,
                "recovery_mode",
                overflow_recovery_event(
                    char_cap=int(getattr(settings, "memory_compaction_char_cap", 32000)),
                    applied_tier="tier4_context_collapse",
                ),
            )
            run = session.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
            if run:
                _write_token_usage(run, _run_usage, _run_cost)
                run.status = "failed"
                run.error_message = str(exc)[:2000]
                session.commit()
            append_run_event(session, run_id, "failed", {"error": str(exc), "traceback": tb[-3000:]})
            session.commit()
            increment("run_failed_total")
            observe_latency("run_execution", (perf_counter() - started_at) * 1000.0)
            record_run_trace(
                "run_execution_failed",
                project_id=project_id,
                run_id=run_id,
                extra={"error": str(exc)[:200]},
            )
            return False, str(exc)
    finally:
        session.close()
    return True, None
