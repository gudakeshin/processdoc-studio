import logging
import asyncio
import html
import json
import threading
from dataclasses import dataclass, field
from typing import Any

import redis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import require_project_role
from app.core.config import settings
from app.db.models import Membership, Run, User
from app.db.session import SessionLocal
from app.services.run_worker import append_run_event
from app.services.storage import workspace_path

logger = logging.getLogger(__name__)

router = APIRouter()
_redis_client: redis.Redis | None = None
_redis_drawio_prefix = settings.drawio_collab_channel_prefix
_listeners_started: set[str] = set()
_listeners_lock = threading.Lock()
_main_loop: asyncio.AbstractEventLoop | None = None


@dataclass
class DocState:
    # Lock state (single writer).
    lock_owner_user_id: str | None = None
    lock_owner_email: str | None = None
    # Latest XML + revision. Autosaves are persisted to runs/<run_id>/drawio.xml.
    revision: int = 0
    xml: str = ""
    # Connected websocket clients.
    clients: set[WebSocket] = field(default_factory=set)
    # Serialize updates (locks + xml broadcasts) for this doc.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_doc_states: dict[str, DocState] = {}
_doc_states_lock = asyncio.Lock()


def _doc_key(project_id: str, run_id: str) -> str:
    return f"{project_id}/{run_id}"


def _redis_channel(project_id: str, run_id: str) -> str:
    return f"{_redis_drawio_prefix}:{project_id}:{run_id}"


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


def _read_drawio_xml_from_disk(project_id: str, run_id: str) -> str:
    def _blank_diagram_xml() -> str:
        return (
            '<mxGraphModel dx="1200" dy="800" grid="1" gridSize="10" guides="1" tooltips="1" '
            'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1169" pageHeight="827" '
            'math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>'
        )

    def _normalize(raw: str) -> str:
        text = (raw or "").strip()
        if not text:
            return ""
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                text = "\n".join(lines[1:-1]).strip()
        if text.startswith("&lt;"):
            text = html.unescape(text)
        if "<mxGraphModel" not in text and "<mxfile" not in text:
            return ""
        start = text.find("<mxfile")
        if start == -1:
            start = text.find("<mxGraphModel")
        if start > 0:
            text = text[start:].strip()
        return text

    run_dir = workspace_path(project_id) / "runs" / run_id
    primary = run_dir / "drawio.xml"
    legacy = run_dir / "drawio_xml.txt"
    try:
        raw = primary.read_text(encoding="utf-8")
        normalized = _normalize(raw)
        if normalized:
            if normalized != raw.strip():
                # Self-heal malformed wrappers/escaping for future reads.
                primary.write_text(normalized, encoding="utf-8")
            return normalized
    except FileNotFoundError:
        pass

    try:
        # Backward compatibility for older runs written before canonical filename adoption.
        raw_legacy = legacy.read_text(encoding="utf-8")
        normalized = _normalize(raw_legacy)
        if normalized:
            primary.write_text(normalized, encoding="utf-8")
            return normalized
    except FileNotFoundError:
        pass

    # Last-resort autocorrect: return a valid empty diagram instead of invalid/blank payload.
    fallback = _blank_diagram_xml()
    run_dir.mkdir(parents=True, exist_ok=True)
    primary.write_text(fallback, encoding="utf-8")
    return fallback


def _user_from_access_token(db: Session, token: str) -> User:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("typ") != "access":
            raise JWTError("not an access token")
        email = payload.get("sub")
        if not isinstance(email, str):
            raise JWTError("missing sub")
    except JWTError as exc:
        raise ValueError("Invalid credentials") from exc

    user = db.scalar(select(User).where(User.email == email))
    if not user:
        raise ValueError("Invalid credentials")
    return user


async def _broadcast(state: DocState, message: dict[str, Any]) -> None:
    # Snapshot because clients may disconnect during send.
    for ws in list(state.clients):
        try:
            await ws.send_json(message)
        except Exception:
            state.clients.discard(ws)


