from __future__ import annotations

from fastapi import APIRouter, WebSocket
from jose import JWTError, jwt
from sqlalchemy import select

from app.core.auth import require_project_role
from app.core.config import settings
from app.db.models import User
from app.db.session import SessionLocal
from app.services.model_realtime import ensure_channel

router = APIRouter()


def _user_from_access_token(token: str) -> User | None:
    db = SessionLocal()
    try:
        try:
            payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
            if payload.get("typ") != "access":
                return None
            email = payload.get("sub")
            if not isinstance(email, str):
                return None
        except JWTError:
            return None
        return db.scalar(select(User).where(User.email == email))
    finally:
        db.close()


@router.websocket("/projects/{pid}/models/{mid}")
async def model_ws(websocket: WebSocket, pid: str, mid: str) -> None:
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=1008)
        return

    db = SessionLocal()
    try:
        user = _user_from_access_token(token)
        if not user:
            await websocket.close(code=1008)
            return
        require_project_role(pid, {"Owner", "Editor", "Viewer"}, user, db)
        channel = await ensure_channel(pid, mid)
        await websocket.accept()
        channel.clients.add(websocket)
        await websocket.send_json({"type": "model_ws_connected", "project_id": pid, "model_id": mid})
        while True:
            # Keepalive/read loop. Clients may send ping messages.
            _ = await websocket.receive_text()
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass
    finally:
        try:
            channel = await ensure_channel(pid, mid)
            channel.clients.discard(websocket)
        except Exception:
            pass
        db.close()

