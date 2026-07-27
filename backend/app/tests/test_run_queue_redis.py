"""Exercises RunQueueRuntime's Redis-backed branches (queue_backend='redis') via fakeredis."""

import time

import pytest

from app.core.config import Settings
from app.services.run_queue.runtime import RunQueueRuntime

pytestmark = pytest.mark.redis


def _runtime() -> RunQueueRuntime:
    settings = Settings(run_queue_backend="redis")
    return RunQueueRuntime(settings)


def test_get_redis_client_connects(fake_redis) -> None:
    rt = _runtime()
    assert rt.get_redis_client() is not None


def test_mark_worker_heartbeat_writes_to_redis(fake_redis) -> None:
    rt = _runtime()
    rt.mark_worker_heartbeat()
    heartbeats = rt.list_worker_heartbeats()
    assert len(heartbeats) == 1
    assert heartbeats[0]["worker_id"] == rt.worker_id


def test_publish_run_event_does_not_raise(fake_redis) -> None:
    rt = _runtime()
    rt.publish_run_event("run-1", 1, "status", "{}")


def test_record_and_list_dead_letter_items(fake_redis) -> None:
    rt = _runtime()
    rt.record_dead_letter(
        {"project_id": "p1", "run_id": "r1", "reason": "execution_failed", "payload": "{}"}
    )
    items = rt.list_dead_letter_items()
    assert len(items) == 1
    assert items[0]["project_id"] == "p1"
    assert items[0]["reason"] == "execution_failed"


def test_list_dead_letter_items_filters_by_project(fake_redis) -> None:
    rt = _runtime()
    rt.record_dead_letter({"project_id": "p1", "run_id": "r1", "reason": "x", "payload": "{}"})
    # record_dead_letter's item_id includes a millisecond timestamp; sleep past the tick so the
    # second call doesn't collide with (and overwrite) the first under the redis backend.
    time.sleep(0.01)
    rt.record_dead_letter({"project_id": "p2", "run_id": "r2", "reason": "x", "payload": "{}"})
    items = rt.list_dead_letter_items(project_id="p1")
    assert len(items) == 1
    assert items[0]["project_id"] == "p1"


def test_queue_runtime_stats_redis_backend(fake_redis) -> None:
    rt = _runtime()
    rt.mark_worker_heartbeat()
    stats = rt.queue_runtime_stats()
    assert stats["backend"] == "redis"
    assert stats["healthy"] is True
    assert stats["depth"] == 0
    assert stats["worker_count"] == 1