def _ensure_listener(project_id: str, run_id: str) -> None:
    key = _doc_key(project_id, run_id)
    with _listeners_lock:
        if key in _listeners_started:
            return
        _listeners_started.add(key)
    threading.Thread(
        target=_listener_loop,
        args=(project_id, run_id),
        daemon=True,
        name=f"drawio-collab-listener-{project_id}-{run_id}",
    ).start()


def _listener_loop(project_id: str, run_id: str) -> None:
    client = _get_redis_client()
    if client is None:
        return
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(_redis_channel(project_id, run_id))
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
            loop.call_soon_threadsafe(asyncio.create_task, _apply_remote_update(project_id, run_id, payload))
        except Exception:  # noqa: S112 — best-effort, non-fatal
            continue


async def _apply_remote_update(project_id: str, run_id: str, payload: dict[str, Any]) -> None:
    key = _doc_key(project_id, run_id)
    async with _doc_states_lock:
        if key not in _doc_states:
            return
        state = _doc_states[key]
    async with state.lock:
        if payload.get("type") == "drawio_update":
            xml = payload.get("xml")
            revision = payload.get("revision")
            if isinstance(xml, str):
                state.xml = xml
            if isinstance(revision, int):
                state.revision = max(state.revision, revision)
        if payload.get("type") == "lock_update":
            locked_by = payload.get("locked_by")
            if isinstance(locked_by, dict):
                state.lock_owner_user_id = locked_by.get("user_id")
                state.lock_owner_email = locked_by.get("email")
            else:
                state.lock_owner_user_id = None
                state.lock_owner_email = None
        await _broadcast(state, payload)


