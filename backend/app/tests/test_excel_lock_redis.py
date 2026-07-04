"""Exercises excel_lock_service's Redis-backed NX/TTL/Lua-release branches via fakeredis."""

import pytest

from app.services import excel_lock_service as locks

pytestmark = pytest.mark.redis


@pytest.fixture(autouse=True)
def _reset_module_redis_client(fake_redis):
    """The module caches its Redis client in a global; force a fresh lazy reconnect
    per test so it picks up the fixture's patched `from_url`, and clear afterward
    so later (non-redis) tests don't inherit a fakeredis client.
    """
    locks._redis_client = None
    yield
    locks._redis_client = None


def test_acquire_lock_uses_redis() -> None:
    result = locks.acquire_lock("proj1", "model1", "A1", "alice")
    assert result["ok"] is True
    assert locks._get_redis() is not None


def test_acquire_lock_conflict_blocks_other_user() -> None:
    locks.acquire_lock("proj1", "model1", "A1", "alice")
    result = locks.acquire_lock("proj1", "model1", "A1", "bob")
    assert result["ok"] is False
    assert result["lockedBy"] == "alice"


def test_acquire_lock_reacquire_by_same_user_refreshes() -> None:
    locks.acquire_lock("proj1", "model1", "A1", "alice")
    result = locks.acquire_lock("proj1", "model1", "A1", "alice")
    assert result["ok"] is True


def test_release_lock_by_owner_succeeds() -> None:
    locks.acquire_lock("proj1", "model1", "A1", "alice")
    assert locks.release_lock("proj1", "model1", "A1", "alice") is True
    assert locks.get_locks("proj1", "model1") == []


def test_release_lock_by_non_owner_fails() -> None:
    locks.acquire_lock("proj1", "model1", "A1", "alice")
    assert locks.release_lock("proj1", "model1", "A1", "bob") is False


def test_force_release_lock() -> None:
    locks.acquire_lock("proj1", "model1", "A1", "alice")
    assert locks.force_release_lock("proj1", "model1", "A1") is True
    assert locks.get_locks("proj1", "model1") == []


def test_release_all_locks_for_user() -> None:
    locks.acquire_lock("proj1", "model1", "A1", "alice")
    locks.acquire_lock("proj1", "model1", "B1", "alice")
    locks.acquire_lock("proj1", "model1", "C1", "bob")
    released = locks.release_all_locks_for_user("proj1", "model1", "alice")
    assert sorted(released) == ["A1", "B1"]
    remaining = {entry["cellRef"] for entry in locks.get_locks("proj1", "model1")}
    assert remaining == {"C1"}
