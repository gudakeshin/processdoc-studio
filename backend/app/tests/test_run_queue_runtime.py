"""Unit tests for RunQueueRuntime (local queue primitives)."""

from app.core.config import Settings
from app.services.run_queue.runtime import RunQueueRuntime


def test_compute_backoff_sec_exponential_cap() -> None:
    rt = RunQueueRuntime(Settings())
    assert rt.compute_backoff_sec(0) == 1.5
    assert rt.compute_backoff_sec(1) == 3.0
    assert rt.compute_backoff_sec(10) == 20.0


def test_local_try_enqueue_idempotent_key() -> None:
    rt = RunQueueRuntime(Settings())
    job = {"project_id": "p", "run_id": "r", "attempt": 0, "enqueued_at_ms": 0}
    assert rt.local_try_enqueue("p:r", job) is True
    assert rt.local_try_enqueue("p:r", job) is False
    assert rt.local_queue_depth() == 1


def test_replayable_reasons_frozen() -> None:
    assert "execution_failed" in RunQueueRuntime.REPLAYABLE_DEAD_LETTER_REASONS