@router.websocket("/{project_id}/{run_id}/ws")
async def drawio_ws(websocket: WebSocket, project_id: str, run_id: str) -> None:
    global _main_loop
    if _main_loop is None:
        _main_loop = asyncio.get_running_loop()
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008)
        return

    db = SessionLocal()
    ws_key = _doc_key(project_id, run_id)
    doc_state: DocState | None = None
    user: User | None = None
    user_role: str | None = None

    try:
        try:
            user = _user_from_access_token(db, token)
        except ValueError:
            await websocket.close(code=1008)
            return

        # Ensure the run exists + user has permission.
        run = db.scalar(select(Run).where(Run.id == run_id, Run.project_id == project_id))
        if not run:
            await websocket.close(code=1008)
            return

        require_project_role(project_id, {"Owner", "Editor", "Viewer"}, user, db)
        user_role = db.scalar(
            select(Membership.role).where(Membership.project_id == project_id, Membership.user_id == user.id)
        )
        if not user_role:
            await websocket.close(code=1008)
            return

        async with _doc_states_lock:
            doc_state = _doc_states.get(ws_key) or DocState()
            if ws_key not in _doc_states:
                # Bootstrap initial XML from disk at first access.
                doc_state.xml = _read_drawio_xml_from_disk(project_id, run_id)
                _doc_states[ws_key] = doc_state
            doc_state = _doc_states[ws_key]
            _ensure_listener(project_id, run_id)

        assert user is not None
        await websocket.accept()
        doc_state.clients.add(websocket)

        async with doc_state.lock:
            await websocket.send_json(
                {
                    "type": "bootstrap",
                    "project_id": project_id,
                    "run_id": run_id,
                    "xml": doc_state.xml,
                    "revision": doc_state.revision,
                    "locked_by": {
                        "user_id": doc_state.lock_owner_user_id,
                        "email": doc_state.lock_owner_email,
                    }
                    if doc_state.lock_owner_user_id
                    else None,
                }
            )

        while True:
            msg = await websocket.receive_text()
            try:
                body = json.loads(msg)
            except json.JSONDecodeError:
                # Ignore invalid messages.
                continue

            msg_type = (body.get("type") or "").strip()

            if msg_type == "request_lock":
                async with doc_state.lock:
                    if user_role not in {"Owner", "Editor"}:
                        await websocket.send_json(
                            {
                                "type": "lock_denied",
                                "locked_by": {
                                    "user_id": doc_state.lock_owner_user_id,
                                    "email": doc_state.lock_owner_email,
                                }
                                if doc_state.lock_owner_user_id
                                else None,
                                "reason": "insufficient_role",
                                "revision": doc_state.revision,
                            }
                        )
                        continue
                    if doc_state.lock_owner_user_id == user.id:
                        await websocket.send_json({"type": "lock_acquired", "revision": doc_state.revision})
                        continue
                    if doc_state.lock_owner_user_id is None:
                        doc_state.lock_owner_user_id = user.id
                        doc_state.lock_owner_email = user.email
                        await _broadcast(
                            doc_state,
                            {
                                "type": "lock_update",
                                "locked_by": {"user_id": user.id, "email": user.email},
                                "revision": doc_state.revision,
                            },
                        )
                        client = _get_redis_client()
                        if client is not None:
                            client.publish(
                                _redis_channel(project_id, run_id),
                                json.dumps(
                                    {
                                        "type": "lock_update",
                                        "locked_by": {"user_id": user.id, "email": user.email},
                                        "revision": doc_state.revision,
                                    }
                                ),
                            )
                        continue

                    await websocket.send_json(
                        {
                            "type": "lock_denied",
                            "locked_by": {
                                "user_id": doc_state.lock_owner_user_id,
                                "email": doc_state.lock_owner_email,
                            },
                            "revision": doc_state.revision,
                        }
                    )

            elif msg_type == "release_lock":
                async with doc_state.lock:
                    if doc_state.lock_owner_user_id == user.id:
                        doc_state.lock_owner_user_id = None
                        doc_state.lock_owner_email = None
                        await _broadcast(doc_state, {"type": "lock_update", "locked_by": None, "revision": doc_state.revision})
                        client = _get_redis_client()
                        if client is not None:
                            client.publish(
                                _redis_channel(project_id, run_id),
                                json.dumps({"type": "lock_update", "locked_by": None, "revision": doc_state.revision}),
                            )

            elif msg_type == "autosave":
                # Persist the latest XML to disk and broadcast to collaborators.
                xml = body.get("xml")
                if not isinstance(xml, str):
                    continue
                async with doc_state.lock:
                    if doc_state.lock_owner_user_id != user.id:
                        # Ignore writes from non-lock holders.
                        continue
                    doc_state.revision += 1
                    doc_state.xml = xml

                    # Persist to disk so refreshes and reconnects keep the latest XML.
                    run_dir = workspace_path(project_id) / "runs" / run_id
                    run_dir.mkdir(parents=True, exist_ok=True)
                    (run_dir / "drawio.xml").write_text(xml, encoding="utf-8")

                    # Append a lightweight timeline event so other consumers can replay updates.
                    session = SessionLocal()
                    try:
                        append_run_event(
                            session,
                            run_id,
                            "drawio_update",
                            {
                                "revision": doc_state.revision,
                                "by": {"user_id": user.id, "email": user.email},
                            },
                        )
                        session.commit()
                    finally:
                        session.close()

                    await _broadcast(
                        doc_state,
                        {
                            "type": "drawio_update",
                            "xml": doc_state.xml,
                            "revision": doc_state.revision,
                            "by": {"user_id": user.id, "email": user.email},
                        },
                    )
                    client = _get_redis_client()
                    if client is not None:
                        client.publish(
                            _redis_channel(project_id, run_id),
                            json.dumps(
                                {
                                    "type": "drawio_update",
                                    "xml": doc_state.xml,
                                    "revision": doc_state.revision,
                                    "by": {"user_id": user.id, "email": user.email},
                                }
                            ),
                        )

            # Unknown messages are ignored.

    except WebSocketDisconnect:
        pass
    finally:
        try:
            if doc_state is not None:
                doc_state.clients.discard(websocket)
                async with doc_state.lock:
                    # If the lock-holder disconnects, release the lock so the doc doesn't get stuck.
                    if user and user.id == doc_state.lock_owner_user_id:
                        doc_state.lock_owner_user_id = None
                        doc_state.lock_owner_email = None
                        await _broadcast(
                            doc_state,
                            {"type": "lock_update", "locked_by": None, "revision": doc_state.revision},
                        )
        except Exception:  # noqa: S110 — best-effort, non-fatal
            # Best-effort cleanup.
            pass
        db.close()

