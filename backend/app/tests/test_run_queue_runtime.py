"""Unit tests for RunQueueRuntime (local queue primitives)."""

from app.core.config import Settings
from app.services.run_queue.runtime import RunQueueRuntime

_TEST_SETTINGS = Settings(
    jwt_secret="test-jwt-secret-32-chars-long-ok!",
    database_url="sqlite:///:memory:",
)


def test_compute_backoff_sec_exponential_cap() -> None:
    rt = RunQueueRuntime(_TEST_SETTINGS)
    # Note: backoff includes random jitter (0-1.5 sec), so use range assertions
    # Attempt 0: base=1.5, exp=1.5*(2^0)=1.5, + jitter(0-1.5) → 1.5-3.0
    backoff_0 = rt.compute_backoff_sec(0)
    assert 1.5 <= backoff_0 <= 3.0, f"Expected 1.5-3.0, got {backoff_0}"

    # Attempt 1: exp=1.5*(2^1)=3.0, + jitter(0-1.5) → 3.0-4.5
    backoff_1 = rt.compute_backoff_sec(1)
    assert 3.0 <= backoff_1 <= 4.5, f"Expected 3.0-4.5, got {backoff_1}"

    # Attempt 10: exp=1.5*(2^10)=1536, capped at max=20, + jitter(0-1.5) → 20.0-20.0 (capped)
    backoff_10 = rt.compute_backoff_sec(10)
    assert 20.0 <= backoff_10 <= 20.0, f"Expected 20.0 (capped), got {backoff_10}"


def test_local_try_enqueue_idempotent_key() -> None:
    rt = RunQueueRuntime(_TEST_SETTINGS)
    job = {"project_id": "p", "run_id": "r", "attempt": 0, "enqueued_at_ms": 0}
    assert rt.local_try_enqueue("p:r", job) is True
    assert rt.local_try_enqueue("p:r", job) is False
    assert rt.local_queue_depth() == 1


def test_replayable_reasons_frozen() -> None:
    assert "execution_failed" in RunQueueRuntime.REPLAYABLE_DEAD_LETTER_REASONS
