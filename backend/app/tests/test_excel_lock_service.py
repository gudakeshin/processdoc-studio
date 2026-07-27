"""Tests for excel_lock_service.py: acquire, release, expiry, and Redis cross-instance visibility."""

import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import fakeredis

import app.services.excel_lock_service as lock_svc
from app.services.excel_lock_service import (
    acquire_lock,
    force_release_lock,
    get_locks,
    release_lock,
    _LockEntry,
    _store,
)
from app.core.tz import IST


PID = "test-project"
MID = "test-model"


@pytest.fixture(autouse=True)
def _clear_local_store():
    """Wipe in-process fallback store between tests."""
    _store.clear()
    yield
    _store.clear()


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch):
    """Force in-process path by making _get_redis() return None."""
    monkeypatch.setattr(lock_svc, "_redis_client", None)
    monkeypatch.setattr(lock_svc, "_get_redis", lambda: None)
    yield


# ---------------------------------------------------------------------------
# Basic in-process tests
# ---------------------------------------------------------------------------

def test_acquire_and_release_basic():
    result = acquire_lock(PID, MID, "B4", "alice@example.com")
    assert result["ok"] is True
    assert result["cellRef"] == "B4"
    assert result["lockedBy"] == "alice@example.com"

    released = release_lock(PID, MID, "B4", "alice@example.com")
    assert released is True

    # After release, get_locks should be empty
    assert get_locks(PID, MID) == []


def test_second_acquire_blocked_returns_owner():
    acquire_lock(PID, MID, "C5", "alice@example.com")
    result = acquire_lock(PID, MID, "C5", "bob@example.com")
    assert result["ok"] is False
    assert result["lockedBy"] == "alice@example.com"


def test_same_user_can_reacquire():
    acquire_lock(PID, MID, "D6", "alice@example.com")
    result = acquire_lock(PID, MID, "D6", "alice@example.com")
    assert result["ok"] is True


def test_release_by_wrong_user_fails():
    acquire_lock(PID, MID, "E7", "alice@example.com")
    released = release_lock(PID, MID, "E7", "bob@example.com")
    assert released is False
    # Lock still held by alice
    locks = get_locks(PID, MID)
    assert any(l["cellRef"] == "E7" for l in locks)


def test_force_release_removes_any_lock():
    acquire_lock(PID, MID, "F8", "alice@example.com")
    ok = force_release_lock(PID, MID, "F8")
    assert ok is True
    assert get_locks(PID, MID) == []


def test_expired_lock_pruned_on_get_locks():
    """Lock whose TTL has passed must not appear in get_locks()."""
    entry = _LockEntry(
        cell_ref="Z1",
        locked_by="alice@example.com",
        locked_at=datetime.now(IST) - timedelta(seconds=300),
    )
    # Manually plant an already-expired entry in the local store
    room = _store.setdefault((PID, MID), {})
    room["Z1"] = entry

    locks = get_locks(PID, MID)
    assert not any(l["cellRef"] == "Z1" for l in locks)


# ---------------------------------------------------------------------------
# Redis-backed cross-instance visibility
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscribe_receives_broadcast():
    """subscribe() returns a queue that receives messages from broadcast()."""
    from app.services.excel_lock_service import subscribe, unsubscribe, broadcast, _subscribers

    pid, mid = "sub-proj", "sub-model"
    q = subscribe(pid, mid)
    try:
        msg = {"type": "lock_update", "locks": []}
        with patch("app.services.excel_lock_service.broadcast_model_event", new_callable=AsyncMock):
            await broadcast(pid, mid, msg)
        received = q.get_nowait()
        assert received == msg
    finally:
        unsubscribe(pid, mid, q)


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    """After unsubscribe, broadcast does not add to the removed queue."""
    from app.services.excel_lock_service import subscribe, unsubscribe, broadcast

    pid, mid = "unsub-proj", "unsub-model"
    q = subscribe(pid, mid)
    unsubscribe(pid, mid, q)

    with patch("app.services.excel_lock_service.broadcast_model_event", new_callable=AsyncMock):
        await broadcast(pid, mid, {"type": "test"})
    assert q.empty()


