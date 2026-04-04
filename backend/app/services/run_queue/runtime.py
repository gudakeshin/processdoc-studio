"""Thread-safe run queue state: local list + optional Redis backend."""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Callable

import redis

from app.core.config import Settings
from app.services.observability import increment, observe_latency
from app.services.retry_policy import compute_rate_limit_backoff


class RunQueueRuntime:
    """Owns queue backends, Redis client cache, dead-letter storage, and worker heartbeats."""

    REPLAYABLE_DEAD_LETTER_REASONS = frozenset(
        {
            "queue_deserialize_failed",
            "missing_project_or_run_id",
            "execution_failed",
        }
    )

    def __init__(self, s: Settings) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._meta = threading.Lock()
        self._queue: list[dict[str, Any]] = []
        self._queued_keys: set[str] = set()
        self.queue_cv = threading.Condition()
        self._worker_started = False

        self.queue_backend = s.run_queue_backend
        self.redis_queue_name = s.run_execution_queue_name
        self.redis_enqueue_dedupe_prefix = s.run_enqueue_dedupe_prefix
        self.redis_enqueue_dedupe_ttl_sec = s.run_enqueue_dedupe_ttl_sec
        self.redis_dead_letter_index = s.run_dead_letter_index_key
        self.redis_dead_letter_item_prefix = s.run_dead_letter_item_prefix
        self.redis_heartbeat_prefix = s.run_worker_heartbeat_key_prefix
        self.redis_run_events_prefix = s.run_events_channel_prefix
        self.redis_heartbeat_ttl_sec = s.run_worker_heartbeat_ttl_sec
        self.worker_id = s.run_worker_id
        self.max_active_runs_global = s.run_max_active_global
        self.max_active_runs_per_project = s.run_max_active_per_project
        self.max_active_runs_per_user = s.run_max_active_per_user
        self.dead_letter_max_replay_attempts = s.run_dead_letter_max_replay_attempts
        self.execution_retry_max_attempts = s.run_execution_retry_max_attempts
        self.execution_retry_backoff_base_sec = s.run_execution_retry_backoff_base_sec
        self.execution_retry_backoff_max_sec = s.run_execution_retry_backoff_max_sec
        self.dead_letter_replay_cooldown_sec = s.run_dead_letter_replay_cooldown_sec

        self._redis_url = s.redis_url
        self._redis_client: redis.Redis | None = None
        self.worker_last_heartbeat_ms = 0
        self.worker_processed_total = 0

        self.dead_letter_local: dict[str, dict[str, Any]] = {}
        self.dead_letter_local_order: list[str] = []

    def get_redis_client(self) -> redis.Redis | None:
        if self._redis_client is not None:
            return self._redis_client
        try:
            client = redis.Redis.from_url(self._redis_url, decode_responses=True)
            client.ping()
            self._redis_client = client
            return self._redis_client
        except Exception:
            return None

    def mark_worker_heartbeat(self) -> None:
        now_ms = int(time.time() * 1000)
        self.worker_last_heartbeat_ms = now_ms
        client = self.get_redis_client()
        if client is not None:
            try:
                payload = {"worker_id": self.worker_id, "backend": self.queue_backend, "last_heartbeat_ms": now_ms}
                key = f"{self.redis_heartbeat_prefix}:{self.worker_id}"
                client.setex(key, self.redis_heartbeat_ttl_sec, json.dumps(payload))
            except Exception:
                increment("run_worker_heartbeat_write_fail_total")

    def lock_for(self, run_id: str) -> threading.Lock:
        with self._meta:
            if run_id not in self._locks:
                self._locks[run_id] = threading.Lock()
            return self._locks[run_id]

    def publish_run_event(self, run_id: str, event_id: int, event_type: str, payload: str) -> None:
        client = self.get_redis_client() if self.queue_backend == "redis" else None
        if client is not None:
            try:
                client.publish(
                    f"{self.redis_run_events_prefix}:{run_id}",
                    json.dumps({"id": event_id, "event_type": event_type, "payload": payload}),
                )
            except Exception:
                increment("run_event_pubsub_publish_fail_total")

    def start_local_daemon(self, loop: Callable[[], None]) -> None:
        if self.queue_backend == "redis":
            return
        with self.queue_cv:
            if self._worker_started:
                return
            self._worker_started = True
            threading.Thread(target=loop, daemon=True).start()

    @property
    def worker_started(self) -> bool:
        return self._worker_started

    def local_try_enqueue(self, key: str, job: dict[str, Any]) -> bool:
        with self.queue_cv:
            if key in self._queued_keys:
                return False
            self._queued_keys.add(key)
            self._queue.append(job)
            self.queue_cv.notify()
            return True

    def local_wait_pop_job(self) -> dict[str, Any]:
        with self.queue_cv:
            while not self._queue:
                self.queue_cv.wait()
            return self._queue.pop(0)

    def local_discard_key(self, key: str) -> None:
        with self.queue_cv:
            self._queued_keys.discard(key)

    def local_queue_depth(self) -> int:
        with self.queue_cv:
            return len(self._queue)

    def bump_processed(self) -> None:
        self.worker_processed_total += 1

    def queue_runtime_stats(self) -> dict[str, Any]:
        if self.queue_backend == "redis":
            client = self.get_redis_client()
            if client is None:
                return {
                    "backend": "redis",
                    "healthy": False,
                    "depth": 0,
                    "oldest_age_ms": None,
                    "worker_last_heartbeat_ms": self.worker_last_heartbeat_ms or None,
                    "worker_processed_total": self.worker_processed_total,
                    "worker_count": 0,
                    "workers": [],
                }
            workers = self.list_worker_heartbeats()
            depth = int(client.llen(self.redis_queue_name))
            oldest_age_ms: int | None = None
            if depth > 0:
                first = client.lindex(self.redis_queue_name, 0)
                if first:
                    try:
                        payload = json.loads(first)
                        enq_ms = int(payload.get("enqueued_at_ms", 0))
                        if enq_ms > 0:
                            oldest_age_ms = int(time.time() * 1000) - enq_ms
                    except Exception:
                        oldest_age_ms = None
            return {
                "backend": "redis",
                "healthy": True,
                "depth": depth,
                "oldest_age_ms": oldest_age_ms,
                "worker_last_heartbeat_ms": self.worker_last_heartbeat_ms or None,
                "worker_processed_total": self.worker_processed_total,
                "worker_count": len(workers),
                "workers": workers,
            }
        with self.queue_cv:
            depth = len(self._queue)
        return {
            "backend": "local",
            "healthy": True,
            "depth": depth,
            "oldest_age_ms": None,
            "worker_last_heartbeat_ms": self.worker_last_heartbeat_ms or None,
            "worker_processed_total": self.worker_processed_total,
            "worker_count": 1 if self.worker_last_heartbeat_ms else 0,
            "workers": [
                {
                    "worker_id": self.worker_id,
                    "backend": "local",
                    "last_heartbeat_ms": self.worker_last_heartbeat_ms or None,
                }
            ]
            if self.worker_last_heartbeat_ms
            else [],
        }

    def list_worker_heartbeats(self) -> list[dict[str, Any]]:
        client = self.get_redis_client()
        if client is None:
            return []
        try:
            keys = client.keys(f"{self.redis_heartbeat_prefix}:*")
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        for key in keys:
            try:
                raw = client.get(key)
                if not raw:
                    continue
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    out.append(payload)
            except Exception:
                continue
        out.sort(key=lambda x: int(x.get("last_heartbeat_ms", 0)), reverse=True)
        return out

    def record_dead_letter(self, item: dict[str, Any]) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        item_id = f"dl_{now_ms}_{os.getpid()}_{len(self.dead_letter_local_order)}"
        payload = {
            "id": item_id,
            "created_at_ms": now_ms,
            "status": "open",
            "project_id": item.get("project_id"),
            "run_id": item.get("run_id"),
            "reason": item.get("reason", "unknown"),
            "payload": item.get("payload"),
            "last_error": item.get("last_error"),
            "error_class": item.get("error_class"),
            "final_attempt": item.get("final_attempt"),
            "retry_policy": item.get("retry_policy"),
            "attempt_history": item.get("attempt_history") or [],
            "replay_cooldown_until_ms": item.get("replay_cooldown_until_ms"),
            "replayed_at_ms": None,
            "replay_attempts": 0,
            "max_replay_attempts": self.dead_letter_max_replay_attempts,
        }
        client = self.get_redis_client() if self.queue_backend == "redis" else None
        if client is not None:
            key = f"{self.redis_dead_letter_item_prefix}:{item_id}"
            client.set(key, json.dumps(payload))
            client.lpush(self.redis_dead_letter_index, item_id)
        else:
            self.dead_letter_local[item_id] = payload
            self.dead_letter_local_order.insert(0, item_id)
        increment("run_execution_dead_letter_total")
        return payload

    def list_dead_letter_items(self, *, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        client = self.get_redis_client() if self.queue_backend == "redis" else None
        items: list[dict[str, Any]] = []
        if client is not None:
            ids = client.lrange(self.redis_dead_letter_index, 0, max(0, limit - 1))
            for item_id in ids:
                raw = client.get(f"{self.redis_dead_letter_item_prefix}:{item_id}")
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except Exception:
                    continue
                if project_id and payload.get("project_id") != project_id:
                    continue
                items.append(payload)
            return items

        for item_id in self.dead_letter_local_order[:limit]:
            payload = self.dead_letter_local.get(item_id)
            if not payload:
                continue
            if project_id and payload.get("project_id") != project_id:
                continue
            items.append(payload)
        return items

    def compute_backoff_sec(self, attempt: int) -> float:
        return compute_rate_limit_backoff(
            retry_after_sec=None,
            attempt=max(1, int(attempt) + 1),
            base_sec=self.execution_retry_backoff_base_sec,
            max_sec=self.execution_retry_backoff_max_sec,
        )

    def schedule_redis_retry(self, delay_sec: float, retry_payload: dict[str, Any]) -> None:
        client = self.get_redis_client()
        if client is None:
            return

        def _push_retry() -> None:
            try:
                client.rpush(self.redis_queue_name, json.dumps(retry_payload))
            except Exception:
                increment("run_execution_retry_enqueue_fail_total")

        threading.Timer(delay_sec, _push_retry).start()

    def schedule_local_retry(self, delay_sec: float, project_id: str, run_id: str, job: dict[str, Any]) -> None:
        def _push_local_retry() -> None:
            key = f"{project_id}:{run_id}"
            with self.queue_cv:
                if key not in self._queued_keys:
                    self._queued_keys.add(key)
                    self._queue.append(job)
                    self.queue_cv.notify()

        threading.Timer(delay_sec, _push_local_retry).start()

    def run_redis_consumer_loop(
        self,
        execute_job: Callable[[str, str, dict[str, Any]], tuple[bool, str | None]],
        handle_failed: Callable[..., None],
    ) -> None:
        client = self.get_redis_client()
        if client is None:
            raise RuntimeError("RUN_QUEUE_BACKEND=redis but Redis is unavailable.")
        while True:
            self.mark_worker_heartbeat()
            item = client.blpop(self.redis_queue_name, timeout=5)
            if not item:
                continue
            _, raw = item
            try:
                payload = json.loads(raw)
                project_id = str(payload.get("project_id", ""))
                run_id = str(payload.get("run_id", ""))
                attempt = int(payload.get("attempt", 0) or 0)
                enqueued_at_ms = int(payload.get("enqueued_at_ms", 0) or 0)
                attempt_history = payload.get("attempt_history")
                if not isinstance(attempt_history, list):
                    attempt_history = []
                if not project_id or not run_id:
                    self.record_dead_letter(
                        {
                            "project_id": None,
                            "run_id": None,
                            "reason": "missing_project_or_run_id",
                            "payload": raw,
                        }
                    )
                    continue
                if enqueued_at_ms > 0:
                    observe_latency("run_queue_lag", (int(time.time() * 1000) - enqueued_at_ms))
                success, error_detail = execute_job(project_id, run_id, payload if isinstance(payload, dict) else {})
                if success:
                    self.worker_processed_total += 1
                else:
                    handle_failed(
                        project_id=project_id,
                        run_id=run_id,
                        attempt=attempt,
                        last_error=error_detail,
                        prior_attempt_history=attempt_history,
                        backend="redis",
                    )
            except Exception:
                increment("run_execution_queue_deserialize_fail_total")
                self.record_dead_letter(
                    {
                        "project_id": None,
                        "run_id": None,
                        "reason": "queue_deserialize_failed",
                        "payload": raw,
                    }
                )
                continue
