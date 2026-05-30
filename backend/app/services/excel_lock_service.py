from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from app.core.tz import IST
from typing import Any

import redis as _redis_module

from app.core.config import settings
from app.services.model_realtime import broadcast_model_event

log = logging.getLogger("processdoc.lock")

_LOCK_TTL_SECONDS = 120
_KEY_PREFIX = "processdoc:celllock"

_redis_client: _redis_module.Redis | None = None


def _get_redis() -> _redis_module.Redis | None:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        client = _redis_module.Redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        _redis_client = client
        return _redis_client
    except Exception:
        return None


def _rkey(project_id: str, model_id: str, cell_ref: str) -> str:
    return f"{_KEY_PREFIX}:{project_id}:{model_id}:{cell_ref}"


def _room_pattern(project_id: str, model_id: str) -> str:
    return f"{_KEY_PREFIX}:{project_id}:{model_id}:*"


# Lua script: atomically delete key only if value matches expected owner JSON substring
_RELEASE_SCRIPT = """
local val = redis.call('GET', KEYS[1])
if val and string.find(val, ARGV[1], 1, true) then
    redis.call('DEL', KEYS[1])
    return 1
end
return 0
"""


@dataclass
class _LockEntry:
    cell_ref: str
    locked_by: str
    locked_at: datetime
    version: int = 1
    expires_at: datetime = field(init=False)

    def __post_init__(self) -> None:
        self.expires_at = self.locked_at + timedelta(seconds=_LOCK_TTL_SECONDS)

    def is_expired(self) -> bool:
        return datetime.now(IST) > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        status = "locked" if not self.is_expired() else "unlocked"
        return {
            "cellRef": self.cell_ref,
            "lockedBy": self.locked_by,
            "lockedAt": self.locked_at.isoformat(),
            "version": self.version,
            "status": status,
            "expiresAt": self.expires_at.isoformat(),
        }


# In-process fallback when Redis is unavailable
_store: dict[tuple[str, str], dict[str, _LockEntry]] = {}
# WebSocket subscribers (local only — Redis pub/sub via broadcast_model_event for cross-process)
_subscribers: dict[tuple[str, str], set[asyncio.Queue[dict[str, Any]]]] = {}


def _local_room(project_id: str, model_id: str) -> dict[str, _LockEntry]:
    k = (project_id, model_id)
    if k not in _store:
        _store[k] = {}
    return _store[k]


def _prune_expired(room: dict[str, _LockEntry]) -> None:
    expired = [ref for ref, e in room.items() if e.is_expired()]
    for ref in expired:
        del room[ref]


# ---------------------------------------------------------------------------
# Public API — Redis-backed with in-process fallback
# ---------------------------------------------------------------------------

def get_locks(project_id: str, model_id: str) -> list[dict[str, Any]]:
    r = _get_redis()
    if r is not None:
        try:
            pattern = _room_pattern(project_id, model_id)
            keys = list(r.scan_iter(pattern))
            if not keys:
                return []
            vals = r.mget(keys)
            result = []
            for raw in vals:
                if raw:
                    result.append(json.loads(raw))
            return result
        except Exception as exc:
            log.warning("Redis get_locks failed, falling back to in-process: %s", exc)

    room = _local_room(project_id, model_id)
    _prune_expired(room)
    return [e.to_dict() for e in room.values()]