def test_redis_release_all_locks_for_user():
    """release_all_locks_for_user correctly removes only the target user's locks via Redis."""
    from app.services.excel_lock_service import release_all_locks_for_user

    fake_redis = fakeredis.FakeRedis(decode_responses=True)

    with patch.object(lock_svc, "_get_redis", return_value=fake_redis):
        acquire_lock("rlu-proj", "rlu-model", "A1", "alice@example.com")
        acquire_lock("rlu-proj", "rlu-model", "A2", "alice@example.com")
        acquire_lock("rlu-proj", "rlu-model", "A3", "bob@example.com")

        released = release_all_locks_for_user("rlu-proj", "rlu-model", "alice@example.com")
        assert set(released) == {"A1", "A2"}

        remaining = get_locks("rlu-proj", "rlu-model")
        assert len(remaining) == 1
        assert remaining[0]["lockedBy"] == "bob@example.com"


@pytest.mark.asyncio
async def test_broadcast_exception_is_non_fatal():
    """broadcast() swallows broadcast_model_event errors silently."""
    from app.services.excel_lock_service import subscribe, unsubscribe, broadcast

    pid, mid = "exc-proj", "exc-model"
    q = subscribe(pid, mid)
    try:
        with patch(
            "app.services.excel_lock_service.broadcast_model_event",
            side_effect=Exception("redis gone"),
        ):
            # Should not raise
            await broadcast(pid, mid, {"type": "test"})
        # Local subscriber still received the message
        assert not q.empty()
    finally:
        unsubscribe(pid, mid, q)


def test_redis_backed_cross_instance_visibility():
    """Two service callers sharing a fakeredis client must see each other's locks."""
    fake_redis = fakeredis.FakeRedis(decode_responses=True)

    with patch.object(lock_svc, "_get_redis", return_value=fake_redis):
        # Acquire on "instance 1" context
        result = acquire_lock("proj-redis", "model-redis", "A1", "user1@example.com")
        assert result["ok"] is True

        # Read from "instance 2" context — same fakeredis backing
        locks = get_locks("proj-redis", "model-redis")
        assert len(locks) == 1
        assert locks[0]["cellRef"] == "A1"
        assert locks[0]["lockedBy"] == "user1@example.com"


def test_force_release_nonexistent_returns_false():
    result = force_release_lock(PID, MID, "XX99")
    assert result is False


def test_release_all_locks_for_user():
    acquire_lock(PID, MID, "A1", "alice@example.com")
    acquire_lock(PID, MID, "A2", "alice@example.com")
    acquire_lock(PID, MID, "A3", "bob@example.com")

    from app.services.excel_lock_service import release_all_locks_for_user
    released = release_all_locks_for_user(PID, MID, "alice@example.com")
    assert set(released) == {"A1", "A2"}

    # Bob's lock remains
    remaining = get_locks(PID, MID)
    assert len(remaining) == 1
    assert remaining[0]["lockedBy"] == "bob@example.com"


def test_release_all_locks_empty_room():
    from app.services.excel_lock_service import release_all_locks_for_user
    released = release_all_locks_for_user("empty-proj", "empty-model", "nobody@example.com")
    assert released == []


def test_redis_release_lua_atomic():
    """Release via Lua script only succeeds for the lock owner.

    fakeredis doesn't support EVAL without lupa, so we patch eval with a
    Python implementation of the same atomic check-and-delete logic.
    """
    fake_redis = fakeredis.FakeRedis(decode_responses=True)

    def _py_eval(script: str, numkeys: int, key: str, owner_fragment: str) -> int:
        val = fake_redis.get(key)
        if val and owner_fragment in val:
            fake_redis.delete(key)
            return 1
        return 0

    fake_redis.eval = _py_eval  # type: ignore[method-assign]

    with patch.object(lock_svc, "_get_redis", return_value=fake_redis):
        acquire_lock("proj-lua", "model-lua", "B2", "alice@example.com")

        # Bob tries to release alice's lock — should fail
        released = release_lock("proj-lua", "model-lua", "B2", "bob@example.com")
        assert released is False

        # Alice releases her own lock — should succeed
        released = release_lock("proj-lua", "model-lua", "B2", "alice@example.com")
        assert released is True
        assert get_locks("proj-lua", "model-lua") == []
