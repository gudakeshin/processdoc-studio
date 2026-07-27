from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from app.core.tz import IST
from pathlib import Path
from typing import Any

import redis
from fastapi import WebSocket

from app.core.config import settings

import logging
logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(IST).isoformat()


def _events_path(excel_dir: Path) -> Path:
    root = excel_dir / "events"
    root.mkdir(parents=True, exist_ok=True)
    return root / "index.jsonl"


def _event_counter_path(events_path: Path) -> Path:
    return events_path.with_name("last_event_id.txt")


def _load_last_event_id(events_path: Path) -> int:
    counter_path = _event_counter_path(events_path)
    if counter_path.exists():
        try:
            return max(0, int(counter_path.read_text(encoding="utf-8").strip() or "0"))
        except Exception:  # noqa: S110 — best-effort, non-fatal
            pass
    # Fallback for existing histories without counter file.
    existing = _read_events(events_path)
    if not existing:
        return 0
    try:
        return int(existing[-1].get("event_id", 0))
    except Exception:
        return 0


def _store_last_event_id(events_path: Path, event_id: int) -> None:
    counter_path = _event_counter_path(events_path)
    counter_path.write_text(str(max(0, event_id)), encoding="utf-8")


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:  # noqa: S112 — best-effort, non-fatal
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


@dataclass
class ModelChannel:
    clients: set[WebSocket] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_channels: dict[str, ModelChannel] = {}
_channels_lock = asyncio.Lock()
_redis_client: redis.Redis | None = None
_redis_channel_prefix = settings.model_realtime_redis_channel_prefix
_listener_started: set[str] = set()
_listener_lock = threading.Lock()
_main_loop: asyncio.AbstractEventLoop | None = None


def _get_redis_client() -> redis.Redis | None:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    try:
        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        _redis_client = client
        return _redis_client
    except Exception as exc:
        logger.warning("%s: suppressed error: %s", '_get_redis_client', exc)
        return None


def _channel_key(project_id: str, model_id: str) -> str:
    return f"{project_id}/{model_id}"


def _redis_topic(project_id: str, model_id: str) -> str:
    return f"{_redis_channel_prefix}:{project_id}:{model_id}"


async def ensure_channel(project_id: str, model_id: str) -> ModelChannel:
    global _main_loop
    if _main_loop is None:
        _main_loop = asyncio.get_running_loop()
    key = _channel_key(project_id, model_id)
    async with _channels_lock:
        if key not in _channels:
            _channels[key] = ModelChannel()
            _ensure_listener(project_id, model_id)
        return _channels[key]


def append_model_event(excel_dir: Path, *, project_id: str, model_id: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = _events_path(excel_dir)
    next_id = _load_last_event_id(path) + 1
    envelope = {
        "event_id": next_id,
        "event_type": event_type,
        "project_id": project_id,
        "model_id": model_id,
        "server_ts": _now_iso(),
        "payload": payload,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(envelope) + "\n")
    _store_last_event_id(path, next_id)
    return envelope


def replay_model_events(excel_dir: Path, *, after_event_id: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    events = _read_events(_events_path(excel_dir))
    filtered = [e for e in events if int(e.get("event_id", 0)) > after_event_id]
    return filtered[:limit]


async def broadcast_model_event(project_id: str, model_id: str, event: dict[str, Any]) -> None:
    client = _get_redis_client()
    if client is not None:
        try:
            client.publish(_redis_topic(project_id, model_id), json.dumps(event))
            return
        except Exception:  # noqa: S110 — best-effort, non-fatal
            pass
    await _deliver_local(project_id, model_id, event)


def _ensure_listener(project_id: str, model_id: str) -> None:
    key = _channel_key(project_id, model_id)
    with _listener_lock:
        if key in _listener_started:
            return
        _listener_started.add(key)
    threading.Thread(
        target=_listener_loop,
        args=(project_id, model_id),
        daemon=True,
        name=f"model-realtime-listener-{project_id}-{model_id}",
    ).start()


def _listener_loop(project_id: str, model_id: str) -> None:
    client = _get_redis_client()
    if client is None:
        return
    topic = _redis_topic(project_id, model_id)
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(topic)
    while True:
        try:
            msg = pubsub.get_message(timeout=1.0)
            if not msg or msg.get("type") != "message":
                continue
            raw = msg.get("data")
            if not isinstance(raw, str):
                continue
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                continue
            loop = _main_loop
            if loop is None:
                continue
            loop.call_soon_threadsafe(asyncio.create_task, _deliver_local(project_id, model_id, payload))
        except Exception:  # noqa: S112 — best-effort, non-fatal
            continue


async def _deliver_local(project_id: str, model_id: str, event: dict[str, Any]) -> None:
    channel = await ensure_channel(project_id, model_id)
    async with channel.lock:
        for ws in list(channel.clients):
            try:
                await ws.send_json(event)
            except Exception:
                channel.clients.discard(ws)