def acquire_lock(project_id: str, model_id: str, cell_ref: str, user: str) -> dict[str, Any]:
    now = datetime.now(IST)
    entry = _LockEntry(cell_ref=cell_ref, locked_by=user, locked_at=now)

    r = _get_redis()
    if r is not None:
        try:
            key = _rkey(project_id, model_id, cell_ref)
            payload = json.dumps(entry.to_dict())
            # Atomic: set only if not exists (NX), with TTL
            acquired = r.set(key, payload, nx=True, ex=_LOCK_TTL_SECONDS)
            if acquired:
                return {"ok": True, **entry.to_dict()}
            # Key exists — find owner
            existing_raw = r.get(key)
            if existing_raw:
                existing = json.loads(existing_raw)
                existing_owner = existing.get("lockedBy", "")
                if existing_owner == user:
                    # Re-acquire: refresh TTL
                    r.set(key, payload, ex=_LOCK_TTL_SECONDS)
                    return {"ok": True, **entry.to_dict()}
                return {"ok": False, "lockedBy": existing_owner}
            # Race: key disappeared between set-fail and get — retry once
            r.set(key, payload, ex=_LOCK_TTL_SECONDS)
            return {"ok": True, **entry.to_dict()}
        except Exception as exc:
            log.warning("Redis acquire_lock failed, falling back to in-process: %s", exc)

    room = _local_room(project_id, model_id)
    _prune_expired(room)
    existing = room.get(cell_ref)
    if existing and not existing.is_expired() and existing.locked_by != user:
        return {"ok": False, "lockedBy": existing.locked_by}
    version = (existing.version + 1) if existing else 1
    entry.version = version
    room[cell_ref] = entry
    return {"ok": True, **entry.to_dict()}


def release_lock(project_id: str, model_id: str, cell_ref: str, user: str) -> bool:
    r = _get_redis()
    if r is not None:
        try:
            key = _rkey(project_id, model_id, cell_ref)
            # Lua atomic check-and-delete: only delete if lockedBy matches user
            result = r.eval(_RELEASE_SCRIPT, 1, key, f'"lockedBy": "{user}"')
            return bool(result)
        except Exception as exc:
            log.warning("Redis release_lock failed, falling back to in-process: %s", exc)

    room = _local_room(project_id, model_id)
    entry = room.get(cell_ref)
    if entry is None or entry.locked_by != user:
        return False
    del room[cell_ref]
    return True


def force_release_lock(project_id: str, model_id: str, cell_ref: str) -> bool:
    r = _get_redis()
    if r is not None:
        try:
            key = _rkey(project_id, model_id, cell_ref)
            return bool(r.delete(key))
        except Exception as exc:
            log.warning("Redis force_release_lock failed, falling back to in-process: %s", exc)

    room = _local_room(project_id, model_id)
    if cell_ref in room:
        del room[cell_ref]
        return True
    return False


def release_all_locks_for_user(project_id: str, model_id: str, user: str) -> list[str]:
    r = _get_redis()
    if r is not None:
        try:
            pattern = _room_pattern(project_id, model_id)
            keys = list(r.scan_iter(pattern))
            released = []
            for key in keys:
                raw = r.get(key)
                if raw:
                    data = json.loads(raw)
                    if data.get("lockedBy") == user:
                        r.delete(key)
                        released.append(data.get("cellRef", key.split(":")[-1]))
            return released
        except Exception as exc:
            log.warning("Redis release_all_locks_for_user failed, falling back to in-process: %s", exc)

    room = _local_room(project_id, model_id)
    released = [ref for ref, e in list(room.items()) if e.locked_by == user]
    for ref in released:
        del room[ref]
    return released


# ---------------------------------------------------------------------------
# WebSocket pub/sub (local subscribers; cross-process via broadcast_model_event)
# ---------------------------------------------------------------------------

def _subs(project_id: str, model_id: str) -> set[asyncio.Queue[dict[str, Any]]]:
    k = (project_id, model_id)
    if k not in _subscribers:
        _subscribers[k] = set()
    return _subscribers[k]


def subscribe(project_id: str, model_id: str) -> asyncio.Queue[dict[str, Any]]:
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _subs(project_id, model_id).add(q)
    return q


def unsubscribe(project_id: str, model_id: str, q: asyncio.Queue[dict[str, Any]]) -> None:
    _subs(project_id, model_id).discard(q)


async def broadcast(project_id: str, model_id: str, msg: dict[str, Any]) -> None:
    # Deliver to local WebSocket subscribers
    for q in list(_subs(project_id, model_id)):
        await q.put(msg)
    # Cross-process delivery via Redis pub/sub
    try:
        await broadcast_model_event(project_id, model_id, msg)
    except Exception as exc:
        log.debug("broadcast_model_event failed (non-fatal): %s", exc)
